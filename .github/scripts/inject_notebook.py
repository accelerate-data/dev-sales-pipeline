"""
Notebook injection script.

Reads the notebook matching NOTEBOOK_GLOB from the repo, substitutes the
Parameters cell with ephemeral workspace values, inserts a Clone cell before
the Build cell, then uploads the modified notebook to the Fabric workspace
via the Items API.

The notebook in the repo stores template placeholders ({{BRANCH}}, etc.).
This script substitutes them at CI runtime without committing back to the branch,
avoiding re-triggering the CI workflow.

Authentication: GitHub OIDC via azure/login (no SPN credentials stored).
Token acquired via: az account get-access-token.

Environment variables required:
  AZURE_KEYVAULT_URL  — Key Vault URI (used by kv_utils to fetch GitHub App secrets)
  EPHEMERAL_WORKSPACE_ID, EPHEMERAL_WORKSPACE_NAME, EPHEMERAL_LAKEHOUSE_ID
  NOTEBOOK_GLOB       — glob pattern (e.g. intents/**/notebook.ipynb)
  HEAD_BRANCH         — feature branch name
  REPO_URL            — GitHub repo clone URL
  GH_APP_ID_KV_NAME, GH_INSTALLATION_ID_KV_NAME, GH_APP_PEM_KV_NAME  — KV secret name references
"""

import base64
import copy
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


FABRIC_API = "https://api.fabric.microsoft.com/v1"


def get_fabric_token() -> str:
    """Get a Fabric access token from the Azure CLI OIDC session."""
    result = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://api.fabric.microsoft.com"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)["accessToken"]


def fabric_request(method: str, path: str, token: str, body: dict = None) -> dict:
    url = f"{FABRIC_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} {method} {url}: {e.read().decode(errors='replace')}", file=sys.stderr)
        raise


def find_notebook(glob_pattern: str) -> str:
    matches = glob.glob(glob_pattern, recursive=True)
    if not matches:
        print(f"No notebook found matching: {glob_pattern}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Multiple notebooks found: {matches}. Using first: {matches[0]}", flush=True)
    return matches[0]


def substitute_parameters_cell(notebook: dict) -> dict:
    """Replace placeholder values in the Parameters cell."""
    nb = copy.deepcopy(notebook)

    workspace_id = os.environ["EPHEMERAL_WORKSPACE_ID"]
    workspace_name = os.environ["EPHEMERAL_WORKSPACE_NAME"]
    lakehouse_id = os.environ["EPHEMERAL_LAKEHOUSE_ID"]
    branch = os.environ["HEAD_BRANCH"]
    repo_url = os.environ["REPO_URL"]
    github_app_id = os.environ.get("GH_APP_ID_KV_NAME", "")
    github_installation_id = os.environ.get("GH_INSTALLATION_ID_KV_NAME", "")
    github_pem_secret = os.environ.get("GH_APP_PEM_KV_NAME", "")
    vault_url = os.environ.get("AZURE_KEYVAULT_URL", "")

    # Build the substituted parameters cell source
    new_params = [
        "# Parameters — injected by CI (do not edit manually)\n",
        f'command = ["dbt deps", "dbt build --select state:modified+ --defer --state ./prod-state --target prod", "dbt test --select state:modified+ --store-failures --target prod"]\n',
        f'repo_url = "{repo_url}"\n',
        f'repo_branch = "{branch}"\n',
        f'github_app_id = "{github_app_id}"\n',
        f'github_installation_id = "{github_installation_id}"\n',
        f'github_pem_secret = "{github_pem_secret}"\n',
        f'vault_url = "{vault_url}"\n',
        f'lakehouse_name = "vibedata-ephemeral-lh"\n',
        f'lakehouse_id = "{lakehouse_id}"\n',
        f'workspace_id = "{workspace_id}"\n',
        f'workspace_name = "{workspace_name}"\n',
        f'schema_name = "dbo"\n',
    ]

    # Find and replace the Parameters cell (first cell with "Parameters" comment or tag)
    params_cell_idx = None
    for i, cell in enumerate(nb.get("cells", [])):
        source = "".join(cell.get("source", []))
        if "Parameters" in source and cell.get("cell_type") == "code":
            params_cell_idx = i
            break

    if params_cell_idx is None:
        # Insert as the first code cell if no Parameters cell found
        print("Warning: No Parameters cell found. Inserting at position 0.", flush=True)
        params_cell_idx = 0
        nb["cells"].insert(0, {
            "cell_type": "code",
            "source": new_params,
            "metadata": {"tags": ["parameters"]},
            "outputs": [],
            "execution_count": None,
        })
    else:
        nb["cells"][params_cell_idx]["source"] = new_params

    return nb, params_cell_idx


