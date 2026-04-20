{{ config(materialized='table') }}

with monthly_metrics as (
    select * from {{ ref('int_sales_rep_monthly_metrics') }}
),

sales_reps as (
    select * from {{ ref('dim_user') }}
),

final as (
    select
        -- Surrogate key
        {{ dbt_utils.generate_surrogate_key(['m.owner_id', 'm.performance_month']) }} as sales_rep_performance_id,

        -- Foreign keys
        m.owner_id,
        m.performance_month,

        -- Sales rep attributes (from dim_user)
        r.user_name as rep_name,
        r.email as rep_email,
        r.job_title as rep_job_title,
        r.is_active as rep_is_active,

        -- Activity metrics
        m.total_opportunities,
        m.total_closed,
        m.closed_won_count,
        m.closed_lost_count,
        m.open_count,

        -- Pipeline generation metrics
        m.new_opportunities_count,
        m.pipeline_generated,

        -- Revenue metrics
        m.closed_won_amount,
        m.avg_deal_size,

        -- Performance metrics
        m.avg_sales_cycle_days,
        m.win_rate_percent

    from monthly_metrics as m
    left join sales_reps as r
        on m.owner_id = r.user_id
)

select * from final
