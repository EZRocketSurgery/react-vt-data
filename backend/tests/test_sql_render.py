"""
Tests for sql_render.py:
  filter_clauses / compile_where / compile_filters (the general-purpose filter
  compiler, emitting $N placeholders and a params list), render_sql /
  sql_filter_block (Jinja rendering), and sqlfluff checks that every SQL template
  lints clean and renders to parseable DuckDB SQL with representative filters.
"""

from pathlib import Path

import pytest
from sqlfluff.core import FluffConfig, Linter

from api.models import FilterSource, RangeFilter
from query.sql_render import (
    compile_filters,
    compile_where,
    filter_clauses,
    render_sql,
    sql_filter_block,
)

BACKEND = Path(__file__).resolve().parent.parent
QUERY_SQL = BACKEND / "query" / "sql"
CLEANING_SQL = BACKEND / "data_cleaning" / "sql"

# ---------------------------------------------------------------------------
# Representative render arguments per template
# ---------------------------------------------------------------------------

WHERE_SOURCE = FilterSource(
    filter_table="acs5_demographics_tidy",
    filters={
        "NAME": ["Vergennes", "Addison town"],
        "year": RangeFilter(min=2015, max=2020),
    },
)
CTE_SOURCE = FilterSource(
    filter_table="VersoZoning_info",
    filters={"County": ["Addison"]},
    join_key="OBJECT_ID",
    join_type="inner",
)
PARCELS_SOURCE = FilterSource(
    filter_table="VCGIParcels_info",
    filters={"county": ["Addison"]},
    join_key="object_id",
)
CDC_SOURCE = FilterSource(
    filter_table="cdc_places_county",
    filters={"measure": ["Depression among adults"]},
)

# template path (relative to backend/) -> FilterSource list for sql_filter_block
QUERY_TEMPLATE_SOURCES = {
    "query/sql/acs5/acs5_county_compare.sql": [WHERE_SOURCE],
    "query/sql/acs5/acs5_dp_county_comparison.sql": [WHERE_SOURCE],
    "query/sql/acs5/acs5_tidy.sql": [WHERE_SOURCE],
    "query/sql/acs5/acs5_timeseries.sql": [WHERE_SOURCE],
    "query/sql/acs5/acs5_town_compare.sql": [WHERE_SOURCE],
    "query/sql/acs5/acs5_tract_compare.sql": [WHERE_SOURCE],
    "query/sql/ambulance/ambulance_geo_query.sql": [
        FilterSource(
            filter_table="VCGI_ambulanceService_info",
            filters={"cert_level": ["Advanced EMT"]},
            join_key="object_id",
        )
    ],
    "query/sql/cdc/county_places.sql": [
        FilterSource(
            filter_table="cdc_places_county",
            filters={"Measure": ["Depression among adults"]},
        )
    ],
    "query/sql/cdc/places_by_county.sql": [CDC_SOURCE],
    "query/sql/cdc/places_tidy.sql": [CDC_SOURCE],
    "query/sql/cdc/tract_places.sql": [
        FilterSource(
            filter_table="cdc_tract_places",
            filters={"Measure": ["Depression among adults"]},
        )
    ],
    "query/sql/flood/flood_geo_query.sql": [
        FilterSource(
            filter_table="FEMA_floodHazard_geom",
            filters={"flood_zone_type": ["AE"]},
        )
    ],
    "query/sql/parcels/agg_category_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/agg_flood_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/agg_owner_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/agg_value_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/category_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/flood_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/geo_query.sql": [PARCELS_SOURCE],
    "query/sql/parcels/owner_table.sql": [PARCELS_SOURCE],
    "query/sql/parcels/value_table.sql": [PARCELS_SOURCE],
    "query/sql/zoning/agg_footprints.sql": [CTE_SOURCE],
    "query/sql/zoning/agg_info_table.sql": [CTE_SOURCE],
    "query/sql/zoning/agg_lot_size.sql": [CTE_SOURCE],
    "query/sql/zoning/info_table.sql": [CTE_SOURCE],
    "query/sql/zoning/geo_query.sql": [CTE_SOURCE],
    "query/sql/zoning/unzoned.sql": [],
    "query/sql/zoning/agg_rules_table.sql": [CTE_SOURCE],
    "query/sql/zoning/footprints.sql": [CTE_SOURCE],
    "query/sql/zoning/geo_rule_table.sql": [CTE_SOURCE],
    "query/sql/zoning/lot_size_table.sql": [CTE_SOURCE],
    "query/sql/zoning/rules_table.sql": [CTE_SOURCE],
    "query/sql/zoning/rules.sql": [CTE_SOURCE],
    "query/sql/wastewater/service_area_geo_query.sql": [
        FilterSource(
            filter_table="service_areas_service_area_info",
            filters={"County": ["Addison"]},
            join_key="ID",
        )
    ],
    "query/sql/wastewater/soil_suitability_geo_query.sql": [
        FilterSource(
            filter_table="soil_suitability_info_soil_suit",
            filters={"Suitability": ["Well Suited"]},
            join_key="ID",
        )
    ],
    "query/sql/wastewater/waste_treatment_geo_query.sql": [
        FilterSource(
            filter_table="treatment_facilities_treatment_facility_info",
            filters={"County": ["Addison"]},
            join_key="ID",
        )
    ],
    # takes no filter fragments; renders as-is
    "query/sql/wastewater/waste_treatment_permit_table.sql": [],
}

