# Design: Ephemeral Fabric CI Workflow

**Date:** 2026-04-15  
**Status:** Approved  
**Scope:** GitHub Actions CI workflow to deploy feature branches to ephemeral Microsoft Fabric workspaces for PR validation

---

## 1. Context

Vibedata enforces branch-based development. Every intent (feature branch) gets an isolated ephemeral Fabric workspace for development and testing against real data. This CI workflow automates the provisioning, static analysis, and developer notification phases of that lifecycle.

**Phases in scope:**
- Design phase (upstream, already handled by vd-studio) — generates dbt models + Fabric notebook
- **Ephemeral Workspace Deployment (this spec)** — CI workflow triggered on PR open/update
- Production Deployment (out of scope — handled by separate CD workflow)

---

## 2. Repository Structure

Two repositories involved:

### `accelerate-data/vibedata-workflows` (central, new)
```
.github/workflows/
  domain-ci.yml            ← reusable workflow (all CI logic lives here)
  workspace-cleanup.yml    ← daily cron for orphaned workspace cleanup
```

### `accelerate-data/dev-sales-pipeline` (domain repo — this repo)
```
.github/workflows/
  ci.yml                   ← thin caller (~20 lines), calls vibedata-workflows
ci-config.yml                 ← domain-specific config (workspace IDs, lakehouse, etc.)
intents/**/notebook.ipynb  ← generated in design phase, injected by CI at runtime
```

The domain `ci.yml` caller:
```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, closed]
    branches: [main]

jobs:
  ci:
    uses: accelerate-data/vibedata-workflows/.github/workflows/domain-ci.yml@main
    secrets: inherit
```

---

## 3. Domain Config File

`ci-config.yml` lives in the root of each domain repo. It holds domain-specific values that are not secrets.

```yaml
domain: sales
prod_workspace_id: e8d68e63-2a03-47c9-ba7b-27ff316b001b
prod_workspace_name: sampledata
prod_lakehouse_id: fd8a5cce-a23c-4173-b092-8c34b10f84e0
prod_lakehouse_name: salesforce
prod_schema: sales_datamart
notebook_glob: "intents/**/notebook.ipynb"
```

---

## 4. Org-Level GitHub Secrets

Stored at the GitHub Organisation level, inherited by all domain repos via `secrets: inherit`:

| Secret | Purpose |
|--------|---------|
| `FABRIC_TENANT_ID` | Entra ID tenant for SPN auth |
| `FABRIC_CLIENT_ID` | SPN client ID (Fabric Capacity Admin role) |
| `FABRIC_CLIENT_SECRET` | SPN client secret |
| `FABRIC_CAPACITY_ID` | Fabric capacity to assign ephemeral workspaces to |
| `GITHUB_APP_ID` | GitHub App ID (used by notebook at runtime to clone repo) |
| `GITHUB_INSTALLATION_ID` | GitHub App installation ID |
| `GITHUB_APP_PEM` | GitHub App private key (PEM) |
| `AZURE_KEYVAULT_URL` | Key Vault URL for notebook runtime secrets |

---

## 5. Workflow Jobs

### 5.1 Triggers

```
pull_request types: [opened, synchronize, reopened] → preflight, provision, static-analysis, notify
pull_request types: [closed]                         → teardown
```

### 5.2 Job: `preflight`

**Runs on:** `opened / synchronize / reopened`

1. **Rebase check** — fails if the feature branch is behind `main`:
   ```bash
   behind_by=$(gh api repos/{owner}/{repo}/compare/main...{head_sha} --jq '.behind_by')
   [ "$behind_by" -gt 0 ] && exit 1
   ```
   Fail message: `"Branch is N commits behind main. Please rebase before CI can proceed."`

2. **Parse `ci-config.yml`** — exports all domain config values as job outputs for downstream jobs.

### 5.3 Job: `provision`

**Needs:** `preflight`

Idempotent — safe to re-run on every PR push.

