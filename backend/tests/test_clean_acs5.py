"""
Regression tests for the ACS5 DP profile observation-identity fix (issue A1).

Burlington's DP04 "median monthly owner cost" selector historically collided:
the 2011/2012 mortgaged (DP04_0100E) and non-mortgaged (DP04_0107E) SMOC
medians share an identical Category/Subcategory/Variable/Measure once split
into the label hierarchy, so a key built from those labels alone loses one of
the two observations. Figures below are the real Burlington values from
backend/Data/Census/med_smoc_by_year.csv.

Run against an in-memory `lake` catalog instead of the DuckLake, following the
pattern in test_geo_lookup.py.
"""

import duckdb
import pytest

from data_cleaning.clean_acs5 import (
    DP_TABLES,
    _assert_unique_observations,
    build_dp_combined,
)
from query.production_db import get_db

BURLINGTON = "Burlington city, Chittenden County, Vermont"
BURLINGTON_GEOID = "5000710675"

_RAW_SCHEMA = """
    year BIGINT, NAME VARCHAR, Variable_Code VARCHAR, Source_Label VARCHAR,
    Category VARCHAR, Subcategory VARCHAR, Variable VARCHAR, Measure VARCHAR,
    Value VARCHAR, geo_type VARCHAR, state VARCHAR, county VARCHAR
"""

# (year, Variable_Code, Value) for Burlington's colliding DP04 SMOC medians.
# Category/Subcategory/Variable/Measure are identical for both codes.
SMOC_ROWS = [
    (2011, "DP04_0100E", "1731"),  # Mortgaged
    (2011, "DP04_0107E", "699"),  # Non-mortgaged
    (2012, "DP04_0100E", "1764"),  # Mortgaged
    (2012, "DP04_0107E", "737"),  # Non-mortgaged
]


def _base_con():
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS lake")
    con.execute("CREATE SCHEMA lake.RAW")
    con.execute("CREATE SCHEMA lake.CLEANED")
    con.execute(
        f"""
        CREATE TABLE lake.RAW.vt_town_lines AS
        SELECT '{BURLINGTON_GEOID}' AS GEOID, '{BURLINGTON}' AS NAME
        """
    )
    # build_dp_combined() unions all four DP profiles; give the other three
    # empty raw tables so only DP04 (housing) carries fixture rows.
    for raw_table, _ in DP_TABLES.values():
        if raw_table != "acs5_housing":
            con.execute(f"CREATE TABLE lake.RAW.{raw_table} ({_RAW_SCHEMA})")
    return con


def _housing_rows(rows):
    values = ", ".join(
        f"""(
            {year}, '{BURLINGTON}', '{code}',
            'Estimate!!SELECTED MONTHLY OWNER COSTS (SMOC)!!Median (dollars)',
            'SELECTED MONTHLY OWNER COSTS (SMOC)', 'Median (dollars)', 'Total',
            'Estimate', '{value}', 'county_subdivision', '50', '007'
        )"""
        for year, code, value in rows
    )
    return f"""
        CREATE TABLE lake.RAW.acs5_housing ({_RAW_SCHEMA});
        INSERT INTO lake.RAW.acs5_housing VALUES {values}
        """


def test_colliding_smoc_observations_survive_distinctly():
    con = _base_con()
    con.execute(_housing_rows(SMOC_ROWS))
    build_dp_combined(con)

    rows = con.execute(
        """
        SELECT year, variable_code, value FROM lake.CLEANED.acs5_dp_combined_tidy
        WHERE "table" = 'DP04' ORDER BY year, variable_code
        """
    ).fetchall()

    assert rows == [
        (2011, "DP04_0100E", 1731.0),
        (2011, "DP04_0107E", 699.0),
        (2012, "DP04_0100E", 1764.0),
        (2012, "DP04_0107E", 737.0),
    ]


def test_dp_values_are_numeric_with_unavailable_codes_nulled():
    con = _base_con()
    # Census marks values it cannot publish with "(X)" or a sentinel code.
    con.execute(
        _housing_rows(
            [
                (2011, "DP04_0100E", "1731"),
                (2011, "DP04_0101E", "(X)"),
                (2011, "DP04_0102E", "666666666"),
                (2011, "DP04_0103E", "-666666666"),
                (2011, "DP04_0104E", "-888888888"),
                (2011, "DP04_0105E", "-999999999"),
            ]
        )
    )
    build_dp_combined(con)

    assert con.execute(
        """
        SELECT data_type FROM duckdb_columns()
        WHERE table_name = 'acs5_dp_combined_tidy' AND column_name = 'value'
        """
    ).fetchone() == ("DOUBLE",)
    rows = con.execute(
        """
        SELECT variable_code, value FROM lake.CLEANED.acs5_dp_combined_tidy
        ORDER BY variable_code
        """
    ).fetchall()
    assert rows == [
        ("DP04_0100E", 1731.0),
        ("DP04_0101E", None),
        ("DP04_0102E", None),
        ("DP04_0103E", None),
        ("DP04_0104E", None),
        ("DP04_0105E", None),
    ]


def test_assert_unique_observations_passes_on_distinct_codes():
    con = _base_con()
    con.execute(_housing_rows(SMOC_ROWS))
    build_dp_combined(con)

    _assert_unique_observations(con)  # should not raise


def test_assert_unique_observations_catches_a_real_collision():
    con = _base_con()
    # Two rows sharing the same variable_code for the same (name, year, table).
    con.execute(
        _housing_rows([(2011, "DP04_0100E", "1731"), (2011, "DP04_0100E", "9999")])
    )
    build_dp_combined(con)

    with pytest.raises(RuntimeError, match="duplicate"):
        _assert_unique_observations(con)


def test_duplicate_town_lines_row_does_not_fan_out_observations():
    con = _base_con()
    # A repeat NAME in vt_town_lines (e.g. a source data glitch) must not
    # duplicate rows via the geography join.
    con.execute(
        f"INSERT INTO lake.RAW.vt_town_lines VALUES ('{BURLINGTON_GEOID}', '{BURLINGTON}')"
    )
    con.execute(_housing_rows(SMOC_ROWS))
    build_dp_combined(con)

    _assert_unique_observations(con)  # should not raise despite the dup join row


@pytest.mark.requires_warehouse
def test_dp_value_col():
    con = get_db()
    (data_type,) = con.execute(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'acs5_dp_combined_tidy' AND column_name = 'value'
        """
    ).fetchone()
    if data_type != "DOUBLE":
        pytest.skip(
            f"warehouse.duckdb predates the DOUBLE value cast ({data_type}); "
            "rebuild it with `just etl`"
        )
    df = con.execute("SELECT value FROM main.acs5_dp_combined_tidy").df()
    print(df["value"].dtype, df["value"].min(), df["value"].max())

    assert df["value"].dtype.kind == "f"
    assert df["value"].min() >= 0
    assert df["value"].max() < 666666666
