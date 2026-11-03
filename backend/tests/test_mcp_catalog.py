"""Catalog contracts use small in-memory fixtures, never the local warehouse."""

import base64
import json
from pathlib import Path

import duckdb
import pytest

from data_tools.catalog import (
    DATASETS,
    build_locations,
    decode_variable_id,
    describe_dataset,
    encode_variable_id,
    get_dataset,
    list_datasets,
    provenance_metadata,
    search_locations,
    search_variables,
    variable_units,
)


@pytest.fixture
def warehouse():
    with duckdb.connect(":memory:") as conn:
        conn.execute("""
            CREATE TABLE acs5_demographics_tidy (
                year VARCHAR, name VARCHAR, geo_type VARCHAR,
                section VARCHAR, variable VARCHAR, value DOUBLE, percent DOUBLE
            );
            INSERT INTO acs5_demographics_tidy VALUES
                ('2020', 'Vermont', 'state', 'Age/Sex', 'Population (ACS)', 640000, NULL),
                ('2024', 'Vermont', 'state', 'Age/Sex', 'Population (ACS)', 647000, NULL),
                ('2024', 'Vermont', 'state', 'Age/Sex', 'Median Age', 43.5, NULL),
                ('unavailable', 'Vermont', 'state', 'Race', 'White', 600000, 92.7);
            CREATE TABLE acs5Demographics_medianAge_timeseries (
                year VARCHAR, name VARCHAR, geo_type VARCHAR, median_age DOUBLE
            );
            INSERT INTO acs5Demographics_medianAge_timeseries
                VALUES ('2024', 'Vermont', 'state', 43.5);
            CREATE TABLE vt_county_geoids (NAME VARCHAR, GEOID INTEGER);
            INSERT INTO vt_county_geoids VALUES
                ('Chittenden County, Vermont', 50007),
                ('Franklin County, Vermont', 50011),
                ('Orleans County, Vermont', 50019);
            CREATE TABLE vt_town_lines_geom (FIPS_ID VARCHAR, TOWN_NAME VARCHAR);
            INSERT INTO vt_town_lines_geom VALUES
                ('5001161675', 'St. Albans city'),
                ('5001161750', 'St. Albans town'),
                ('5001948925', 'Newport city'),
                ('5001949000', 'Newport town'),
                ('5000710675', 'Burlington city');
            CREATE TABLE vt_tract_lines_geom (LocationID VARCHAR, name VARCHAR);
            INSERT INTO vt_tract_lines_geom VALUES ('50007003900', 'Census Tract 39');
        """)
        yield conn


def test_catalog_covers_every_export_and_profile_flood_extensions():
    # Keep this explicit: renaming a public dataset ID breaks saved agent prompts.
    expected = {
        "acs5_demographics",
        "acs5_economics",
        "acs5_housing",
        "acs5_education",
        "acs5_snapshot",
        "acs5_ts_historic_population",
        "acs5_ts_historic_population_change",
        "acs5_ts_population_change",
        "acs5_ts_median_age",
        "acs5_ts_age_dependency_ratio",
        "acs5_ts_median_home_value",
        "acs5_ts_vacancy_rates",
        "acs5_ts_income_burden",
        "acs5_ts_household_income",
        "acs5_ts_per_capita_income",
        "acs5_ts_median_earnings",
        "acs5_ts_health_insurance",
        "acs5_ts_housing_units",
        "qcew_employment_by_sector",
        "zoning_districts",
        "zoning_bylaws",
        "wastewater_service_areas",
        "wastewater_treatment_facilities",
        "wastewater_treatment_facility_permits",
        "wastewater_soil_suitability",
        "wastewater_stormwater_management",
        "cdc_places_county",
        "cdc_places_tract",
        "ambulance_service_areas",
        "acs5_dp",
        "flood_hazard",
    }
    assert set(DATASETS) == expected
    assert all(
        dataset.source_url.startswith("https://") for dataset in DATASETS.values()
    )
    assert all(
        "geometry" not in dataset.filter_columns for dataset in DATASETS.values()
    )


