"""
Fabric REST API wrapper for ephemeral workspace lifecycle management.

Commands:
  provision  --name NAME --capacity-id ID
             Find or create workspace + lakehouse. Writes IDs to GITHUB_OUTPUT.

  teardown   --name NAME
             Find workspace by name and delete it. Exits cleanly if not found.

  cleanup    --repo OWNER/REPO
             List all ephemeral-* workspaces. Delete those whose PR is closed.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error


FABRIC_API = "https://api.fabric.microsoft.com/v1"
ENTRA_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GITHUB_API = "https://api.github.com"


# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_fabric_token() -> str:
    tenant = os.environ["FABRIC_TENANT_ID"]
    client_id = os.environ["FABRIC_CLIENT_ID"]
    client_secret = os.environ["FABRIC_CLIENT_SECRET"]

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://api.fabric.microsoft.com/.default",
    }).encode()

    url = ENTRA_TOKEN_URL.format(tenant=tenant)
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


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


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_provision(args):
    token = get_fabric_token()
    name = args.name
    capacity_id = args.capacity_id

    # Find or create workspace
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

    # Find or create lakehouse
    lh = find_lakehouse_by_name(workspace_id, "ephemeral_lh", token)
    if lh:
        lakehouse_id = lh["id"]
        print(f"Reusing existing lakehouse: ephemeral_lh ({lakehouse_id})", flush=True)
    else:
        print("Creating lakehouse: ephemeral_lh", flush=True)
        lh = fabric_request("POST", f"/workspaces/{workspace_id}/items", token, {
            "displayName": "ephemeral_lh",
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
    repo = args.repo  # owner/repo

    resp = fabric_request("GET", "/workspaces", token)
    all_workspaces = resp.get("value", [])

    ephemeral = [
        ws for ws in all_workspaces
        if ws["displayName"].startswith("ephemeral-")
    ]

    print(f"Found {len(ephemeral)} ephemeral workspace(s).", flush=True)
    deleted = 0

    for ws in ephemeral:
        name = ws["displayName"]  # ephemeral-{repo}-{pr_number}
        parts = name.split("-")
        if len(parts) < 3:
            continue

        pr_number = parts[-1]
        if not pr_number.isdigit():
            continue

        # Check if PR is still open
        pr_url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
        req = urllib.request.Request(pr_url)
        req.add_header("Authorization", f"Bearer {gh_token}")
        req.add_header("Accept", "application/vnd.github+json")

        try:
            with urllib.request.urlopen(req) as r:
                pr = json.loads(r.read())
            pr_state = pr.get("state", "unknown")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                pr_state = "not_found"
            else:
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

    p_prov = sub.add_parser("provision")
    p_prov.add_argument("--name", required=True)
    p_prov.add_argument("--capacity-id", required=True)

    p_tear = sub.add_parser("teardown")
    p_tear.add_argument("--name", required=True)

    p_clean = sub.add_parser("cleanup")
    p_clean.add_argument("--repo", required=True)

    args = parser.parse_args()

    if args.command == "provision":
        cmd_provision(args)
    elif args.command == "teardown":
        cmd_teardown(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)


if __name__ == "__main__":
    main()
