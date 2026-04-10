# Build Execution Log

## Build Attempt: 2026-04-10 12:45 UTC

**Target:** `ephemeral_dev`  
**Command:** `dbt build --select +fct_pipeline`  
**Status:** 🔄 Running...

### Models to Build (6 models)

**Dependency order:**

1. **Staging Layer (views)**
   - `stg_salescloud__opportunity`
   - `stg_salescloud__account`
   - `stg_salescloud__user`

2. **Mart Layer - Dimensions (tables)**
   - `dim_account` (depends on stg_salescloud__account)
   - `dim_user` (depends on stg_salescloud__user)

3. **Mart Layer - Fact (table)**
   - `fct_pipeline` (depends on all staging + dimensions)

### Expected Tests

- **13 unit tests** on `fct_pipeline`
- **49 data quality tests** across all models
- **Total:** 62 tests

### Build Progress

⏳ Waiting for Livy session startup (1-2 minutes)...

---

## Previous Build Attempts

### Attempt 1-3: Failed (Auth Error)
- **Error:** `User is not authorized`
- **Cause:** VD Studio OAuth token not configured
- **Resolution:** Platform team fixed authentication

### Attempt 4: Current
- **Auth:** ✅ Fixed
- **Session:** Fresh (cache cleared)
- **Expected:** Success

---

## Validation Plan (Post-Build)

Once build completes successfully, run reconciliation:

```sql
SELECT 
  stage_name,
  SUM(amount) as sum_amount
FROM {{ ref('fct_pipeline') }}
WHERE stage_name IN ('Closed Won', 'Negotiation/Review', 'Proposal/Price Quote')
GROUP BY stage_name
ORDER BY stage_name
```

**Expected results (from validation.csv):**
- Closed Won: $140,379.95
- Negotiation/Review: $753,000.00
- Proposal/Price Quote: $1,257,000.00
- **Total:** $2,150,379.95

**Tolerance:** ±$1,000 or 1%
