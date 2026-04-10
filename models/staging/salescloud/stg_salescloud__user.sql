{{ config(materialized='view') }}

with source as (
    select * from {{ source('salescloud', 'user') }}
),

renamed as (
    select
        -- Primary key
        id as user_id,

        -- User attributes
        name as user_name,
        email,
        username,

        -- Role and profile
        userroleid as user_role_id,
        profileid as profile_id,
        title as job_title,

        -- Flags
        isactive as is_active,

        -- Audit fields
        createddate as created_date,
        lastmodifieddate as last_modified_date

    from source
)

select * from renamed
