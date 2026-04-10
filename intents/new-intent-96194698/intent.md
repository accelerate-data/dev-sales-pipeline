# Intent: Monthly Product Aggregates

## Business Context

The sales team needs to analyze product performance over time to identify trending products, forecast demand, and optimize product mix strategies. Currently, the sales data is available at the opportunity and line item level, but there's no easy way to view aggregated product performance by month.

This aggregate model will enable:
- Product managers to track monthly product revenue trends
- Sales leadership to identify top-performing products each month
- Finance to forecast product-level revenue
- Operations to understand product demand patterns

The output will be consumed by business intelligence dashboards and monthly reporting.

## Goals

1. Create a monthly product-level aggregate fact table that shows all key product performance metrics
2. Enable time-series analysis of product performance across months
3. Provide a single source of truth for monthly product metrics
4. Support efficient querying for product trend analysis and forecasting

## Business Rules

### Metric Definitions

**Total Revenue**: Sum of `TotalPrice` from all opportunity line items for a given product and month, where the opportunity close date falls within that month

**Opportunity Count**: Count of distinct opportunities that included the product and closed in that month

**Total Quantity**: Sum of `Quantity` from all line items for the product in that month

**Average Deal Size**: Total revenue divided by opportunity count for each product-month combination

**Average Unit Price**: Average of `UnitPrice` across all line items for the product in that month

**Average Discount**: Average of `Discount` percentage across all line items (if applicable)

### Temporal Aggregation

- Use the opportunity `close_date` to determine which month a line item belongs to
- Extract year-month from close_date for grouping
- Only include opportunities with non-null close dates
- Include both won and lost opportunities (can be filtered in BI layer)

### Product Identification

- Group by `Product2Id` (product identifier)
- Include `ProductCode` and `Name` for convenience
- Handle cases where product name/code may change over time (use most recent)

## Acceptance Criteria

- [ ] New staging model `stg_salescloud__opportunitylineitem` created with clean column names
- [ ] New mart model `fct_pipeline_monthly_product` created with one row per month + product
- [ ] All requested metrics are calculated correctly:
  - Total revenue (sum of TotalPrice)
  - Opportunity count (distinct OpportunityIds)
  - Total quantity (sum of Quantity)
  - Average deal size (revenue / opportunity count)
  - Average unit price
- [ ] Model includes both month dimension (YYYY-MM) and product attributes
- [ ] Compilation succeeds with no errors
- [ ] Data validation shows reasonable results (no negative values, counts match source)
- [ ] Schema tests added for primary key uniqueness
- [ ] Documentation added to model YAML files

## Open Questions

1. Should we filter to only "Closed Won" opportunities, or include all closed opportunities?
   - **Decision needed**: Include all or filter to won only?
   
2. How should we handle line items where the opportunity has no close_date?
   - **Proposed approach**: Exclude these from monthly aggregates (can't assign to a month)

3. Should we include current month (partial month) or only complete months?
   - **Proposed approach**: Include current month, users can filter in BI layer

4. Do we need historical tracking if product names/codes change over time?
   - **Proposed approach**: Use current product attributes (no SCD needed initially)

## Sources

### Primary Sources

1. **salescloud.opportunitylineitem**
   - Contains product-level sales data (line items)
   - Provides: Product2Id, ProductCode, Name, Quantity, UnitPrice, TotalPrice, Discount
   - Links to opportunities via OpportunityId

2. **salescloud.opportunity** (via existing stg_salescloud__opportunity)
   - Provides close_date for temporal aggregation
   - Provides opportunity-level context (is_won, is_closed)

### Existing Models to Leverage

- `stg_salescloud__opportunity` - Already available for close dates and opportunity status