def test_availability_and_years_are_from_current_warehouse(warehouse):
    datasets = {row["dataset_id"]: row for row in list_datasets(warehouse)}
    demographics = datasets["acs5_demographics"]
    assert demographics["available"] is True
    assert (demographics["year_min"], demographics["year_max"]) == (2020, 2024)
    assert datasets["acs5_dp"]["available"] is False
    assert datasets["acs5_dp"]["year_max"] is None
    unavailable = describe_dataset(warehouse, "acs5_dp")
    assert unavailable["columns"] == []
    assert "absent" in unavailable["unavailable_reason"]
    description = describe_dataset(warehouse, "acs5_demographics")
    assert description["geo_types"] == ["state"]
    assert {row["name"] for row in description["columns"]} == {
        "year",
        "name",
        "geo_type",
        "section",
        "variable",
        "value",
        "percent",
    }


def test_catalog_search_is_case_insensitive_and_unknown_ids_rejected(warehouse):
    matches = list_datasets(warehouse, "MEDIAN AGE")
    assert [row["dataset_id"] for row in matches] == ["acs5_ts_median_age"]
    with pytest.raises(ValueError, match="Unknown dataset"):
        get_dataset("acs5_demographics; DROP TABLE acs5_demographics_tidy")


def test_variable_search_deduplicates_years_and_roundtrips(warehouse):
    rows = search_variables(warehouse, "acs5_demographics", query="population")
    assert len(rows) == 1
    assert rows[0]["selectors"] == {
        "section": "Age/Sex",
        "variable": "Population (ACS)",
    }
    assert rows[0]["value_columns"] == {
        "value": "people",
        "value_moe": "people",
        "percent": "percent",
        "percent_moe": "percentage points",
    }
    dataset = get_dataset("acs5_demographics")
    assert decode_variable_id(dataset, rows[0]["variable_id"]) == rows[0]["selectors"]
    assert (
        rows[0]["variable_id"]
        == search_variables(warehouse, "acs5_demographics", "POPULATION")[0][
            "variable_id"
        ]
    )
    assert search_variables(warehouse, "acs5_demographics", "'; DROP TABLE x; --") == []
    assert len(search_variables(warehouse, "acs5_demographics", limit=1)) == 1


def test_wide_metric_variable_id_and_units(warehouse):
    # The margin is not a variable of its own: it comes back with the estimate.
    [row] = search_variables(warehouse, "acs5_ts_median_age")
    assert row["selectors"] == {"$column": "median_age"}
    assert row["measures"] == [
        {"name": "median_age", "unit": "years"},
        {"name": "median_age_moe", "unit": "years"},
    ]
    assert decode_variable_id(
        get_dataset("acs5_ts_median_age"), row["variable_id"]
    ) == {"$column": "median_age"}
    median = search_variables(warehouse, "acs5_demographics", "median")[0]
    assert median["value_columns"]["value"] == "years"


def _encoded(payload):
    return "v1:" + base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")


@pytest.mark.parametrize(
    "variable_id",
    [
        "plain_column",
        "v1:!!!",
        "v1:W10",
        "v2:abcdef",
        "v1:" + "x" * 17000,
        _encoded(
            {
                "dataset_id": "acs5_housing",
                "selectors": {"Section": "A", "Variable": "B"},
            }
        ),
        _encoded(
            {"dataset_id": "acs5_demographics", "selectors": {"Variable": "Population"}}
        ),
        _encoded(
            {
                "dataset_id": "acs5_demographics",
                "selectors": {
                    "Section": "Age/Sex",
                    "Variable": "Population",
                    "sql": "SELECT * FROM secrets",
                },
            }
        ),
        _encoded(
            {
                "dataset_id": "acs5_demographics",
                "selectors": {"Section": [], "Variable": "Population"},
            }
        ),
        _encoded(
            {
                "dataset_id": "acs5_demographics",
                "selectors": {"Section": "Age/Sex", "Variable": "x" * 2049},
            }
        ),
    ],
)
def test_invalid_cross_dataset_or_injected_variable_ids_rejected(variable_id):
    with pytest.raises(ValueError):
        decode_variable_id(get_dataset("acs5_demographics"), variable_id)


