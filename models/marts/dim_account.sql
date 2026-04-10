{{ config(materialized='table') }}

with accounts as (
    select * from {{ ref('stg_salescloud__account') }}
),

final as (
    select
        -- Primary key
        account_id,

        -- Account attributes
        account_name,
        account_type,
        industry,

        -- Location
        billing_city,
        billing_state,
        billing_country,

        -- Relationships
        owner_id,

        -- Audit
        created_date,
        last_modified_date

    from accounts
)

select * from final
