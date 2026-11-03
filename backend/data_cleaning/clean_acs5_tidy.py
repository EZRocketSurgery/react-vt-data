"""
**Author**:
    Ian Sargent
**Created**:
    2026-07-13
**Description**:
    Data cleaning for the raw (curated variables) ACS-5 `demographics`,
    `economic`, `education` and `housing` tables in the DuckLake, plus the
    `snapshot` table that combines a few key indicators from them.

    Each output is in tidy format: year, geoid, name, geo_type, county, county_fips,
    section, variable, value, value_moe, value_reliability, percent,
    percent_moe, percent_reliability. The *_moe columns are 90% margins of
    error (percent_moe in percentage points), computed at collection (see
    data_collection/base.py); *_reliability labels them (see margins.py).
**Run with**:
python run_data_cleaning.py clean_acs5_tidy
"""

import duckdb

from data_cleaning.geo_lookup import acs_geo_sql, build_geo_lookups, write_table
from data_cleaning.margins import reliability_sql

# RAW table name -> CLEANED table name
TIDY_TABLES = {
    "demographics": "acs5_demographics_tidy",
    "economic": "acs5_economics_tidy",
    "education": "acs5_education_tidy",
    "housing": "acs5_housing_tidy",
}

# Snapshot indicators, by RAW table
SNAPSHOT_VARIABLES = {
    "demographics": ["Population (ACS)", "Median Age"],
    "economic": ["Labor Force Participation Rate (16+)", "Median Household Income"],
    "housing": ["Median Home Value"],
}
SNAPSHOT_TABLE_NAME = "acs5_snapshot_indicators_tidy"


def tidy_sql(base: str) -> str:
    """
    SQL query creation of the tidy table
    using :func:`geo_lookup.acs_geo_sql` function.

    Args:
        base: Raw SELECT statement exposing columns (NAME, geo_type, state, and county)

    Returns:
        str: SELECT SQL query taking from the provided base query
    """
    return f"""--sql
        SELECT
            year,
            geoid,
            name,
            geo_type,
            county,
            county_fips,
            section AS section,
            variable AS variable,
            value AS value,
            value_moe AS value_moe,
            {reliability_sql("value", "value_moe")} AS value_reliability,
            percent AS percent,
            percent_moe AS percent_moe,
            -- Collection rounds percent_moe to 0.1 point, so a small share's
            -- real margin can round to 0, which reliability_sql reads as a
            -- controlled estimate. Unless the count is controlled too, label
            -- the share by its count: exact when the total is controlled, and
            -- otherwise never rosier than the share's own label.
            CASE
                WHEN percent_moe = 0 AND value_moe > 0
                    THEN {reliability_sql("value", "value_moe")}
                ELSE {reliability_sql("percent", "percent_moe")}
            END AS percent_reliability
        FROM ({acs_geo_sql(base)})
        """


def snapshot_base() -> str:
    """
    Selects the specified `SNAPSHOT_VARIABLES` from each source table.

    Returns:
        str: Final combination SQL statement of selected snapshot variable tables.
    """
    selects = []
    for table, variables in SNAPSHOT_VARIABLES.items():
        in_list = ", ".join(f"'{v}'" for v in variables)
        selects.append(f"SELECT * FROM lake.RAW.{table} WHERE Variable IN ({in_list})")

    return " UNION ALL BY NAME ".join(selects)


def main(con: duckdb.DuckDBPyConnection):
    build_geo_lookups(con)

    for raw_table, cleaned_table in TIDY_TABLES.items():
        write_table(con, cleaned_table, tidy_sql(f"SELECT * FROM lake.RAW.{raw_table}"))

    write_table(con, SNAPSHOT_TABLE_NAME, tidy_sql(snapshot_base()))
