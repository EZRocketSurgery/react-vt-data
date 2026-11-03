import duckdb

from data_cleaning.geo_lookup import inline_sql_unavailable
from data_cleaning.margins import reliability_sql

DP_TABLES = {
    "DP02": ("acs5_social", "dp_social"),
    "DP03": ("acs5_economic", "dp_economic"),
    "DP04": ("acs5_housing", "dp_housing"),
    "DP05": ("acs5_demographic", "dp_demographic"),
}

COUNTY_GEOIDS = {
    "Addison County, Vermont": 50001,
    "Bennington County, Vermont": 50003,
    "Caledonia County, Vermont": 50005,
    "Chittenden County, Vermont": 50007,
    "Essex County, Vermont": 50009,
    "Franklin County, Vermont": 50011,
    "Grand Isle County, Vermont": 50013,
    "Lamoille County, Vermont": 50015,
    "Orange County, Vermont": 50017,
    "Orleans County, Vermont": 50019,
    "Rutland County, Vermont": 50021,
    "Washington County, Vermont": 50023,
    "Windham County, Vermont": 50025,
    "Windsor County, Vermont": 50027,
}

# All census "unavailable" data values
# Source: https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html
DP_UNAVAILABLE = {
    "666666666": "The estimate could not be computed because there were an insufficient number of sample observations.",
    "-666666666": "The estimate could not be computed because there were an insufficient number of sample observations.",
    "-888888888": "The estimate is not applicable or not available.",
    "-999999999": "The estimate cannot be displayed because there were an insufficient number of sample cases in the selected geographic area.",
}


def published_moe_sql(moe: str) -> str:
    """
    A raw DP table's published margin of error as a number. -555555555 means
    the estimate is controlled, so its margin is zero; other annotation codes
    (negative, "(X)") are missing.

    Args:
        moe: SQL expression for the raw MOE column

    Returns:
        str: A SQL CASE expression
    """
    return f"""CASE
        WHEN TRY_CAST({moe} AS DOUBLE) = -555555555 THEN 0
        WHEN TRY_CAST({moe} AS DOUBLE) IN ({inline_sql_unavailable(DP_UNAVAILABLE)})
            THEN NULL
        WHEN TRY_CAST({moe} AS DOUBLE) >= 0 THEN TRY_CAST({moe} AS DOUBLE)
    END"""


def _dp_select_sql(dp: str, raw_table_name: str) -> str:
    """
    Build the SELECT query for a single census DP table, joined against `vt_town_lines`
    to attach a `geoid` column.

    Args:
        dp: Data Profile table name (ie. "DP02", "DP03", "DP04", "DP05")
        raw_table_name: The name of the lake.RAW schema DP table.

    Returns:
        str: SQL query string selecting the DP table.
    """

    return f"""--sql
        SELECT
            g.year,
            g.name,
            CASE
                WHEN g.geo_type IN ('county', 'town') THEN LEFT(g.geoid, 5)
            END AS county_fips,
            g.variable_code,
            g.source_label,
            g.category,
            g.subcategory,
            g.variable,
            g.measure,
            g.value,
            g.moe,
            {reliability_sql("g.value", "g.moe")} AS reliability,
            g."table",
            g.geo_type,
            g.geoid
        FROM (
            SELECT
                n.year,
                n.NAME AS name,
                n.Variable_Code AS variable_code,
                n.Source_Label AS source_label,
                n.Category AS category,
                n.Subcategory AS subcategory,
                n.Variable AS variable,
                n.Measure AS measure,
                CASE
                    WHEN n.Value = '(X)' THEN NULL
                    WHEN CAST(n.Value AS DOUBLE) IN ({inline_sql_unavailable(DP_UNAVAILABLE)}) THEN NULL
                    ELSE CAST(n.Value AS DOUBLE)
                END AS "value",
                -- The published margin of error (M for an estimate, PM for a
                -- percent).
                {published_moe_sql("n.MOE")} AS moe,
                '{dp}' AS "table",
                n.geo_type_norm AS geo_type,
                CASE
                    WHEN n.geo_type_norm = 'town' THEN t.GEOID
                    WHEN n.geo_type_norm = 'county' THEN CONCAT(n.state, n.county)
                    WHEN n.geo_type_norm = 'state' THEN '50'
                END AS geoid
            FROM (
                SELECT
                    r.*,
                    CASE
                        WHEN r.geo_type = 'county_subdivision' THEN 'town'
                        ELSE r.geo_type
                    END AS geo_type_norm
                FROM lake.RAW.{raw_table_name} AS r
            ) AS n
            LEFT JOIN (
                SELECT DISTINCT GEOID, NAME FROM lake.RAW.vt_town_lines
            ) AS t
                ON n.NAME = t.NAME
        ) AS g
        """


