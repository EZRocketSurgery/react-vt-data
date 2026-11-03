"""
Tests for data_collection/base.py:
  pct(), VarGroup, compute_tidy_generic() and its margins of error, fetch()
"""

import math

import pandas as pd
import pytest

from data_collection import base
from data_collection.base import VarGroup, compute_tidy_generic, pct

# ---------------------------------------------------------------------------
# pct()
# ---------------------------------------------------------------------------


class TestPct:
    def test_normal(self):
        assert pct(50, 200) == 25.0

    def test_rounds_to_one_decimal(self):
        assert pct(1, 3) == 33.3

    def test_zero_denominator_returns_none(self):
        assert pct(10, 0) is None

    def test_none_denominator_returns_none(self):
        assert pct(10, None) is None

    def test_full_percent(self):
        assert pct(100, 100) == 100.0

    def test_zero_numerator(self):
        assert pct(0, 100) == 0.0

    def test_large_values(self):
        result = pct(12546, 14305)
        assert result == pytest.approx(87.7, abs=0.1)


# ---------------------------------------------------------------------------
# VarGroup
# ---------------------------------------------------------------------------


class TestVarGroup:
    def test_basic_construction(self):
        vg = VarGroup("My Label", "My Section", ["B01001_001E"])
        assert vg.label == "My Label"
        assert vg.section == "My Section"
        assert vg.codes == ["B01001_001E"]
        assert vg.denom is None  # default

    def test_with_denom(self):
        vg = VarGroup("Rate", "Labor", ["B23025_002E"], ["B23025_001E"])
        assert vg.denom == ["B23025_001E"]

    def test_multi_code(self):
        vg = VarGroup("Total", "Pop", ["B01001_002E", "B01001_026E"])
        assert len(vg.codes) == 2


# ---------------------------------------------------------------------------
# compute_tidy_generic()
# ---------------------------------------------------------------------------


def _make_df(**extra_cols):
    """Helper to build a minimal raw fetch DataFrame."""
    base = {
        "year": [2020],
        "geo_type": ["county"],
        "NAME": ["Burlington city, Chittenden County, Vermont"],
        "state": ["50"],
        "county": ["007"],
    }
    base.update(extra_cols)
    return pd.DataFrame(base)


