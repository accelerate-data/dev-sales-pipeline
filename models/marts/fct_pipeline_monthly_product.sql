{{ config(materialized='table') }}

with line_items as (
    select * from {{ ref('stg_salescloud__opportunitylineitem') }}
),

opportunities as (
    select * from {{ ref('stg_salescloud__opportunity') }}
),

-- Join line items to opportunities to get close dates
line_items_with_dates as (
    select
        line_items.*,
        opportunities.close_date,
        opportunities.is_won,
        opportunities.is_closed
    from line_items
    inner join opportunities
        on line_items.opportunity_id = opportunities.opportunity_id
    where opportunities.close_date is not null  -- Exclude opportunities without close dates
),

-- Aggregate to monthly + product level
monthly_product_aggregates as (
    select
        -- Time dimension: First day of the close month
        date_trunc('month', close_date) as close_month,

        -- Product dimension
        product_id,
        product_code,
        product_name,

        -- Aggregate metrics
        sum(total_price) as total_revenue,
        count(distinct opportunity_id) as opportunity_count,
        sum(quantity) as total_quantity,
        avg(unit_price) as avg_unit_price,
        avg(discount) as avg_discount,

        -- Calculated metric: Average deal size
        sum(total_price) / count(distinct opportunity_id) as avg_deal_size,

        -- Win rate metrics (for analysis)
        count(distinct case when is_won = true then opportunity_id end) as won_opportunity_count,
        sum(case when is_won = true then total_price else 0 end) as won_revenue,

        -- Data quality metrics
        count(*) as line_item_count,
        min(close_date) as earliest_close_date,
        max(close_date) as latest_close_date

    from line_items_with_dates
    group by
        date_trunc('month', close_date),
        product_id,
        product_code,
        product_name
),

final as (
    select
        -- Primary key components
        close_month,
        product_id,

        -- Product attributes
        product_code,
        product_name,

        -- Revenue metrics
        total_revenue,
        won_revenue,
        total_revenue - won_revenue as lost_revenue,

        -- Volume metrics
        opportunity_count,
        won_opportunity_count,
        opportunity_count - won_opportunity_count as lost_opportunity_count,
        total_quantity,
        line_item_count,

        -- Average metrics
        avg_deal_size,
        avg_unit_price,
        avg_discount,

        -- Calculated: Win rate percentage
        case
            when opportunity_count > 0
            then (cast(won_opportunity_count as double) / cast(opportunity_count as double)) * 100.0
            else null
        end as win_rate_pct,

        -- Date range for the month
        earliest_close_date,
        latest_close_date

    from monthly_product_aggregates
)

select * from final
