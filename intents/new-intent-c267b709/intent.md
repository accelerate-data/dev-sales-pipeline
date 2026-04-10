# Sales Pipeline Data Mart - Intent

## Business Context

Sales leadership needs a unified view of the sales pipeline to track opportunity progress, forecast revenue, and analyze sales performance. Currently, this data exists in raw Salesforce tables that are difficult to query and lack the aggregations needed for executive reporting.

The sales pipeline mart will serve as the single source of truth for:
- **Sales executives** tracking overall pipeline health, win rates, and forecast accuracy
- **Sales managers** monitoring team performance and deal progression
- **Sales ops** analyzing conversion metrics and sales cycle duration
- **Revenue operations** building forecasts and capacity models

## Goals

1. **Enable pipeline health monitoring** - Provide real-time visibility into open pipeline value by stage, owner, and product
2. **Support revenue forecasting** - Calculate weighted pipeline values using probability-based forecasting
3. **Track conversion metrics** - Measure opportunity win/loss rates and opportunity-to-close conversion rates
4. **Analyze sales cycles** - Measure time-in-stage and total sales cycle duration
5. **Support performance analysis** - Enable sales rep and team performance comparison

**Scope Boundary - Phase 1:** This intent delivers current-state pipeline analysis only. Historical snapshots, product-level line item analysis, and lead-to-opportunity conversion tracking are deferred to future phases.

## Business Rules

### Pipeline Value Calculation
- **Open Pipeline**: Opportunities where `IsClosed = FALSE` and `IsDeleted = FALSE`
- **Weighted Pipeline**: `Amount * Probability / 100` for forecasting
- **Closed Won Pipeline**: Opportunities where `IsClosed = TRUE AND IsWon = TRUE`
- **Closed Lost Pipeline**: Opportunities where `IsClosed = TRUE AND IsWon = FALSE`

### Opportunity Categorization
```sql
CASE 
  WHEN IsClosed = TRUE AND IsWon = TRUE THEN 'Closed Won'
  WHEN IsClosed = TRUE AND IsWon = FALSE THEN 'Closed Lost'
  WHEN Probability >= 75 THEN 'Best Case'
  WHEN Probability >= 50 THEN 'Commit'
  WHEN Probability >= 25 THEN 'Pipeline'
  ELSE 'Upside'
END AS forecast_category
```

**Assumed Fields:** This logic assumes the following Salesforce standard fields exist in the source:
- `Probability` (integer 0-100 representing likelihood to close)
- `IsClosed` (boolean)
- `IsWon` (boolean)
- `CreatedDate` (timestamp)
- `CloseDate` (date)

### Sales Cycle Metrics
- **Sales Cycle Duration**: `DATEDIFF(day, CreatedDate, CloseDate)` for closed opportunities
- **Days in Current Stage**: `DATEDIFF(day, LastStageChangeDate, CURRENT_DATE)` for open opportunities
- **Age of Opportunity**: `DATEDIFF(day, CreatedDate, CURRENT_DATE)`

### Data Quality Rules
- Exclude soft-deleted records: `IsDeleted = FALSE`
- **Zero-value opportunities**: Include all opportunities in fact table, but exclude `amount = 0` or `amount IS NULL` opportunities from weighted pipeline and forecasting calculations
- **Orphaned opportunities**: Include opportunities with `account_id IS NULL` in fact table for data quality visibility, but flag them for investigation and exclude from account-level rollups
- **CloseDate validation**: CloseDate must be populated for all **closed** opportunities (`IsClosed = TRUE`). Open opportunities may have null or future close dates.

## Acceptance Criteria

- [ ] Pipeline fact table shows one row per opportunity with current state
- [ ] Account and user dimensions enable slicing by customer and sales rep
- [ ] All currency amounts are in standard USD format
- [ ] Fact table includes both open and closed opportunities for trend analysis
- [ ] Win rate calculations match Salesforce standard reports (within 1%)
- [ ] Pipeline value by stage matches Salesforce pipeline report (within $1,000 or 1%)
- [ ] All primary keys are unique and not null
- [ ] All foreign keys have valid relationships to dimensions
- [ ] Models compile and build successfully without errors
- [ ] Unit tests cover key business logic (forecast category, pipeline value)
- [ ] Data tests validate schema integrity and data quality rules

## Open Questions

1. **Historical Analysis**: Do you need point-in-time snapshots of pipeline (e.g., pipeline value as of end of each month), or just current state?
2. **Product Dimension**: Should we include opportunity line items and create a product dimension, or focus on opportunity-level analysis?
3. **Campaign Attribution**: Should we track campaign influence on opportunities?
4. **Multi-Currency**: Are all opportunities in USD, or do we need currency conversion logic?
5. **Forecast Overrides**: Do sales reps manually override forecast categories in Salesforce? Should we use `ForecastCategory` field if it exists?

## Sources

### Primary Source: Salesforce Sales Cloud
Located in `sampledata.salesforce.salescloud` schema:

- **opportunity** - Core opportunity records (pipeline transactions)
- **account** - Customer and prospect accounts
- **user** - Sales reps and opportunity owners
- **opportunityhistory** - Historical field value changes (for snapshots if needed)
- **opportunitylineitem** - Product line items (if product-level analysis is required)

All sources are ingested and available in the domain lakehouse.