class TestComputeTidyGeneric:
    def test_single_group_with_denom(self):
        df = _make_df(B23025_001E=[1000.0], B23025_002E=[650.0])
        groups = [VarGroup("LFP Rate", "Labor", ["B23025_002E"], ["B23025_001E"])]
        result = compute_tidy_generic(df, groups)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["Variable"] == "LFP Rate"
        assert row["Section"] == "Labor"
        assert row["Value"] == 650.0
        assert row["Percent"] == 65.0

    def test_single_group_no_denom(self):
        df = _make_df(B19013_001E=[75000.0])
        groups = [VarGroup("Median HH Income", "Income", ["B19013_001E"])]
        result = compute_tidy_generic(df, groups)

        assert result.iloc[0]["Value"] == 75000.0
        assert result.iloc[0]["Percent"] is None

    def test_multi_code_summed(self):
        """Codes within a group should be summed into one Value."""
        df = _make_df(B01001_002E=[500.0], B01001_026E=[520.0])
        groups = [VarGroup("Total Pop", "Pop", ["B01001_002E", "B01001_026E"])]
        result = compute_tidy_generic(df, groups)

        assert result.iloc[0]["Value"] == 1020.0

    def test_multi_group_produces_one_row_each(self):
        df = _make_df(A=[10.0], B=[5.0], C=[20.0])
        groups = [
            VarGroup("Metric A", "Sec", ["A"]),
            VarGroup("Metric B", "Sec", ["B"]),
        ]
        result = compute_tidy_generic(df, groups)
        assert len(result) == 2
        assert set(result["Variable"]) == {"Metric A", "Metric B"}

    def test_missing_code_makes_value_null(self):
        """An absent code makes the sum null, not a partial sum."""
        df = _make_df(B01001_002E=[500.0])
        groups = [VarGroup("X", "S", ["B01001_002E", "B_MISSING"])]
        result = compute_tidy_generic(df, groups)
        assert pd.isna(result.iloc[0]["Value"])

    def test_sentinel_estimate_is_null(self):
        """-666666666 (too few sample observations) is not a value."""
        df = _make_df(B19013_001E=[-666666666.0])
        groups = [VarGroup("Median HH Income", "Income", ["B19013_001E"])]
        result = compute_tidy_generic(df, groups)
        assert pd.isna(result.iloc[0]["Value"])

    def test_one_sentinel_component_makes_sum_and_percent_null(self):
        df = _make_df(
            B01001_001E=[1000.0], B01001_003E=[40.0], B01001_027E=[-666666666.0]
        )
        groups = [
            VarGroup("Under 5", "Age", ["B01001_003E", "B01001_027E"], ["B01001_001E"])
        ]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert pd.isna(row["Value"])
        assert pd.isna(row["Percent"])

    def test_two_sentinel_components_do_not_sum(self):
        """Two sentinels once summed to -1,333,333,332."""
        df = _make_df(B25003_002E=[-666666666.0], B25003_003E=[-666666666.0])
        groups = [VarGroup("Occupied", "Housing", ["B25003_002E", "B25003_003E"])]
        assert pd.isna(compute_tidy_generic(df, groups).iloc[0]["Value"])

    def test_sentinel_denominator_makes_percent_null(self):
        df = _make_df(B23025_001E=[-999999999.0], B23025_002E=[650.0])
        groups = [VarGroup("LFP Rate", "Labor", ["B23025_002E"], ["B23025_001E"])]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert row["Value"] == 650.0
        assert pd.isna(row["Percent"])

    def test_real_zero_is_kept(self):
        df = _make_df(B01001_001E=[1000.0], B01001_003E=[0.0], B01001_027E=[0.0])
        groups = [
            VarGroup("Under 5", "Age", ["B01001_003E", "B01001_027E"], ["B01001_001E"])
        ]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert row["Value"] == 0
        assert row["Percent"] == 0.0

    def test_passthrough_base_columns(self):
        df = _make_df(B01001_001E=[100.0])
        groups = [VarGroup("Pop", "Pop", ["B01001_001E"])]
        result = compute_tidy_generic(df, groups)
        row = result.iloc[0]
        assert row["year"] == 2020
        assert row["geo_type"] == "county"
        assert row["NAME"] == "Burlington city, Chittenden County, Vermont"
        assert row["state"] == "50"
        assert row["county"] == "007"

    def test_multiple_geographies(self):
        df = pd.DataFrame(
            {
                "year": [2020, 2020],
                "geo_type": ["county", "county_subdivision"],
                "NAME": [
                    "Chittenden County, Vermont",
                    "Burlington city, Chittenden County, Vermont",
                ],
                "state": ["50", "50"],
                "county": ["007", "007"],
                "B01001_001E": [170000.0, 44000.0],
            }
        )
        groups = [VarGroup("Population", "Demo", ["B01001_001E"])]
        result = compute_tidy_generic(df, groups)
        assert len(result) == 2
        assert set(result["geo_type"]) == {"county", "county_subdivision"}


# ---------------------------------------------------------------------------
# Margins of error
# ---------------------------------------------------------------------------


def _rate(num, num_moe, den, den_moe):
    """One proportion row: num of den, each with its margin of error."""
    df = _make_df(
        B23025_001E=[den],
        B23025_001M=[den_moe],
        B23025_002E=[num],
        B23025_002M=[num_moe],
    )
    groups = [VarGroup("LFP Rate", "Labor", ["B23025_002E"], ["B23025_001E"])]
    return compute_tidy_generic(df, groups).iloc[0]