def test_wide_metric_rejects_unknown_or_unhashable_column():
    dataset = get_dataset("acs5_ts_median_age")
    for column in ("read_csv('/private/key')", [], None):
        with pytest.raises(ValueError):
            decode_variable_id(
                dataset, encode_variable_id(dataset, {"$column": column})
            )


def test_canonical_locations_keep_city_and_town_distinct(warehouse):
    locations = search_locations(warehouse, "St. Albans")
    assert {row["id"] for row in locations} == {"5001161675", "5001161750"}
    assert {row["geo_type"] for row in locations} == {"county_subdivision"}
    assert all(row["county"] == "50011" for row in locations)
    assert {row["name"] for row in locations} == {
        "St. Albans city, Franklin County, Vermont",
        "St. Albans town, Franklin County, Vermont",
    }
    county = search_locations(warehouse, "Chittenden", "county")
    assert [row["id"] for row in county] == ["50007"]
    tract = search_locations(warehouse, "50007003900")
    assert tract[0]["name"] == "Census Tract 39, Chittenden County, Vermont"
    assert tract[0]["id"] == tract[0]["location_id"] == tract[0]["geoid"]
    assert len({row["id"] for row in build_locations(warehouse)}) == len(
        build_locations(warehouse)
    )
    assert all(
        "st. albans" not in {alias.casefold() for alias in row["aliases"]}
        for row in locations
    )


def test_place_name_matches_rank_before_county_context(warehouse):
    warehouse.execute("""
        INSERT INTO vt_county_geoids VALUES ('Rutland County, Vermont', 50021);
        INSERT INTO vt_town_lines_geom VALUES
            ('5002161225', 'Rutland city'), ('5002161300', 'Rutland town'),
            ('5002183200', 'West Rutland town'), ('5002104525', 'Benson town');
        INSERT INTO vt_tract_lines_geom VALUES ('50021000100', 'Census Tract 1');
    """)
    results = search_locations(warehouse, "Rutland", limit=4)
    assert {row["id"] for row in results[:3]} == {"50021", "5002161225", "5002161300"}
    assert results[3]["name"].startswith("West Rutland")
    for row in results:
        if row["id"] in {"5002161225", "5002161300"}:
            assert "rutland" not in {alias.casefold() for alias in row["aliases"]}


def test_current_census_spelling_is_an_alias_for_boundary_geoid(warehouse):
    warehouse.execute("""
        INSERT INTO vt_town_lines_geom VALUES ('5001124050', 'Enosburgh town');
        INSERT INTO acs5_demographics_tidy VALUES
            ('2024', 'Enosburg town, Franklin County, Vermont', 'county_subdivision',
             'Age/Sex', 'Population (ACS)', 2800, NULL);
    """)
    place = search_locations(warehouse, "5001124050")[0]
    assert "Enosburg town, Franklin County, Vermont" in place["aliases"]


def test_historical_geoid_lookup_retains_full_name_and_merges_aliases(warehouse):
    warehouse.execute("""
        CREATE TABLE VCGI_historicPopulation_timeseries (
            geoid BIGINT, NAME VARCHAR, geo_type VARCHAR, Jurisdiction VARCHAR, County VARCHAR
        );
        INSERT INTO VCGI_historicPopulation_timeseries VALUES
            (5000710675, 'Burlington city, Chittenden County, Vermont', 'town',
             'Burlington city', 'Chittenden'),
            (5000739325, 'Historical place, Chittenden County, Vermont', 'town',
             'Historical place', 'Chittenden');
    """)
    assert len(search_locations(warehouse, "Burlington")) == 1
    historical = search_locations(warehouse, "Historical place")
    assert historical[0]["id"] == "5000739325"
    assert historical[0]["geo_type"] == "county_subdivision"


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_discovery_limits_are_enforced(warehouse, limit):
    with pytest.raises(ValueError, match="limit"):
        search_variables(warehouse, "acs5_demographics", limit=limit)
    with pytest.raises(ValueError, match="limit"):
        search_locations(warehouse, limit=limit)