def add_dp_tables(con: duckdb.DuckDBPyConnection) -> None:
    """
    Write each RAW DP table to CLEANED and add the DP identifier.

    Args:
        con: DuckDBPyConnection to the DuckLake
    """

    for dp, (raw_table, cleaned_table) in DP_TABLES.items():
        con.execute(
            f"""--sql
            CREATE OR REPLACE TABLE lake.CLEANED.{cleaned_table} AS
            {_dp_select_sql(dp, raw_table)}
            """
        )


def build_dp_combined(con: duckdb.DuckDBPyConnection):
    """
    Builds the combined table housing all 4 Census DP tables with a "table" column identifier

    Args:
        con: DuckDBPyConnection to the DuckLake
    """
    unions = [_dp_select_sql(dp, raw_table) for dp, (raw_table, _) in DP_TABLES.items()]

    con.execute(
        f"""--sql
        CREATE OR REPLACE TABLE lake.CLEANED.acs5_dp_combined_tidy AS
        {" UNION ALL ".join(unions)}
        """
    )


def _assert_unique_observations(con: duckdb.DuckDBPyConnection) -> None:
    """
    Enforce the repaired, lossless observation key on the combined DP table:
    (name, year, table, variable_code). Census guarantees variable_code is
    unique within one geography/year/table's API response, so any duplicate
    here means real row duplication (e.g. a join fan-out), not a legitimate
    distinct observation. Fails loudly rather than silently dropping rows.

    Args:
        con: DuckDBPyConnection to the DuckLake
    """
    null_codes = con.execute(
        """--sql
        SELECT count(*) FROM lake.CLEANED.acs5_dp_combined_tidy
        WHERE variable_code IS NULL
        """
    ).fetchone()[0]
    if null_codes:
        raise RuntimeError(
            f"{null_codes} rows in acs5_dp_combined_tidy have a NULL variable_code"
        )

    dupes = con.execute(
        """--sql
        SELECT name, year, "table", variable_code, count(*) AS n
        FROM lake.CLEANED.acs5_dp_combined_tidy
        GROUP BY ALL HAVING count(*) > 1
        """
    ).fetchall()
    if dupes:
        raise RuntimeError(
            f"{len(dupes)} duplicate (name, year, table, variable_code) "
            f"groups in acs5_dp_combined_tidy: {dupes[:10]}"
        )


def build_county_geoids(con: duckdb.DuckDBPyConnection):
    """
    Create the county GEOID lookup table.

    Args:
        con: DuckDBPyConnection to the DuckLake
    """

    values = ", ".join(
        f"('{name}', '{geoid}')" for name, geoid in COUNTY_GEOIDS.items()
    )

    con.execute(
        f"""--sql
        CREATE OR REPLACE TABLE lake.CLEANED.vt_county_geoids AS
        SELECT
            name,
            REPLACE(name, ' County, Vermont', '') AS county,
            geoid,
            geoid AS county_fips
        FROM (
            VALUES {values}
        ) AS t(name, geoid)
        """
    )


def clean(con: duckdb.DuckDBPyConnection):
    add_dp_tables(con)
    build_dp_combined(con)
    _assert_unique_observations(con)
    build_county_geoids(con)


def main(con: duckdb.DuckDBPyConnection):
    clean(con)


if __name__ == "__main__":
    from lake_build import get_connection

    con = get_connection()

    try:
        main(con)
    finally:
        con.close()
