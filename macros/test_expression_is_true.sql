{% test expression_is_true(model, expression, column_name=None) %}

{%- set where_clause = kwargs.get('where') -%}

select *
from {{ model }}
where not ({{ expression }})
{% if where_clause %}
  and {{ where_clause }}
{% endif %}

{% endtest %}
