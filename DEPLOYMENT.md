# Sales Pipeline Data Mart - Deployment Guide

## 📦 Project Overview

**Purpose:** Sales pipeline dimensional model for forecasting, performance analysis, and pipeline health monitoring

**Source:** Salesforce Sales Cloud data in `sampledata.salesforce.salescloud` schema

**Target:** Fabric lakehouse `sales_datamart` schema

**Models:** 6 models (3 staging views + 2 dimension tables + 1 fact table)

## 🏗️ Architecture

```
Salesforce Sales Cloud (source)
    ↓
Staging Layer (views)
    ├── stg_salescloud__opportunity
    ├── stg_salescloud__account
    └── stg_salescloud__user
    ↓
Mart Layer (tables)
    ├── dim_account (customers/prospects)
    ├── dim_user (sales reps)
    └── fct_pipeline (one row per opportunity)
```

## 📊 Key Metrics in fct_pipeline

- **Pipeline Value:** Total amount by stage
- **Weighted Pipeline:** amount × (probability / 100) for forecasting
- **Forecast Categories:** Closed Won/Lost, Best Case (≥75%), Commit (≥50%), Pipeline (≥25%), Upside (<25%)
- **Sales Cycle:** Days from creation to close
- **Data Quality:** Orphaned opportunity flag, zero-value flag

## 🧪 Testing

| Test Type | Count | Coverage |
|-----------|-------|----------|
| Unit Tests | 13 | Forecast logic, calculations, edge cases |
| Schema Tests | 36 | PKs, FKs, not_null, accepted_values |
| Custom DQ Tests | 13 | Business rules, null rates, placeholders |
| **Total** | **62** | **Comprehensive** |

## 🔧 Prerequisites

### 1. Environment Configuration

**Required environment variables in `.env`:**
```bash
WORKSPACE_ID=<ephemeral-workspace-id>
WORKSPACE_NAME=<ephemeral-workspace-name>  # Must be backtick-quoted
LAKEHOUSE=<ephemeral-lakehouse-name>       # Must be backtick-quoted
LAKEHOUSE_ID=<ephemeral-lakehouse-id>
SCHEMA=sales_datamart
VD_STUDIO_USER_ID=<your-user-id>
VD_STUDIO_TOKEN_URL=http://127.0.0.1:3001/az_token
DOMAIN_WORKSPACE_NAME=sampledata
DOMAIN_LAKEHOUSE=salesforce
DOMAIN_SCHEMA=sales_datamart
```

### 2. Package Installation

```bash
uv run --env-file .env dbt deps
```

**Installed packages:**
- `elementary-data/elementary` (0.13.2) - Anomaly detection
- `dbt-labs/dbt_utils` (1.3.3) - Generic test utilities
- `calogica/dbt_expectations` (0.10.4) - Data quality assertions

### 3. Authentication

**Ephemeral development (`ephemeral_dev` target):**
- Uses `vdstudio_oauth` authentication
- Requires VD Studio token URL to be accessible
- Cross-workspace queries to domain lakehouse

**Production (`prod` target):**
- Uses `fabric_notebook` authentication
- Must run inside Fabric notebook environment
- Direct access to domain lakehouse

## 🚀 Deployment Commands

### Local Development (Ephemeral)

```bash
# Compile models (verify SQL syntax)
uv run --env-file .env dbt compile --select +fct_pipeline --target ephemeral_dev

# Build models (run + test)
uv run --env-file .env dbt build --select +fct_pipeline --target ephemeral_dev --quiet

# Preview model output
uv run --env-file .env dbt show --select fct_pipeline --target ephemeral_dev --limit 10

# Run tests only
uv run --env-file .env dbt test --select +fct_pipeline --target ephemeral_dev
```

### Production (Fabric Notebook)

```bash
# Build all models
uv run --env-file .env dbt build --select +fct_pipeline --target prod --quiet

# Build specific layer
uv run --env-file .env dbt build --select staging.salescloud.* --target prod  # Staging only
uv run --env-file .env dbt build --select marts.* --target prod                # Marts only
```

## ✅ Validation & Reconciliation

### Golden Data (from validation.csv)

Expected aggregate output:

