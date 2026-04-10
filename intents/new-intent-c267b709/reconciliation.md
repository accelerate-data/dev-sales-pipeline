# Sales Pipeline Validation Reconciliation

## Expected Output (Golden Data)

From `validation.csv`:

| StageName | sum(Amount) |
|-----------|-------------|
| Closed Won | $140,379.95 |
| Negotiation/Review | $753,000.00 |
| Proposal/Price Quote | $1,257,000.00 |

**Total Pipeline Value:** $2,150,379.95

## Reconciliation Query

```sql
SELECT 
  stage_name,
  SUM(amount) as sum_amount
FROM {{ ref('fct_pipeline') }}
WHERE stage_name IN ('Closed Won', 'Negotiation/Review', 'Proposal/Price Quote')
GROUP BY stage_name
ORDER BY stage_name
```

## Validation Criteria

1. **Row Count Match:** Expected 3 rows (3 stages)
2. **Stage Name Match:** All 3 stage names present
3. **Amount Tolerance:** ±$1,000 or 1% acceptable (per intent.md)
4. **Total Pipeline:** Should sum to $2,150,379.95 ±$1,000

## Validation Status

**Status:** Pending model execution

**Blocker:** Authentication to ephemeral Fabric workspace requires resolution before validation can be performed.

**Next Steps:**
1. Resolve OAuth authentication for ephemeral_dev target
2. Execute: `uv run --env-file .env dbt build --select fct_pipeline --target ephemeral_dev`
3. Run reconciliation query via dbt show
4. Compare results to golden data
5. Document any discrepancies for investigation

## Alternative: SQLite Validation

If Fabric auth cannot be resolved immediately, models can be tested against local SQLite with sample data to verify transformation logic before production deployment.
