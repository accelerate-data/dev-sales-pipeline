"""
Post a PR comment with the ephemeral workspace URL, static analysis scorecard,
and the developer checklist.

Reads JSON reports from the reports/ directory.
Posts via the GitHub CLI (gh) using the GH_TOKEN env var.
"""

import json
import os
import subprocess
import sys
import tempfile


FABRIC_WORKSPACE_URL = "https://app.fabric.microsoft.com/groups/{workspace_id}/list"


def load_report(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def icon(passed: bool) -> str:
    return "✅" if passed else "❌"


def format_ruff(report: list) -> tuple[str, int]:
    issues = len(report) if isinstance(report, list) else 0
    status = icon(issues == 0)
    detail = f"{issues} issue(s)" if issues else "No issues"
    return status, detail


def format_sqlfluff(report) -> tuple[str, str]:
    file_results = report if isinstance(report, list) else report.get("files", [])
    violations = []
    for file_result in file_results:
        violations.extend(file_result.get("violations", []))
    count = len(violations)
    status = icon(count == 0)
    detail = f"{count} violation(s)" if count else "No violations"
    return status, detail


def format_gitleaks(report: dict | list) -> tuple[str, int]:
    findings = report if isinstance(report, list) else report.get("findings", [])
    count = len(findings)
    status = icon(count == 0)
    detail = f"**{count} secret(s) found — BLOCK**" if count else "No secrets found"
    return status, detail


def format_scorecard(report: dict) -> tuple[str, str]:
    if not report:
        return "⚠️", "Scorecard unavailable"
    desc = report.get("description_coverage_pct", 0)
    pk = report.get("pk_test_coverage_pct", 0)
    violations = report.get("naming_violation_count", 0)
    status = icon(desc >= 80 and pk == 100 and violations == 0)
    detail = f"Doc: {desc}% | PK tests: {pk}% | Naming: {violations} violation(s)"
    return status, detail


def build_comment(
    workspace_id: str,
    workspace_name: str,
    head_branch: str,
    ruff: list,
    sqlfluff: dict,
    gitleaks: dict | list,
    scorecard: dict,
    analysis_outcome: str,
) -> str:
    ws_url = FABRIC_WORKSPACE_URL.format(workspace_id=workspace_id)

    ruff_icon, ruff_detail = format_ruff(ruff)
    sql_icon, sql_detail = format_sqlfluff(sqlfluff)
    gl_icon, gl_detail = format_gitleaks(gitleaks)
    sc_icon, sc_detail = format_scorecard(scorecard)

    return f"""## Ephemeral Workspace Ready

**Workspace:** [{workspace_name}]({ws_url})
**Branch:** `{head_branch}`

### Static Analysis
| Check | Status | Details |
|-------|--------|---------|
| ruff | {ruff_icon} | {ruff_detail} |
| sqlfluff | {sql_icon} | {sql_detail} |
| gitleaks | {gl_icon} | {gl_detail} |
| dbt scorecard | {sc_icon} | {sc_detail} |

### Developer Checklist
- [ ] Open the workspace and run the notebook cells in order:
  - **Cell: Clone** — `dbt clone --select state:modified+` *(resets D and D+ to prod state)*
  - **Cell: Build** — `dbt build --select state:modified+ --defer`
  - **Cell: Test** — `dbt test --select state:modified+ --store-failures`
- [ ] Review any dbt test failures in the workspace
- [ ] Validate results meet acceptance criteria from intent spec
- [ ] Mark PR ready for review

> CI reports available as workflow artifacts.
"""


def main():
    workspace_id = os.environ.get("EPHEMERAL_WORKSPACE_ID", "")
    workspace_name = os.environ.get("EPHEMERAL_WORKSPACE_NAME", "")
    head_branch = os.environ.get("HEAD_BRANCH", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    repo = os.environ.get("REPO", "")
    analysis_outcome = os.environ.get("STATIC_ANALYSIS_OUTCOME", "unknown")

    ruff = load_report("reports/ruff.json")
    sqlfluff_report = load_report("reports/sqlfluff.json")
    gitleaks = load_report("reports/gitleaks.json")
    scorecard = load_report("reports/scorecard.json")

    comment = build_comment(
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        head_branch=head_branch,
        ruff=ruff,
        sqlfluff=sqlfluff_report,
        gitleaks=gitleaks,
        scorecard=scorecard,
        analysis_outcome=analysis_outcome,
    )

    # Write to temp file and post via gh CLI
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(comment)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["gh", "pr", "comment", pr_number,
             "--repo", repo,
             "--body-file", tmp_path,
             "--edit-last"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            # No existing comment to edit — create a new one
            result = subprocess.run(
                ["gh", "pr", "comment", pr_number,
                 "--repo", repo,
                 "--body-file", tmp_path],
                capture_output=True, text=True
            )
        if result.returncode != 0:
            print(f"Failed to post PR comment: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("PR comment posted.", flush=True)
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