def test_missing_dataset_and_unknown_geography_fail_clearly(warehouse):
    with pytest.raises(ValueError, match="not available"):
        search_variables(warehouse, "cdc_places_county")
    with pytest.raises(ValueError, match="Unknown geography"):
        search_locations(warehouse, geo_type="zip")


def test_units_preserve_percentages_and_source_specific_estimates():
    dataset = get_dataset("acs5_dp")
    assert variable_units(dataset, {"measure": "Percent Estimate"}) == {
        "value": "percent",
        "moe": "percentage points",
    }
    assert "source-defined" in variable_units(dataset, {"measure": "Estimate"})["value"]
    assert get_dataset("zoning_bylaws").value_columns["f1f_min_lot_size"] == "acres"
    assert get_dataset("acs5_ts_health_insurance").value_columns["Value"] == "people"
    assert "with a mortgage" in get_dataset("acs5_ts_income_burden").description
    economics = get_dataset("acs5_economics")
    assert variable_units(
        economics, {"variable": "Labor Force Participation Rate (16+)"}
    ) == {
        "value": "people",
        "value_moe": "people",
        "percent": "percent",
        "percent_moe": "percentage points",
    }
    housing = get_dataset("acs5_housing")
    assert variable_units(housing, {"variable": "Rental Vacancy Rate"}) == {
        "value": "housing units",
        "value_moe": "housing units",
        "percent": "percent",
        "percent_moe": "percentage points",
    }
    assert (
        "unavailable"
        in variable_units(economics, {"variable": "Income below poverty"})["value"]
    )


def test_location_index_requires_no_observation_tables():
    with duckdb.connect(":memory:") as conn:
        assert {row["id"] for row in build_locations(conn)} == {"US", "50"}


@pytest.fixture
def profile_warehouse(warehouse):
    warehouse.execute("""
        CREATE TABLE acs5_dp_combined_tidy (
            name VARCHAR, "table" VARCHAR, category VARCHAR, subcategory VARCHAR,
            variable VARCHAR, measure VARCHAR, year INTEGER, value VARCHAR
        );
        INSERT INTO acs5_dp_combined_tidy VALUES
            ('Burlington city, Chittenden County, Vermont', 'DP04', 'Estimate',
             'GROSS RENT', 'Occupied units paying rent: Median (dollars)', 'Number', 2009, '900'),
            ('Chittenden County, Vermont', 'DP04', 'GROSS RENT', 'Median (dollars)',
             'Total', 'Estimate', 2010, '950'),
            ('Burlington city, Chittenden County, Vermont', 'DP04', 'GROSS RENT',
             'Median (dollars)', 'Total', 'Estimate', 2011, '1000'),
            ('Burlington city, Chittenden County, Vermont', 'DP04', 'GROSS RENT',
             'Occupied units paying rent', 'Median (dollars)', 'Estimate', 2013, '1100'),
            ('Burlington city, Chittenden County, Vermont', 'DP04', 'GROSS RENT',
             'Occupied units paying rent', 'Median (dollars)', 'Estimate', 2014, '1200'),
            ('Burlington city, Chittenden County, Vermont', 'DP04',
             'GROSS RENT AS A PERCENTAGE OF HOUSEHOLD INCOME (GRAPI)',
             '35.0 percent or more', 'Total', 'Percent', 2011, '24.5'),
            ('Burlington city, Chittenden County, Vermont', 'DP04',
             'GROSS RENT AS A PERCENTAGE OF HOUSEHOLD INCOME (GRAPI)',
             'Occupied units paying rent', '35.0 percent or more', 'Percent Estimate', 2017, '22.5'),
            ('Burlington city, Chittenden County, Vermont', 'DP04', 'GROSS RENT',
             'Occupied units paying rent', 'Total', 'Percent Estimate', 2017, '4047'),
            ('United States', 'DP04', 'GROSS RENT',
             'Median (dollars)', 'Total', 'Estimate', 2010, '900'),
            ('Vermont', 'DP04', 'GROSS RENT',
             'Median (dollars)', 'Total', 'Estimate', 2010, '900');
    """)
    return warehouse


