"""
Tests for data_collection/census.py: the DP profile tidy step keeps each
estimate's published margin of error as an MOE column.
"""

import pandas as pd

from data_collection.acs5 import ID_VARS
from data_collection.census import merge_census_cols, relabel_census_cols

LABEL = "INCOME AND BENEFITS!!Total households!!Median household income (dollars)"


def _tidy(**codes) -> pd.DataFrame:
    # The profile variables.json lists only E and PE codes.
    labels = pd.DataFrame(
        {
            "Name": ["DP03_0062E", "DP03_0062PE"],
            "Label": [f"Estimate!!{LABEL}", f"Percent!!{LABEL}"],
        }
    )
    # Like a group() response: annotation columns, GEO_ID and geography.
    wide = pd.DataFrame(
        {
            "year": [2023],
            "geo_type": ["county"],
            "table": ["DP03"],
            "NAME": ["Addison County, Vermont"],
            "state": ["50"],
            "county": ["001"],
            "GEO_ID": ["0500000US50001"],
            **{code: [value] for code, value in codes.items()},
        }
    )
    tidy = merge_census_cols(relabel_census_cols(labels), wide, ID_VARS)
    return tidy.set_index("Variable_Code")


def test_estimates_and_percents_carry_their_margin():
    tidy = _tidy(
        DP03_0062E="85000",
        DP03_0062EA=None,
        DP03_0062M="3100",
        DP03_0062MA=None,
        DP03_0062PE="-888888888",
        DP03_0062PM="-888888888",
    )

    assert sorted(tidy.index) == ["DP03_0062E", "DP03_0062PE"]
    assert tidy.loc["DP03_0062E", ["Value", "MOE"]].tolist() == ["85000", "3100"]
    assert tidy.loc["DP03_0062PE", "MOE"] == "-888888888"
    assert tidy.loc["DP03_0062E", "Measure"] == "Estimate"


def test_missing_margin_is_null():
    tidy = _tidy(DP03_0062E="85000", DP03_0062PE="-888888888")

    assert tidy.loc["DP03_0062E", "Value"] == "85000"
    assert pd.isna(tidy.loc["DP03_0062E", "MOE"])
