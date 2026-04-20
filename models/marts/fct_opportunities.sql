{{ config(materialized='table') }}

with opportunities as (
    select * from {{ ref('stg_salescloud__opportunity') }}
),

accounts as (
    select * from {{ ref('dim_account') }}
),

users as (
    select * from {{ ref('dim_user') }}
),

opportunity_revenue as (
    select
        -- Primary key (grain: one row per opportunity)
        opp.opportunity_id,

        -- Foreign keys
        opp.account_id,
        opp.owner_id,

        -- Opportunity attributes
        opp.opportunity_name,
        opp.stage_name,
        opp.opportunity_type,
        opp.lead_source,

        -- Revenue metrics
        opp.amount,
        opp.expected_revenue,

        -- Dates
        opp.created_date,
        opp.close_date,

        -- Status flags
        opp.is_closed,
        opp.is_won,

        -- Calculated: Revenue recognition flag
        case
            when opp.is_closed = true and opp.is_won = true
            then true
            else false
        end as is_closed_won,

        -- Calculated: Recognized revenue (only for closed/won)
        case
            when opp.is_closed = true and opp.is_won = true
            then coalesce(opp.amount, 0)
            else 0
        end as revenue_amount,

        -- Calculated: Sales cycle duration (for closed opportunities)
        case
            when opp.is_closed = true and opp.close_date is not null and opp.created_date is not null
            then datediff(day, opp.created_date, opp.close_date)
            else null
        end as sales_cycle_days,

        -- Calculated: Win/Loss categorization
        case
            when opp.is_closed = true and opp.is_won = true then 'Won'
            when opp.is_closed = true and opp.is_won = false then 'Lost'
            else 'Open'
        end as opportunity_status,

        -- Data quality flags
        case when opp.amount is null or opp.amount <= 0 then true else false end as is_zero_or_null_amount,
        case when opp.close_date > current_date() then true else false end as is_future_close_date,

        -- Audit
        opp.last_modified_date

    from opportunities as opp
),

final as (
    select
        opp.*,

        -- Denormalized account attributes (for analysis convenience)
        acct.account_name,
        acct.account_type,
        acct.industry,
        acct.billing_state,
        acct.billing_country,

        -- Denormalized user attributes (for analysis convenience)
        usr.user_name as owner_name,
        usr.is_active as owner_is_active

    from opportunity_revenue as opp

    -- LEFT JOIN to preserve opportunities even if account/owner is missing
    left join accounts as acct
        on opp.account_id = acct.account_id

    left join users as usr
        on opp.owner_id = usr.user_id
)

select * from final
