# Sales Pipeline Data Mart - Design

## Source Mapping

| Source Table | Staging Model | Mart Model | Build Status |
|--------------|---------------|------------|--------------|
| `salescloud.opportunity` | `stg_salescloud__opportunity` | `fct_pipeline` | new |
| `salescloud.account` | `stg_salescloud__account` | `dim_account` | new |
| `salescloud.user` | `stg_salescloud__user` | `dim_user` | new |

## Model Architecture

```
Sources (salescloud schema)
    ↓
Staging Layer (views)
    stg_salescloud__opportunity
    stg_salescloud__account
    stg_salescloud__user
    ↓
Mart Layer (tables)
    dim_account ← stg_salescloud__account
    dim_user ← stg_salescloud__user
    fct_pipeline ← stg_salescloud__opportunity + dim_account + dim_user
```

**Dependency Flow:**
1. Build staging models first (views, no dependencies)
2. Build dimension models from staging (tables)
3. Build fact model last (references dimensions for surrogate key lookups and validation)

## Materialization Strategy

| Model | Materialization | Rationale |
|-------|----------------|-----------|
| `stg_salescloud__opportunity` | `view` | Lightweight rename/cast layer, no transformations, follows staging convention |
| `stg_salescloud__account` | `view` | Lightweight rename/cast layer, no transformations, follows staging convention |
| `stg_salescloud__user` | `view` | Lightweight rename/cast layer, no transformations, follows staging convention |
| `dim_account` | `table` | Relatively small dimension (~thousands of rows), queried frequently, worth materializing |
| `dim_user` | `table` | Small dimension (~hundreds of rows), queried frequently, worth materializing |
| `fct_pipeline` | `table` | Core mart table, moderate size (~tens of thousands), many calculations, must be performant |

**Future consideration:** If `fct_pipeline` grows beyond 1M rows and we need daily snapshots, convert to `incremental` with `LastModifiedDate` filter.

## Validation Approach

### Pre-Build Validation
1. **Row count check**: Query source tables to confirm data exists
2. **Schema inspection**: Verify expected columns exist in source tables
3. **Data profiling**: Check for null rates, value distributions in key fields

### Post-Build Validation
1. **Grain verification**: Ensure one row per opportunity in `fct_pipeline`
2. **Referential integrity**: Verify all foreign keys resolve to dimension records
3. **Business logic**: Compare pipeline value calculations to expected values
4. **Reconciliation**: Match aggregate metrics (total pipeline value, count by stage) to source

### Validation Queries
```sql
-- Grain check: should return 0 rows
SELECT opportunity_id, COUNT(*) as cnt
FROM fct_pipeline
GROUP BY opportunity_id
HAVING cnt > 1;

-- Pipeline value reconciliation (within $1000 or 1%)
SELECT 
  SUM(amount) as fact_total,
  (SELECT SUM(amount) FROM salescloud.opportunity WHERE isdeleted = FALSE) as source_total,
  ABS(fact_total - source_total) as difference;
```

## Grain Specification

| Model | Grain | Validation |
|-------|-------|------------|
| `stg_salescloud__opportunity` | One row per opportunity (current state) | `unique` test on `opportunity_id` |
| `stg_salescloud__account` | One row per account (current state) | `unique` test on `account_id` |
| `stg_salescloud__user` | One row per user (current state) | `unique` test on `user_id` |
| `dim_account` | One row per account (SCD Type 1) | `unique` test on `account_id` |
| `dim_user` | One row per user (SCD Type 1) | `unique` test on `user_id` |
| `fct_pipeline` | One row per opportunity (current state snapshot) | `unique` test on `opportunity_id` |

**Note:** This is a **current state** design, not historical snapshots. If historical point-in-time analysis is needed later, we'll add `fct_pipeline_daily_snapshot` using dbt snapshots or incremental models.

## Join Plan

### fct_pipeline Joins

```sql
-- Primary grain: opportunity
FROM stg_salescloud__opportunity AS opp

-- Account dimension (left join to preserve orphaned opportunities for data quality visibility)
LEFT JOIN dim_account AS acct
  ON opp.account_id = acct.account_id

-- User dimension (left join to preserve unassigned opportunities)
LEFT JOIN dim_user AS owner
  ON opp.owner_id = owner.user_id
```

**Fan-out Risk:** None. All joins are many-to-one (many opportunities → one account, many opportunities → one owner).

