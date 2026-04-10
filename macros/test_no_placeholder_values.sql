{% test no_placeholder_values(model, column_name, patterns=['test', 'sample', 'demo', 'placeholder', 'example', 'temp', 'TBD']) %}

select
    {{ column_name }},
    count(*) as records_with_placeholder
from {{ model }}
where lower({{ column_name }}) like '%test%'
   or lower({{ column_name }}) like '%sample%'
   or lower({{ column_name }}) like '%demo%'
   or lower({{ column_name }}) like '%placeholder%'
   or lower({{ column_name }}) like '%example%'
   or lower({{ column_name }}) like '%temp%'
   or lower({{ column_name }}) like '%tbd%'
group by {{ column_name }}

{% endtest %}