def test_multiword_variable_search_matches_across_dimensions_and_punctuation(
    profile_warehouse,
):
    query = "GROSS RENT Median (dollars)"
    rows = search_variables(profile_warehouse, "acs5_dp", query)
    assert len(rows) == 3
    assert {row["variable_id"] for row in rows} == {
        row["variable_id"]
        for row in search_variables(
            profile_warehouse, "acs5_dp", "gross, RENT! median--DOLLARS"
        )
    }
    assert rows == search_variables(profile_warehouse, "acs5_dp", query)
    assert (
        search_variables(profile_warehouse, "acs5_dp", "gross rent nonexistent") == []
    )
    assert (
        search_variables(profile_warehouse, "acs5_dp", "'); DROP TABLE users; --") == []
    )
    brackets = search_variables(
        profile_warehouse, "acs5_dp", "GRAPI 35.0 percent or more"
    )
    assert len(brackets) == 2
    assert {row["selectors"]["measure"] for row in brackets} == {
        "Percent",
        "Percent Estimate",
    }


def test_selector_variants_report_their_actual_distinct_years(profile_warehouse):
    rows = search_variables(profile_warehouse, "acs5_dp", "gross rent median dollars")
    variants = {
        row["selectors"]["measure"] + ":" + row["selectors"]["variable"]: row
        for row in rows
    }
    assert variants["Number:Occupied units paying rent: Median (dollars)"][
        "years_available"
    ] == [2009]
    assert variants["Estimate:Total"]["years_available"] == [2010, 2011]
    assert variants["Estimate:Median (dollars)"]["years_available"] == [2013, 2014]
    assert all("not a harmonized" in row["coverage_note"] for row in rows)
    assert all(
        decode_variable_id(get_dataset("acs5_dp"), row["variable_id"])
        == row["selectors"]
        for row in rows
    )


def test_profile_coverage_discloses_geography_specific_gaps(profile_warehouse):
    description = describe_dataset(profile_warehouse, "acs5_dp")
    assert description["years_available"] == [2009, 2010, 2011, 2013, 2014, 2017]
    assert 2010 not in description["gaps"]
    towns = description["coverage_by_geo_type"]["county_subdivision"]
    assert 2010 in towns["gaps"]
    assert towns["years_available"] == [2009, 2011, 2013, 2014, 2017]
    assert towns["geography_count_by_year"]["2011"] == 1
    assert description["coverage_by_geo_type"]["county"]["years_available"] == [2010]
    assert description["geo_types"] == [
        "county",
        "county_subdivision",
        "national",
        "state",
    ]
    assert "does not guarantee" in description["coverage_note"]


def test_default_and_filtered_distinct_value_discovery(profile_warehouse):
    description = describe_dataset(profile_warehouse, "acs5_dp")
    assert description["filter_values_by_column"]["measure"]["values"] == [
        "Estimate",
        "Number",
        "Percent",
        "Percent Estimate",
    ]
    filtered = describe_dataset(
        profile_warehouse,
        "acs5_dp",
        value_column="measure",
        value_filters={"table": [" dp04 "], "year": [2017]},
        value_limit=20,
    )["filter_values"]
    assert filtered["values"] == ["Percent Estimate"]
    assert filtered["has_more"] is False
    assert filtered["applied_filters"] == {"table": [" dp04 "], "year": [2017]}
    truncated = describe_dataset(
        profile_warehouse,
        "acs5_dp",
        value_column="measure",
        value_limit=2,
    )["filter_values"]
    assert truncated["values"] == ["Estimate", "Number"]
    assert truncated["has_more"] is True