class TestMarginsOfError:
    def test_single_code_passes_its_margin_through(self):
        df = _make_df(B19013_001E=[75000.0], B19013_001M=[4120.0])
        groups = [VarGroup("Median HH Income", "Income", ["B19013_001E"])]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert row["Value_MOE"] == 4120.0
        assert row["Percent_MOE"] is None

    def test_sum_margin_is_root_sum_of_squares(self):
        df = _make_df(
            B01001_002E=[500.0],
            B01001_002M=[30.0],
            B01001_026E=[520.0],
            B01001_026M=[40.0],
        )
        groups = [VarGroup("Total Pop", "Pop", ["B01001_002E", "B01001_026E"])]
        assert compute_tidy_generic(df, groups).iloc[0]["Value_MOE"] == 50.0

    def test_proportion_margin_uses_census_formula(self):
        row = _rate(150.0, 50.0, 1000.0, 100.0)
        # sqrt(MOE_num^2 - p^2 * MOE_den^2) / den, in percentage points
        expected = 100 * math.sqrt(50**2 - 0.15**2 * 100**2) / 1000
        assert row["Percent"] == 15.0
        assert row["Percent_MOE"] == round(expected, 1)

    def test_negative_radicand_falls_back_to_ratio_formula(self):
        row = _rate(900.0, 10.0, 1000.0, 100.0)
        # 10^2 - 0.9^2 * 100^2 < 0, so the + form applies
        expected = 100 * math.sqrt(10**2 + 0.9**2 * 100**2) / 1000
        assert row["Percent_MOE"] == round(expected, 1)

    def test_sum_counts_only_the_largest_zero_estimate_margin(self):
        """Census guidance: zero estimates' margins are modeled, so a sum uses
        only the largest of them instead of all of them."""
        df = _make_df(
            B01001_003E=[0.0],
            B01001_003M=[12.0],
            B01001_004E=[0.0],
            B01001_004M=[15.0],
            B01001_005E=[10.0],
            B01001_005M=[5.0],
        )
        codes = ["B01001_003E", "B01001_004E", "B01001_005E"]
        groups = [VarGroup("Under 15", "Age", codes)]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert row["Value_MOE"] == round(math.sqrt(15**2 + 5**2))

    def test_full_share_margin_is_not_zero(self):
        """num = den makes the proportion form zero; the ratio form applies."""
        row = _rate(40.0, 12.0, 40.0, 12.0)
        assert row["Percent"] == 100.0
        assert row["Percent_MOE"] == round(100 * math.sqrt(12**2 + 12**2) / 40, 1)

    def test_controlled_margin_is_zero(self):
        """-555555555: the estimate is controlled and has no sampling error."""
        row = _rate(150.0, 50.0, 1000.0, -555555555.0)
        assert row["Percent_MOE"] == round(100 * 50 / 1000, 1)

    def test_uncomputable_margin_is_null_but_estimate_stands(self):
        """-222222222: too few sample cases to compute a margin."""
        row = _rate(0.0, -222222222.0, 1000.0, 100.0)
        assert row["Value"] == 0
        assert row["Percent"] == 0.0
        assert pd.isna(row["Value_MOE"])
        assert pd.isna(row["Percent_MOE"])

    def test_missing_margin_column_is_null(self):
        df = _make_df(B19013_001E=[75000.0])
        groups = [VarGroup("Median HH Income", "Income", ["B19013_001E"])]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert row["Value"] == 75000.0
        assert pd.isna(row["Value_MOE"])

    def test_suppressed_estimate_nulls_value_and_margin(self):
        df = _make_df(B19013_001E=[-666666666.0], B19013_001M=[-222222222.0])
        groups = [VarGroup("Median HH Income", "Income", ["B19013_001E"])]
        row = compute_tidy_generic(df, groups).iloc[0]
        assert pd.isna(row["Value"])
        assert pd.isna(row["Value_MOE"])


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_keeps_estimates_margins_and_geography(monkeypatch):
    # Like a real group() response: annotation columns, GEO_ID, then geography.
    header = [
        "B19013_001E",
        "B19013_001EA",
        "B19013_001M",
        "B19013_001MA",
        "GEO_ID",
        "NAME",
        "state",
        "county",
    ]
    rows = [
        ["68854", None, "4120", None, "0500000US50007",
         "Chittenden County, Vermont", "50", "007"],
        ["-666666666", "-", "-222222222", "**", "0500000US50009",
         "Essex County, Vermont", "50", "009"],
    ]  # fmt: skip
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params)
        return _Response([header, *rows])

    monkeypatch.setattr(base, "API_KEY", "test-key")
    monkeypatch.setattr(base.requests, "get", fake_get)

    df = base.fetch(2023, "B19013", ["B19013_001E"], "county:*", "state:50")

    assert calls[0]["get"] == "group(B19013)"
    assert list(df.columns) == [
        "NAME", "state", "county", "B19013_001E", "B19013_001M", "year"
    ]  # fmt: skip
    assert df["B19013_001E"].tolist() == [68854, -666666666]
    assert df["B19013_001M"].tolist() == [4120, -222222222]
    assert (df["year"] == 2023).all()


def test_fetch_fills_unpublished_codes_with_nan(monkeypatch):
    header = ["B19013_001E", "B19013_001M", "GEO_ID", "NAME", "state"]
    rows = [["70000", "500", "0400000US50", "Vermont", "50"]]
    monkeypatch.setattr(base, "API_KEY", "test-key")
    monkeypatch.setattr(
        base.requests, "get", lambda *a, **k: _Response([header, *rows])
    )

    df = base.fetch(2023, "B19013", ["B19013_001E", "B19013_002E"], "state:50", "")

    assert pd.isna(df.loc[0, "B19013_002E"])
    assert pd.isna(df.loc[0, "B19013_002M"])
