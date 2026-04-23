{{
    config(
        materialized='table'
    )
}}

-- Account Scorecard: Monthly aggregation of account sales performance
-- Grain: One row per account per month
-- For current month: MTD (month-to-date) values
-- For historical months: Full month values

with source_opportunities as (
    select * from {{ ref('stg_salescloud__opportunity') }}
    where is_deleted = false
),

source_accounts as (
    select * from {{ ref('stg_salescloud__account') }}
    where is_deleted = false
),

-- Get all unique account-month combinations where opportunities existed
account_months as (
    select distinct
        account_id,
        DATE_TRUNC('month', close_date) as month_start_date
    from source_opportunities
    where close_date is not null

    union

    select distinct
        account_id,
        DATE_TRUNC('month', created_date) as month_start_date
    from source_opportunities
    where created_date is not null
),

-- Aggregate metrics by account and month
account_monthly_metrics as (
    select
        am.account_id,
        am.month_start_date,

        -- Revenue metrics (won only)
        sum(
            case
                when o.is_won = true then o.amount
                else 0
            end
        ) as total_revenue_amount,

        -- MTD revenue for current month
        sum(
            case
                when o.is_won = true
                  and DATE_TRUNC('month', o.close_date) = DATE_TRUNC('month', CURRENT_DATE)
                then o.amount
                else 0
            end
        ) as mtd_revenue_amount,

        -- Pipeline (open opportunities, not closed/won)
        sum(
            case
                when o.is_closed = false then o.amount
                else 0
            end
        ) as pipeline_amount,

        -- MTD pipeline
        sum(
            case
                when o.is_closed = false
                  and DATE_TRUNC('month', o.close_date) = DATE_TRUNC('month', CURRENT_DATE)
                then o.amount
                else 0
            end
        ) as mtd_pipeline_amount,

        -- Opportunity counts
        count(o.opportunity_id) as opportunity_count,

        sum(
            case when o.is_won = true then 1 else 0 end
        ) as won_opportunity_count,

        sum(
            case when o.is_closed = false then 1 else 0 end
        ) as open_opportunity_count,

        -- Win rate (handle division by zero)
        case
            when count(o.opportunity_id) > 0
            then cast(sum(case when o.is_won = true then 1 else 0 end) as double) / count(o.opportunity_id) * 100
            else null
        end as win_rate_pct,

        -- Average deal size (won deals only)
        avg(
            case when o.is_won = true then o.amount else null end
        ) as avg_won_deal_size

    from account_months am
    left join source_opportunities o
        on am.account_id = o.account_id
        and (
            (o.close_date is not null and DATE_TRUNC('month', o.close_date) = am.month_start_date)
            or (o.created_date is not null and DATE_TRUNC('month', o.created_date) = am.month_start_date)
        )
    group by am.account_id, am.month_start_date
),

-- Add account attributes and final flags
final as (
    select
        am.account_id,
        a.account_name,
        a.account_type,
        a.industry,
        a.billing_city,
        a.billing_state,
        a.billing_country,
        am.month_start_date,
        am.total_revenue_amount,
        am.mtd_revenue_amount,
        am.pipeline_amount,
        am.mtd_pipeline_amount,
        am.opportunity_count,
        am.won_opportunity_count,
        am.open_opportunity_count,
        am.win_rate_pct,
        am.avg_won_deal_size,

        -- Flag for current month (MTD data)
        case
            when am.month_start_date = DATE_TRUNC('month', CURRENT_DATE)
            then true
            else false
        end as is_current_month

    from account_monthly_metrics am
    left join source_accounts a
        on am.account_id = a.account_id
)

select * from final