# data-cleaning templates take plain string context instead of FilterSources
CLEANING_TEMPLATE_CONTEXT = {
    "data_cleaning/sql/zoning_colors.sql": {},
    "data_cleaning/sql/zoning_empty_geom.sql": {"min_acres": 10},
    "data_cleaning/sql/zoning_info.sql": {"info_string": "OBJECT_ID, County"},
    "data_cleaning/sql/zoning_rules.sql": {
        "rule_string": 'CAST("Residential_Min_Lot" AS VARCHAR) AS residential_min_lot'
    },
}


# ---------------------------------------------------------------------------
# Filter compiler
# ---------------------------------------------------------------------------


class TestFilterClauses:
    def test_in_list(self):
        params: list = []
        clauses = filter_clauses({"County": ["Addison", "Rutland"]}, params)
        assert clauses == ['"County" IN ($1, $2)']
        assert params == ["Addison", "Rutland"]

    def test_scalar_becomes_in_list(self):
        params: list = []
        assert filter_clauses({"County": "Addison"}, params) == ['"County" IN ($1)']
        assert params == ["Addison"]

    def test_range(self):
        params: list = []
        clauses = filter_clauses({"year": RangeFilter(min=2015, max=2020)}, params)
        assert clauses == [
            'TRY_CAST("year" AS DOUBLE) >= $1',
            'TRY_CAST("year" AS DOUBLE) <= $2',
        ]
        assert params == [2015.0, 2020.0]

    def test_none_values_skipped(self):
        params: list = []
        assert filter_clauses({"County": None}, params) == []
        assert filter_clauses(None, params) == []
        assert params == []

    def test_numbering_continues_across_calls(self):
        params: list = []
        filter_clauses({"a": ["x"]}, params)
        clauses = filter_clauses({"b": ["y", "z"]}, params)
        assert clauses == ['"b" IN ($2, $3)']
        assert params == ["x", "y", "z"]

    def test_compile_where(self):
        params: list = []
        assert compile_where(None, params) == ""
        where = compile_where({"a": ["x"], "b": ["y"]}, params)
        assert where == 'WHERE "a" IN ($1) AND "b" IN ($2)'
        assert params == ["x", "y"]