**Null Handling (aligns with intent.md data quality rules):**
- Opportunities with `account_id IS NULL` preserved for investigation; flagged via data quality tests; excluded from account-level rollups in BI layer
- Opportunities with `owner_id IS NULL` preserved for unassigned opportunity analysis
- Opportunities with `amount = 0` or `amount IS NULL` included in fact table but excluded from weighted pipeline calculations via conditional logic

## Testing Plan

### Schema Tests (dbt-core generic tests)
Applied in `_{model_name}.yml` files:

**Staging Models:**
- `unique` + `not_null` on all primary keys (`opportunity_id`, `account_id`, `user_id`)
- `accepted_values` on `is_deleted` (true/false), `is_closed` (true/false), `is_won` (true/false)
- **Note:** No `relationships` tests from staging to staging - these are deferred to the fact table where business logic applies (e.g., LEFT JOIN allows null foreign keys for data quality visibility)

**Dimension Models:**
- `unique` + `not_null` on primary keys
- `accepted_values` on categorical fields (if any, e.g., account_type, user_role)

**Fact Model:**
- `unique` + `not_null` on `opportunity_id`
- `relationships` to dimensions: `account_id` → `dim_account`, `owner_id` → `dim_user`
- `not_null` on critical fields: `created_date`, `stage_name`
- `accepted_values` on derived fields: `forecast_category` (Pipeline, Commit, Best Case, Upside, Closed Won, Closed Lost)

### Unit Tests (dbt 1.8+ unit tests)
Defined in `_{model_name}.yml` files. See **Unit Test Scenarios** section below.

### Data Quality Tests (dbt-expectations, Elementary)
Applied after unit tests pass:

- **Freshness**: Ensure source data is updated within expected SLA
- **Volume anomalies**: Detect unexpected row count changes in `fct_pipeline` (Elementary)
- **Null rate anomalies**: Detect spikes in null rates for critical fields (Elementary)
- **Value distribution**: Ensure `stage_name` values match expected set (dbt-expectations `expect_column_values_to_be_in_set`)
- **Business logic validation**: `amount >= 0` for all non-deleted opportunities

## Data Quality Rules

### Needing Attention

| Model | Rule | Package | Rationale |
|-------|------|---------|-----------|
| `fct_pipeline` | `amount` should be >= 0 for non-deleted opportunities | dbt-expectations | Negative amounts may indicate data quality issues; needs user review to confirm if valid (e.g., credits, refunds) |
| `fct_pipeline` | `close_date` should be populated for all closed opportunities (where `is_closed = true`) | custom | Closed opportunities without close dates indicate data integrity issues |
| `fct_pipeline` | Opportunities with null `account_id` should be < 2% of total | elementary (null_rate) | Orphaned opportunities need investigation; acceptable null rate threshold needs user validation (currently 2% proposed) |
| `dim_account` | Account name should not contain test/placeholder values | custom (regex) | Pattern needs user validation (e.g., "test", "sample", "demo") |

### Default (Schema)

`unique` and `not_null` on primary keys; `relationships` on foreign keys; `accepted_values` on status/type columns (is_deleted, is_closed, is_won, forecast_category).

## Unit Test Scenarios

| Model | Scenario | What It Tests |
|-------|----------|---------------|
| `fct_pipeline` | Closed won opportunity with probability < 100 | Ensures `forecast_category` = 'Closed Won' regardless of probability field value |
| `fct_pipeline` | Open opportunity with probability = 75 | Verifies forecast category logic (Best Case threshold) |
| `fct_pipeline` | Open opportunity with probability = 50 | Verifies forecast category logic (Commit threshold) |
| `fct_pipeline` | Open opportunity with amount = 0 | Confirms zero-value opportunities are included in fact table (excluded from weighted pipeline via conditional logic) |
| `fct_pipeline` | Open opportunity with null close_date | Tests handling of missing close dates for open opportunities (should preserve null without error) |
| `fct_pipeline` | Closed opportunity with null close_date | Tests data quality rule: closed opportunities should have populated close_date (should fail data test) |
| `fct_pipeline` | Weighted pipeline calculation | Verifies `weighted_amount = amount * probability / 100` |
| `fct_pipeline` | Sales cycle duration for closed opportunity | Tests `DATEDIFF(day, created_date, close_date)` calculation |
| `dim_account` | Account with special characters in name | Ensures proper string handling (no truncation/corruption) |
