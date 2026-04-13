-- Local overrides for the elementary_fabricspark shim.
-- These macros are dispatched ahead of the shim via the `sales_pipeline`
-- entry in the `elementary` dispatch search_order in dbt_project.yml.

{#
  Fix for `Artifact not found: <workspace>.<workspace>` errors on Fabric
  lakehouses with `lakehouse_schemas_enabled: true`.

  The upstream shim nulls out `schema` when building a temp relation, which
  produces a 3-part path `workspace.lakehouse.table` instead of the required
  4-part `workspace.lakehouse.schema.table`. Fabric then fails to resolve the
  namespace. We keep the base relation's schema so the temp lands in the same
  schema as the target (e.g. `elementary`).
#}
{% macro fabricspark__edr_make_temp_relation(base_relation, suffix) %}
    {% set tmp_identifier = elementary.table_name_with_suffix(base_relation.identifier, suffix) %}
    {% set tmp_relation = base_relation.incorporate(path = {
        "identifier": tmp_identifier
    }) -%}

    {% do return(tmp_relation) %}
{% endmacro %}
