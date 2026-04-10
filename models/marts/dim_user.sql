{{ config(materialized='table') }}

with users as (
    select * from {{ ref('stg_salescloud__user') }}
),

final as (
    select
        -- Primary key
        user_id,

        -- User attributes
        user_name,
        email,
        username,
        job_title,

        -- Role and profile
        user_role_id,
        profile_id,

        -- Status
        is_active,

        -- Audit
        created_date,
        last_modified_date

    from users
)

select * from final