def insert_clone_cell(notebook: dict, after_idx: int) -> dict:
    """Insert a Clone cell after the Parameters cell."""
    nb = copy.deepcopy(notebook)

    clone_cell = {
        "cell_type": "code",
        "source": [
            "# Clone: Reset D and D+ to prod state\n",
            "# Re-run this cell at any time to reset between test iterations.\n",
            "from dbt.adapters.fabricspark.notebook import run_dbt_job, DbtJobConfig, RepoConfig, ConnectionConfig\n",
            "\n",
            "clone_config = DbtJobConfig(\n",
            '    command=["dbt deps", "dbt clone --select state:modified+ --defer --state ./prod-state --target prod"],\n',
            "    repo=RepoConfig(\n",
            "        url=repo_url,\n",
            "        branch=repo_branch,\n",
            "        github_app_id=github_app_id,\n",
            "        github_installation_id=github_installation_id,\n",
            "        github_pem_secret=github_pem_secret,\n",
            "        vault_url=vault_url,\n",
            "    ),\n",
            "    connection=ConnectionConfig(\n",
            '        lakehouse_name=lakehouse_name,\n',
            "        lakehouse_id=lakehouse_id,\n",
            "        workspace_id=workspace_id,\n",
            "        workspace_name=workspace_name,\n",
            "        schema_name=schema_name,\n",
            "    ),\n",
            ")\n",
            "run_dbt_job(clone_config)\n",
        ],
        "metadata": {"tags": ["ci-injected-clone"]},
        "outputs": [],
        "execution_count": None,
    }

    nb["cells"].insert(after_idx + 1, clone_cell)
    return nb


def find_existing_notebook(workspace_id: str, display_name: str, token: str) -> str | None:
    """Return item ID of an existing notebook with the given display name, or None."""
    resp = fabric_request("GET", f"/workspaces/{workspace_id}/items", token)
    for item in resp.get("value", []):
        if item["type"] == "Notebook" and item["displayName"] == display_name:
            return item["id"]
    return None


def upload_notebook(workspace_id: str, display_name: str, notebook: dict, token: str):
    """Create or update a notebook in the Fabric workspace via Items API."""
    nb_content = base64.b64encode(json.dumps(notebook).encode()).decode()

    existing_id = find_existing_notebook(workspace_id, display_name, token)

    if existing_id:
        print(f"Updating existing notebook: {display_name} ({existing_id})", flush=True)
        fabric_request("POST", f"/workspaces/{workspace_id}/items/{existing_id}/updateDefinition", token, {
            "definition": {
                "parts": [{
                    "path": "notebook-content.ipynb",
                    "payload": nb_content,
                    "payloadType": "InlineBase64",
                }]
            }
        })
    else:
        print(f"Creating notebook: {display_name}", flush=True)
        fabric_request("POST", f"/workspaces/{workspace_id}/items", token, {
            "displayName": display_name,
            "type": "Notebook",
            "definition": {
                "parts": [{
                    "path": "notebook-content.ipynb",
                    "payload": nb_content,
                    "payloadType": "InlineBase64",
                }]
            }
        })

    print("Notebook upload complete.", flush=True)


def main():
    token = get_fabric_token()
    workspace_id = os.environ["EPHEMERAL_WORKSPACE_ID"]
    notebook_glob = os.environ["NOTEBOOK_GLOB"]

    notebook_path = find_notebook(notebook_glob)
    print(f"Found notebook: {notebook_path}", flush=True)

    with open(notebook_path) as f:
        notebook = json.load(f)

    # Step 1: Substitute Parameters cell
    notebook, params_idx = substitute_parameters_cell(notebook)
    print(f"Parameters cell substituted (cell index {params_idx}).", flush=True)

    # Step 2: Insert Clone cell after Parameters cell
    notebook = insert_clone_cell(notebook, params_idx)
    print("Clone cell inserted.", flush=True)

    # Step 3: Upload to Fabric workspace
    display_name = os.path.splitext(os.path.basename(notebook_path))[0]
    upload_notebook(workspace_id, display_name, notebook, token)


if __name__ == "__main__":
    main()