**Steps:**
1. Get SPN access token from Entra ID (`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`, scope: `https://api.fabric.microsoft.com/.default`)
2. **Find or create workspace:**
   - `GET /v1/workspaces` → filter by `displayName = "ephemeral-{repo}-{pr_number}"`
   - If not found: `POST /v1/workspaces` with `{ "displayName": "ephemeral-{repo}-{pr_number}", "capacityId": "{FABRIC_CAPACITY_ID}" }`
3. **Find or create lakehouse:**
   - `GET /v1/workspaces/{id}/items` → filter by type `Lakehouse` and name `ephemeral_lh`
   - If not found: `POST /v1/workspaces/{id}/items` with `{ "displayName": "ephemeral_lh", "type": "Lakehouse" }`
4. Output: `ephemeral_workspace_id`, `ephemeral_lakehouse_id`

The workspace is **not linked to Git** — fully independent. All code fetching is handled by the notebook at runtime.

### 5.4 Job: `static-analysis`

**Needs:** `provision`

Two parallel tracks + notebook injection:

**Track A — Linting and secret scan:**
```bash
pip install ruff sqlfluff gitleaks

ruff check . --output-format json > reports/ruff.json
sqlfluff lint models/ --dialect sparksql --format json > reports/sqlfluff.json
gitleaks detect --source . --report-format json --report-path reports/gitleaks.json
```

**Track B — dbt doc/convention scorecard:**
```bash
# dbt parse is offline (no DB connection) but needs env vars to resolve profiles.yml
# CI sets dummy values for parse-only env vars
export WORKSPACE_ID=dummy WORKSPACE_NAME=dummy LAKEHOUSE=dummy LAKEHOUSE_ID=dummy SCHEMA=dummy
dbt parse --profiles-dir .
python scripts/scorecard.py --manifest target/manifest.json > reports/scorecard.json
```

`scorecard.py` reads `AGENTS.md` from the repo root (each domain controls its own naming rules; skips convention checks gracefully if absent) and checks:
- Description coverage % across models and columns
- Test coverage: `not_null` + `unique` on all PKs
- Naming convention compliance against `AGENTS.md` patterns

All outputs are JSON artifacts — persisted to Postgres in a future iteration.

**Notebook injection** (after linting, using provision outputs):

The workflow reads the notebook matching `notebook_glob`, substitutes the Parameters cell in-memory (no branch commit — avoids triggering a re-run), and pushes the modified notebook to the Fabric workspace via the Items API.

The notebook in the repo stores template placeholders:
```python
# Parameters (template — substituted by CI at runtime)
repo_branch    = "{{BRANCH}}"
workspace_id   = "{{WORKSPACE_ID}}"
workspace_name = "{{WORKSPACE_NAME}}"
lakehouse_name = "{{LAKEHOUSE_NAME}}"
lakehouse_id   = "{{LAKEHOUSE_ID}}"
command        = ["{{COMMANDS}}"]
```

CI substitutes at runtime:
```python
repo_branch    = "{head_branch}"
workspace_id   = "{ephemeral_workspace_id}"
workspace_name = "ephemeral-{repo}-{pr_number}"
lakehouse_name = "ephemeral_lh"
lakehouse_id   = "{ephemeral_lakehouse_id}"
command        = [
    "dbt deps",
    "dbt build --select state:modified+ --defer --state ./prod-state --target prod",
    "dbt test --select state:modified+ --store-failures --target prod"
]
```

CI also inserts a **Clone cell** immediately before the Build cell:
```python
# Clone: reset D and D+ to prod state (re-run this cell to reset between test iterations)
clone_command = [
    "dbt deps",
    "dbt clone --select state:modified+ --defer --state ./prod-state --target prod"
]
result = run_dbt_job(DbtJobConfig(command=clone_command, repo=..., connection=...))
```

