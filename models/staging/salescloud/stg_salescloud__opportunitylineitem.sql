{{ config(materialized='view') }}

with source as (
    select * from {{ source('salescloud', 'opportunitylineitem') }}
),

renamed as (
    select
        -- Primary key
        Id as line_item_id,

        -- Foreign keys
        OpportunityId as opportunity_id,
        PricebookEntryId as pricebook_entry_id,
        Product2Id as product_id,

        -- Product attributes
        Name as product_name,
        ProductCode as product_code,

        -- Quantities and pricing
        Quantity as quantity,
        UnitPrice as unit_price,
        TotalPrice as total_price,
        Discount as discount,

        -- Additional attributes
        Description as description,
        ServiceDate as service_date,
        SortOrder as sort_order,

        -- Audit fields
        CreatedDate as created_date

    from source
)

select * from renamed
