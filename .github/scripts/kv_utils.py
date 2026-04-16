"""
Azure Key Vault secret fetcher.

Authenticates via Azure CLI (pre-authenticated by azure/login OIDC step
using the KV UAMI). No credentials stored — GitHub OIDC issues a
short-lived token exchanged for an Azure access token by azure/login.

CLI commands:
  fetch-fabric       Fetches Fabric config (capacity ID) → writes to $GITHUB_ENV
  fetch-github-app   Fetches GitHub App config → writes to $GITHUB_ENV

Required env var:
  AZURE_KEYVAULT_URL — Key Vault vault URI
"""

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request

KV_API_VERSION = "7.4"


def _get_kv_token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://vault.azure.net"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)["accessToken"]


def get_secret(secret_name: str) -> str:
    """Fetch a single secret value from Key Vault by name."""
    vault_url = os.environ["AZURE_KEYVAULT_URL"].rstrip("/")
    token = _get_kv_token()
    url = f"{vault_url}/secrets/{secret_name}?api-version={KV_API_VERSION}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["value"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Failed to fetch KV secret '{secret_name}': HTTP {e.code} — {body}") from e


def write_env(key: str, value: str):
    """Write a key=value pair to $GITHUB_ENV for use in subsequent steps."""
    env_file = os.environ.get("GITHUB_ENV")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"[kv_utils] {key}={value}")


def cmd_fetch_fabric():
    """Fetch Fabric capacity ID and write to GITHUB_ENV."""
    capacity_id = get_secret("vibedata-fabric-capacity-id")
    write_env("FABRIC_CAPACITY_ID", capacity_id)
    print("Fetched: FABRIC_CAPACITY_ID", flush=True)


def cmd_fetch_github_app():
    """Fetch GitHub App ID and installation ID and write to GITHUB_ENV.
    The PEM secret name is passed through as-is — the Fabric notebook
    fetches the actual PEM at runtime using its own KV access.
    """
    app_id_secret_name = os.environ.get("GH_APP_ID_KV_NAME", "vibedata-github-app-id")
    install_id_secret_name = os.environ.get("GH_INSTALLATION_ID_KV_NAME", "vibedata-github-installation-id")

    app_id = get_secret(app_id_secret_name)
    installation_id = get_secret(install_id_secret_name)

    write_env("GH_APP_ID_KV_NAME", app_id)
    write_env("GH_INSTALLATION_ID_KV_NAME", installation_id)
    print("Fetched: GH_APP_ID_KV_NAME, GH_INSTALLATION_ID_KV_NAME", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fetch secrets from Azure Key Vault")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch-fabric", help="Fetch Fabric capacity ID → GITHUB_ENV")
    sub.add_parser("fetch-github-app", help="Fetch GitHub App ID + installation ID → GITHUB_ENV")
    args = parser.parse_args()

    if args.command == "fetch-fabric":
        cmd_fetch_fabric()
    elif args.command == "fetch-github-app":
        cmd_fetch_github_app()


if __name__ == "__main__":
    main()
