{% test null_rate_below_threshold(model, column_name, threshold=0.02) %}

with null_analysis as (
    select
        count(*) as total_rows,
        sum(case when {{ column_name }} is null then 1 else 0 end) as null_rows,
        cast(sum(case when {{ column_name }} is null then 1 else 0 end) as float) /
        nullif(cast(count(*) as float), 0) as null_rate
    from {{ model }}
)

select *
from null_analysis
where null_rate > {{ threshold }}

{% endtest %}