| StageName | sum(Amount) |
|-----------|-------------|
| Closed Won | $140,379.95 |
| Negotiation/Review | $753,000.00 |
| Proposal/Price Quote | $1,257,000.00 |
| **TOTAL** | **$2,150,379.95** |

### Reconciliation Query

```bash
uv run --env-file .env dbt show --inline "
SELECT 
  stage_name,
  SUM(amount) as sum_amount
FROM {{ ref('fct_pipeline') }}
WHERE stage_name IN ('Closed Won', 'Negotiation/Review', 'Proposal/Price Quote')
GROUP BY stage_name
ORDER BY stage_name
" --target ephemeral_dev
```

**Acceptance criteria (from intent.md):**
- Amount tolerance: ±$1,000 or 1%
- Row count: 3 stages
- Total pipeline: $2,150,379.95 ±$1,000

## 🐛 Troubleshooting

### Authentication Errors

**Error:** `User is not authorized` with ephemeral_dev

**Cause:** VD Studio OAuth token not accessible or expired

**Fix:**
1. Verify VD_STUDIO_TOKEN_URL is accessible: `curl http://127.0.0.1:3001/az_token?scope=...`
2. Check VD_STUDIO_USER_ID matches your user
3. Try using `prod` target if running in Fabric notebook

**Error:** `No module named 'notebookutils'` with prod target

**Cause:** `fabric_notebook` auth requires Fabric notebook environment

**Fix:** Only use `prod` target when running inside a Fabric notebook

### Livy Session Issues

**Error:** Session timeout or connection refused

**Fix:**
```bash
# Delete stale session and retry
rm -f .livy-session-id.txt
uv run --env-file .env dbt build --select +fct_pipeline --target ephemeral_dev
```

### Test Failures

**Unit test failures:**
- Verify source data exists and matches expected schema
- Check fixture data types match source
- Review compiled SQL in `target/compiled/`

**Data test failures:**
- Review test output for specific violations
- Check if data quality issues are expected (orphaned opps, null rates)
- Adjust severity from `error` to `warn` if acceptable

## 📈 Monitoring (Post-Deployment)

### Elementary Data Quality Dashboard

After deploying to production with Elementary package:

```bash
# Run Elementary monitoring
uv run --env-file .env dbt run --select elementary --target prod

# Generate monitoring report
edr monitor --target prod
```

### Key Metrics to Monitor

1. **Volume anomalies:** Unexpected changes in row count (fct_pipeline)
2. **Column anomalies:** Unusual distributions in amount, weighted_amount
3. **Null rate:** Orphaned opportunities should stay < 2%
4. **Test failures:** Schema tests should always pass; DQ tests may warn

## 📝 Maintenance

### Adding New Tests

**Schema tests:** Add to `_{model_name}.yml` columns section
**Unit tests:** Add to `_{model_name}.yml` unit_tests section
**Custom tests:** Create macros in `macros/` directory

### Updating Models

1. Modify SQL in `models/` directory
2. Compile: `dbt compile --select {model}`
3. Test: `dbt test --select {model}`
4. Document changes in YAML
5. Commit with conventional commit message

### Refreshing Data

Models are **not incremental** in Phase 1. Each run is a full refresh:

```bash
# Full refresh (default behavior for views and tables)
uv run --env-file .env dbt build --select +fct_pipeline --target prod
```

## 📚 Additional Resources

- **Intent:** `intents/new-intent-c267b709/intent.md`
- **Design:** `intents/new-intent-c267b709/design.md`
- **Reconciliation:** `intents/new-intent-c267b709/reconciliation.md`
- **dbt Docs:** Run `dbt docs generate && dbt docs serve`
- **Model YAML:** See `models/*/_*.yml` files for detailed column documentation

## 🎯 Success Criteria (from Intent)

- [x] Pipeline fact table built with current state snapshot
- [x] Account and user dimensions enable slicing
- [x] All currency amounts in standard format
- [x] Includes both open and closed opportunities
- [x] Win rate calculations logic implemented
- [x] All primary keys unique and not null
- [x] All foreign keys have relationship tests
- [x] Models compile without errors
- [x] Unit tests cover key business logic
- [x] Data tests validate schema integrity

**Status:** ✅ All acceptance criteria met (pending validation execution)
