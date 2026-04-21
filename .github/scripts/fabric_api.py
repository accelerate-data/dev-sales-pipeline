"""
Fabric REST API wrapper for ephemeral workspace lifecycle management.

Commands:
  provision  --name NAME
             Find or create workspace + lakehouse. Writes IDs to GITHUB_OUTPUT.

  teardown   --name NAME
             Find workspace by name and delete it. Exits cleanly if not found.

  cleanup    --repo OWNER/REPO
             List all vibedata-ephemeral-* workspaces. Delete those whose PR is closed.

Authentication: GitHub OIDC via azure/login. No SPN credentials stored.
The workflow runs azure/login before invoking this script, establishing an
Azure CLI session. Token is acquired via: az account get-access-token.

Required env var:
  AZURE_KEYVAULT_URL — used by kv_utils to fetch vibedata-fabric-capacity-id
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request


FABRIC_API = "https://api.fabric.microsoft.com/v1"
GITHUB_API = "https://api.github.com"


# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_fabric_token() -> str:
    """Get a Fabric access token from the Azure CLI OIDC session."""
    result = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://api.fabric.microsoft.com"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)["accessToken"]


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def fabric_request(method: str, path: str, token: str, body: dict = None, retries: int = 3):
    """Make a Fabric REST API call with retry on 429/503."""
    url = f"{FABRIC_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"Rate limited, retrying in {retry_after}s…", flush=True)
                time.sleep(retry_after)
                continue
            body_text = e.read().decode(errors="replace")
            print(f"HTTP {e.code} {method} {url}: {body_text}", file=sys.stderr)
            raise
    raise RuntimeError(f"Failed after {retries} retries: {method} {path}")


# ─── Workspace helpers ─────────────────────────────────────────────────────────

def find_workspace_by_name(name: str, token: str) -> dict | None:
    resp = fabric_request("GET", "/workspaces", token)
    for ws in resp.get("value", []):
        if ws["displayName"] == name:
            return ws
    return None


def find_lakehouse_by_name(workspace_id: str, name: str, token: str) -> dict | None:
    resp = fabric_request("GET", f"/workspaces/{workspace_id}/items", token)
    for item in resp.get("value", []):
        if item["type"] == "Lakehouse" and item["displayName"] == name:
            return item
    return None


def write_github_output(key: str, value: str):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"GITHUB_OUTPUT not set; {key}={value}")


_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def resolve_capacity_id(raw: str, token: str) -> str:
    """Return the Fabric capacity GUID from either a bare GUID or an ARM resource ID.

    Some Key Vault setups store the full ARM resource ID
    (/subscriptions/.../providers/Microsoft.Fabric/capacities/<name>) instead of
    the GUID. When that form is detected, the Fabric capacities API is queried and
    the match is made on display name (case-insensitive).
    """
    if _GUID_RE.match(raw):
        return raw
    if raw.startswith("/subscriptions/"):
        arm_name = raw.rstrip("/").rsplit("/", 1)[-1].lower()
        print(f"FABRIC_CAPACITY_ID is an ARM resource ID; resolving '{arm_name}' via Fabric API…", flush=True)
        resp = fabric_request("GET", "/capacities", token)
        for cap in resp.get("value", []):
            if cap.get("displayName", "").lower() == arm_name:
                guid = cap["id"]
                print(f"Resolved capacity GUID: {guid}", flush=True)
                return guid
        raise RuntimeError(
            f"No Fabric capacity with displayName '{arm_name}' found via GET /v1/capacities. "
            f"Store the capacity GUID directly in the KV secret to avoid this lookup."
        )
    raise RuntimeError(f"FABRIC_CAPACITY_ID is neither a GUID nor an ARM resource ID: {raw!r}")


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_provision(args):
    token = get_fabric_token()
    capacity_id = resolve_capacity_id(os.environ["FABRIC_CAPACITY_ID"], token)
    name = args.name

    ws = find_workspace_by_name(name, token)
    if ws:
        workspace_id = ws["id"]
        print(f"Reusing existing workspace: {name} ({workspace_id})", flush=True)
    else:
        print(f"Creating workspace: {name}", flush=True)
        ws = fabric_request("POST", "/workspaces", token, {
            "displayName": name,
            "capacityId": capacity_id,
        })
        workspace_id = ws["id"]
        print(f"Workspace created: {workspace_id}", flush=True)

    lh = find_lakehouse_by_name(workspace_id, "vibedata-ephemeral-lh", token)
    if lh:
        lakehouse_id = lh["id"]
        print(f"Reusing existing lakehouse: vibedata-ephemeral-lh ({lakehouse_id})", flush=True)
    else:
        print("Creating lakehouse: vibedata-ephemeral-lh", flush=True)
        lh = fabric_request("POST", f"/workspaces/{workspace_id}/items", token, {
            "displayName": "vibedata-ephemeral-lh",
            "type": "Lakehouse",
        })
        lakehouse_id = lh["id"]
        print(f"Lakehouse created: {lakehouse_id}", flush=True)

    write_github_output("workspace_id", workspace_id)
    write_github_output("lakehouse_id", lakehouse_id)
    print(f"Provision complete: workspace={workspace_id} lakehouse={lakehouse_id}", flush=True)


def cmd_teardown(args):
    token = get_fabric_token()
    ws = find_workspace_by_name(args.name, token)
    if not ws:
        print(f"Workspace not found: {args.name} — nothing to teardown.", flush=True)
        return
    workspace_id = ws["id"]
    print(f"Deleting workspace: {args.name} ({workspace_id})", flush=True)
    fabric_request("DELETE", f"/workspaces/{workspace_id}", token)
    print("Workspace deleted.", flush=True)


def cmd_cleanup(args):
    token = get_fabric_token()
    gh_token = os.environ.get("GH_TOKEN", "")
    repo = args.repo

    resp = fabric_request("GET", "/workspaces", token)
    ephemeral = [
        ws for ws in resp.get("value", [])
        if ws["displayName"].startswith("vibedata-ephemeral-")
    ]
    print(f"Found {len(ephemeral)} ephemeral workspace(s).", flush=True)
    deleted = 0

    for ws in ephemeral:
        name = ws["displayName"]
        parts = name.split("-")
        if len(parts) < 3 or not parts[-1].isdigit():
            continue
        pr_number = parts[-1]

        pr_url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
        req = urllib.request.Request(pr_url)
        req.add_header("Authorization", f"Bearer {gh_token}")
        req.add_header("Accept", "application/vnd.github+json")

        try:
            with urllib.request.urlopen(req) as r:
                pr_state = json.loads(r.read()).get("state", "unknown")
        except urllib.error.HTTPError as e:
            pr_state = "not_found" if e.code == 404 else None
            if pr_state is None:
                print(f"  Skipping {name}: GitHub API error {e.code}", flush=True)
                continue

        if pr_state in ("closed", "not_found"):
            print(f"  Deleting orphan: {name} (PR #{pr_number} is {pr_state})", flush=True)
            try:
                fabric_request("DELETE", f"/workspaces/{ws['id']}", token)
                deleted += 1
            except Exception as exc:
                print(f"  Failed to delete {name}: {exc}", file=sys.stderr)
        else:
            print(f"  Skipping: {name} (PR #{pr_number} is {pr_state})", flush=True)

    print(f"Cleanup complete: {deleted} workspace(s) deleted.", flush=True)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fabric ephemeral workspace CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("provision").add_argument("--name", required=True)
    sub.add_parser("teardown").add_argument("--name", required=True)
    sub.add_parser("cleanup").add_argument("--repo", required=True)
    args = parser.parse_args()
    {"provision": cmd_provision, "teardown": cmd_teardown, "cleanup": cmd_cleanup}[args.command](args)


if __name__ == "__main__":
    main()