The modified notebook is pushed via:
```
# First run: create the notebook
POST /v1/workspaces/{ephemeral_workspace_id}/items

# Subsequent runs: look up existing notebook by type + displayName, then update
GET  /v1/workspaces/{ephemeral_workspace_id}/items → filter type=Notebook, displayName matches notebook filename
PATCH /v1/workspaces/{ephemeral_workspace_id}/items/{notebookId}/updateDefinition
```

### 5.5 Job: `notify`

**Needs:** `static-analysis`

Posts a single PR comment:

```markdown
## Ephemeral Workspace Ready

**Workspace:** [ephemeral-{repo}-{pr_number}]({fabric_workspace_url})
**Branch:** `{head_branch}` (rebased onto main ✓)

### Static Analysis
| Check | Status | Details |
|-------|--------|---------|
| ruff | ✅/❌ | N issues |
| sqlfluff | ✅/⚠️ | N warnings |
| gitleaks | ✅/❌ | N secrets found |
| Doc coverage | N% | N/N models documented |
| Test coverage | N% | N/N PKs covered |

### Developer Checklist
- [ ] Open the workspace and run the notebook
  - Cell: **Clone** — `dbt clone --select state:modified+` (resets D and D+ to prod state)
  - Cell: **Build** — `dbt build --select state:modified+ --defer`
  - Cell: **Test** — `dbt test --select state:modified+ --store-failures`
- [ ] Review any dbt test failures in the workspace
- [ ] Validate results meet acceptance criteria from `intents/{intent-id}/intent.md`
- [ ] Mark PR ready for review
```

### 5.6 Job: `teardown`

**Runs on:** `closed` (merge or cancel)

```bash
# Find workspace by name, delete it
workspace_id=$(GET /v1/workspaces | jq -r '.value[] | select(.displayName=="ephemeral-{repo}-{pr_number}") | .id')
[ -n "$workspace_id" ] && DELETE /v1/workspaces/$workspace_id
```

Exits cleanly if workspace not found (was never provisioned, or already cleaned up).

---

## 6. Orphan Cleanup Cron

**File:** `workspace-cleanup.yml` in `vibedata-workflows`  
**Schedule:** Daily

```bash
# List all ephemeral-* workspaces
# For each: parse repo + pr_number from displayName
# Check GitHub API: is the PR still open?
# If closed / merged / not found → DELETE /v1/workspaces/{id}
```

Safety net for workspaces whose teardown job failed or whose PR was force-closed.

---

## 7. Notebook Cell Structure (Final)

After CI injection, the notebook in the Fabric workspace has:

| Cell | Type | Content |
|------|------|---------|
| 1 | Parameters | Runtime config: branch, workspace IDs, lakehouse IDs, commands |
| 2 | Code | `pip install vd-dbt-fabricspark` |
| 3 | Code | **Clone** — `dbt clone --select state:modified+ --defer` (inserted by CI) |
| 4 | Code | **Build + Test** — `dbt build` + `dbt test --store-failures` |

The developer can re-run Cell 3 at any time to reset D and D+ back to prod state between test iterations.

---

## 8. dbt Prod Manifest (Slim CI Deferral)

Slim CI (`--defer --state ./prod-state`) requires a `manifest.json` from the latest production deployment as the diff baseline.

- The CD workflow (separate) uploads `target/manifest.json` as a GitHub Actions artifact after each tagged prod release
- CI downloads the artifact from the latest tag — not from the latest `main` commit, since production tracks tags not raw commits
- The artifact is placed at `./prod-state/manifest.json` before notebook injection

---

## 9. Workspace Naming Convention

```
ephemeral-{github_repo_name}-{pr_number}
```

Examples:
- `ephemeral-dev-sales-pipeline-42`
- `ephemeral-dev-finance-pipeline-7`

Deterministic — always derivable from PR context. No need to persist workspace IDs across jobs (can always be looked up by name).

---

## 10. Out of Scope

- CD workflow (post-merge deployment to prod workspace)
- Production workspace provisioning
- dbt Semantic Layer / Elementary monitoring setup
- Postgres persistence for scorecards (JSON artifact output for now)
- Reusable composite actions decomposition (future optimization)
