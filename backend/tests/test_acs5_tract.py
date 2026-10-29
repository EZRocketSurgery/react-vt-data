"""
Tests for the tract-level ACS collector's reshaping and the cleaner's
indicators, run against small in-memory fixtures instead of the Census API
or the DuckLake.
"""

import math

import duckdb
import pandas as pd
import pytest

from data_cleaning.clean_acs5_tract import (
    AT_OR_ABOVE_138,
    BELOW_138,
    c27016,
    main,
    uninsured,
)
from data_collection.acs5_tract import to_long

TRACT = ("Census Tract 9601; Addison County; Vermont", "50", "001", "960100")


def test_to_long_keeps_estimates_moes_and_sentinels():
    # Like a real group() response: GEO_ID, annotation columns, and NAME
    # appearing twice.
    wide = pd.DataFrame(
        [["1400000US50001960100", TRACT[0], *TRACT,
          "1000", "100", "-666666666", "-555555555", "x"]],
        columns=["GEO_ID", "NAME", "NAME", "state", "county", "tract",
                 "B17001_001E", "B17001_001M", "B17001_002E", "B17001_002M",
                 "B17001_002EA"],
    )  # fmt: skip
    long = to_long(wide, "B17001", 2024).set_index("code")

    assert list(long.index) == ["B17001_001", "B17001_002"]
    assert long.loc["B17001_001", ["estimate", "moe"]].tolist() == [1000, 100]
    # Sentinels stay as-is in RAW; the cleaner decides what they mean.
    assert long.loc["B17001_002", "estimate"] == -666666666
    assert (long["year"] == 2024).all()


def _raw(estimates: dict[str, tuple[float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            (2024, *TRACT, code, est, moe)
            for code, (est, moe) in estimates.items()
        ],
        columns=["year", "NAME", "state", "county", "tract", "code",
                 "estimate", "moe"],
    )  # fmt: skip


@pytest.fixture
def lake():
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS lake")
    con.execute("CREATE SCHEMA lake.RAW")
    con.execute("CREATE SCHEMA lake.CLEANED")
    con.execute(
        """
        CREATE TABLE lake.RAW.vt_town_lines AS
        SELECT 5000144350 AS GEOID,
            'Middlebury town, Addison County, Vermont' AS NAME
        """
    )
    return con


def _clean(con, estimates) -> pd.DataFrame:
    con.register("raw_df", _raw(estimates))
    con.execute("CREATE OR REPLACE TABLE lake.RAW.acs5_tract AS SELECT * FROM raw_df")
    main(con)
    return con.execute("SELECT * FROM lake.CLEANED.acs5_tract_tidy").df()


def _c27016_fixture(uninsured_count: float) -> dict[str, tuple[float, float]]:
    """Every C27016 code, 100 people per poverty group, `uninsured_count`
    uninsured in each group's 19-64 bracket."""
    codes = {c27016(1): (500, 40)}
    for start in BELOW_138 + AT_OR_ABOVE_138:
        codes[c27016(start)] = (100, 20)
        for k in range(1, 10):
            codes[c27016(start + k)] = (0, 10)
        codes[c27016(start + 6)] = (uninsured_count, 10)
    return codes


def test_poverty_rate_and_census_margin_of_error(lake):
    df = _clean(lake, {"B17001_001": (1000, 100), "B17001_002": (150, 50)})
    row = df[df.variable == "Below poverty level"].iloc[0]

    assert row.geoid == "50001960100"
    assert row.county == "Addison"
    assert row["name"] == "Census Tract 9601, Addison County"
    assert (row.value, row.universe, row.percent) == (150, 1000, 15.0)
    # sqrt(MOE_num^2 - p^2 * MOE_den^2) / den = sqrt(2500 - 225) / 1000
    assert row.percent_moe == round(100 * math.sqrt(50**2 - 0.15**2 * 100**2) / 1000, 1)


def test_uninsured_split_by_poverty_is_a_crosstab(lake):
    df = _clean(lake, _c27016_fixture(uninsured_count=8)).set_index("variable")

    # 8 uninsured in each of 5 groups of 100: 40 / 500 overall, 16 / 200
    # below 138% of poverty, 24 / 300 at or above it.
    assert df.loc["No health insurance", "percent"] == 8.0
    assert df.loc["No health insurance, below 138% of poverty", "percent"] == 8.0
    assert df.loc["No health insurance, 138% of poverty or more", "value"] == 24
    assert len(uninsured(BELOW_138 + AT_OR_ABOVE_138)) == 15


def test_controlled_margin_counts_as_zero(lake):
    # -555555555: the universe is controlled, so it has no sampling error.
    df = _clean(lake, {"B17001_001": (1000, -555555555), "B17001_002": (150, 50)})
    row = df[df.variable == "Below poverty level"].iloc[0]

    assert row.percent_moe == round(100 * 50 / 1000, 1)


def test_uncomputable_margin_makes_the_margin_null(lake):
    # -222222222: too few sample cases to compute a margin. The estimate
    # stands, but its margin is unknown, not zero.
    df = _clean(lake, {"B17001_001": (1000, 100), "B17001_002": (0, -222222222)})
    row = df[df.variable == "Below poverty level"].iloc[0]

    assert row.percent == 0.0
    assert pd.isna(row.percent_moe)


def test_suppressed_component_makes_the_indicator_null(lake):
    df = _clean(
        lake, {"B17001_001": (1000, 100), "B17001_002": (-666666666, -222222222)}
    )
    row = df[df.variable == "Below poverty level"].iloc[0]

    # A sentinel must not be summed as a value or yield a partial share.
    assert pd.isna(row.value)
    assert pd.isna(row.percent)
    assert pd.isna(row.percent_moe)