class TestCompileFilters:
    def test_empty_sources(self):
        assert compile_filters([], []) == ("", "")

    def test_inner_join(self):
        params: list = []
        cte, join = compile_filters([CTE_SOURCE], params)
        assert cte == (
            "WITH f0 AS (SELECT DISTINCT OBJECT_ID "
            'FROM VersoZoning_info WHERE "County" IN ($1))'
        )
        assert join == "JOIN f0 USING (OBJECT_ID)"
        assert params == ["Addison"]

    def test_left_join(self):
        src = CTE_SOURCE.model_copy(update={"join_type": "left"})
        _, join = compile_filters([src], [])
        assert join == "LEFT JOIN f0 USING (OBJECT_ID)"

    def test_spatial_join(self):
        src = FilterSource(
            filter_table="VersoZoning_geom",
            join_key="geom",
            join_type="spatial_intersect",
        )
        _, join = compile_filters([src], [])
        assert join == "JOIN f0 ON ST_Intersects(g.geom, f0.geom)"

    def test_multiple_sources_share_numbering(self):
        params: list = []
        cte, _ = compile_filters([CTE_SOURCE, CTE_SOURCE], params)
        assert '"County" IN ($1)' in cte
        assert '"County" IN ($2)' in cte
        assert params == ["Addison", "Addison"]


# ---------------------------------------------------------------------------
# Jinja rendering
# ---------------------------------------------------------------------------


class TestRendering:
    def test_where_string_injected(self):
        sql, params = sql_filter_block(
            BACKEND / "query/sql/acs5/acs5_tidy.sql", [WHERE_SOURCE]
        )
        assert "FROM acs5_demographics_tidy" in sql
        assert 'WHERE "NAME" IN ($1, $2)' in sql
        assert params == ["Vergennes", "Addison town", 2015.0, 2020.0]
        assert "{{" not in sql and "{%" not in sql

    def test_cte_and_join_injected(self):
        sql, params = sql_filter_block(
            BACKEND / "query/sql/zoning/geo_query.sql", [CTE_SOURCE]
        )
        assert sql.startswith("WITH f0 AS (")
        assert "JOIN f0 USING (OBJECT_ID)" in sql
        assert params == ["Addison"]

    def test_params_match_used_fragments_only(self):
        """A CTE-style template must not collect params for the unused WHERE path."""
        sql, params = sql_filter_block(
            BACKEND / "query/sql/zoning/geo_query.sql", [CTE_SOURCE]
        )
        assert sql.count("$") == len(params) == 1

    def test_no_sources_renders_unfiltered(self):
        sql, params = sql_filter_block(BACKEND / "query/sql/zoning/info_table.sql", [])
        assert "WHERE" not in sql
        assert params == []

    def test_undefined_variable_raises(self):
        from jinja2 import UndefinedError

        with pytest.raises(UndefinedError):
            render_sql(BACKEND / "data_cleaning/sql/zoning_info.sql")


# ---------------------------------------------------------------------------
# sqlfluff: templates lint clean, rendered SQL parses as DuckDB
# ---------------------------------------------------------------------------


def test_all_templates_accounted_for():
    """Every .sql file has a representative context in this test module."""
    templates = {
        str(p.relative_to(BACKEND))
        for d in (QUERY_SQL, CLEANING_SQL)
        for p in d.rglob("*.sql")
    }
    assert templates == set(QUERY_TEMPLATE_SOURCES) | set(CLEANING_TEMPLATE_CONTEXT)


def test_templates_pass_sqlfluff():
    """Same check as `sqlfluff lint query/sql data_cleaning/sql` (config in .sqlfluff)."""
    linter = Linter(config=FluffConfig.from_path(str(BACKEND)))
    result = linter.lint_paths((str(QUERY_SQL), str(CLEANING_SQL)))
    violations = result.get_violations()
    assert violations == [], [str(v) for v in violations]


@pytest.mark.parametrize("template", sorted(QUERY_TEMPLATE_SOURCES))
def test_rendered_query_sql_parses(template):
    sql, _params = sql_filter_block(
        BACKEND / template, QUERY_TEMPLATE_SOURCES[template]
    )
    _assert_parses(sql, template)


@pytest.mark.parametrize("template", sorted(CLEANING_TEMPLATE_CONTEXT))
def test_rendered_cleaning_sql_parses(template):
    sql = render_sql(BACKEND / template, **CLEANING_TEMPLATE_CONTEXT[template])
    _assert_parses(sql, template)


def _assert_parses(sql: str, template: str):
    linter = Linter(
        config=FluffConfig(overrides={"dialect": "duckdb", "templater": "raw"})
    )
    parsed = linter.parse_string(sql)
    assert parsed.violations == [], (template, sql, [str(v) for v in parsed.violations])