def test_distinct_values_trim_and_deduplicate_text_without_ignoring_bad_filters(
    profile_warehouse,
):
    profile_warehouse.execute("""
        INSERT INTO acs5_dp_combined_tidy VALUES
            ('Vermont', 'DP04 ', 'GROSS RENT ', 'Median (dollars)', 'Total', 'Estimate ', 2010, '900');
    """)
    result = describe_dataset(
        profile_warehouse,
        "acs5_dp",
        value_column="category",
        value_filters={"table": ["dp04"], "measure": [" ESTIMATE "]},
    )
    assert result["filter_values"]["values"] == ["GROSS RENT"]
    for kwargs in (
        {"value_column": "value"},
        {"value_column": "measure; DROP TABLE x"},
        {"value_column": "measure", "value_filters": {"unknown": ["x"]}},
        {"value_column": "measure", "value_filters": {"table": []}},
        {"value_column": "measure", "value_filters": {"table": [float("inf")]}},
        {"value_filters": {"table": ["DP04"]}},
    ):
        with pytest.raises(ValueError):
            describe_dataset(profile_warehouse, "acs5_dp", **kwargs)
    injected = describe_dataset(
        profile_warehouse,
        "acs5_dp",
        value_column="measure",
        value_filters={"table": ["DP04' OR TRUE --"]},
    )
    assert injected["filter_values"]["values"] == []


def test_provenance_identifies_the_current_served_pipeline_without_guessing_codes():
    income = provenance_metadata(get_dataset("acs5_ts_household_income"))
    assert income["warehouse_table"] == "acs5Economics_medianHouseholdIncome_timeseries"
    assert income["source_columns"]["median_household_income"]["census_codes"] == [
        "B19013_001E"
    ]
    assert "backend/data_collection/economic.py" in income["transformations"]
    home = provenance_metadata(get_dataset("acs5_ts_median_home_value"))
    assert home["source_columns"]["median_home_value"]["census_codes"] == [
        "B25077_001E"
    ]
    assert "backend/data_cleaning/clean_acs5_timeseries.py" in home["transformations"]
    assert "retired build/acs5.py" in home["source_code_note"]
    assert "not a certificate" in home["source_code_note"]
    burden = provenance_metadata(get_dataset("acs5_ts_income_burden"))
    assert burden["source_columns"]["Value"]["census_codes"] == []
    assert burden["source_columns"]["Value"]["selectors"]["Measure"] == "Estimate"
    assert set(burden["source_columns"]) == {"Value", "Total", "Percent"}
    assert "Percent Estimate" in burden["source_code_note"]
    assert "backend/data_cleaning/clean_acs5_timeseries.py" in burden["transformations"]


@pytest.mark.parametrize("dataset_id", sorted(DATASETS))
def test_provenance_references_files_that_exist(dataset_id):
    # Lineage paths are hand-maintained; a renamed or consolidated cleaner
    # would otherwise leave the MCP pointing at code that no longer exists.
    repo_root = Path(__file__).resolve().parents[2]
    lineage = provenance_metadata(get_dataset(dataset_id))
    paths = list(lineage["transformations"]) + [
        col["code_reference"]
        for col in lineage["source_columns"].values()
        if "code_reference" in col
    ]
    missing = [p for p in paths if not (repo_root / p).is_file()]
    assert not missing, f"{dataset_id} lineage references missing files: {missing}"


def test_percent_total_units_are_conservative_but_true_percent_brackets_survive():
    dataset = get_dataset("acs5_dp")
    suspicious = {
        "variable": " Total ",
        "measure": "Percent Estimate",
        "subcategory": "Occupied units paying rent",
    }
    assert "unit not verified" in variable_units(dataset, suspicious)["value"]
    genuine_bracket = suspicious | {"subcategory": "35.0 percent or more"}
    assert variable_units(dataset, genuine_bracket)["value"] == "percent"
    assert (
        variable_units(
            dataset, genuine_bracket | {"subcategory": "Less than 20.0 percent"}
        )["value"]
        == "percent"
    )
    assert any("contain totals" in caveat for caveat in dataset.caveats)
