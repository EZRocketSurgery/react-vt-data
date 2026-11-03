"""
Shared utilities for ACS 5-Year Census B-table scrapers.

Census annotation values (negative sentinels such as -666666666) are missing
data, so a row with any missing component is null rather than a partial sum.

Each tidy row carries its 90% margin of error: Value_MOE for Value and
Percent_MOE (in percentage points) for Percent, derived from the published
margins with the Census Bureau's approximations for sums and proportions.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import requests

from data_collection.census import split_name_col
from data_collection.parallel import pmap
from query.clock import EASTERN_STD_TIME

logger = logging.getLogger(__name__)

# Define API key through the .env file
API_KEY = os.environ.get("CENSUS_API_KEY")
BASE_URL = "https://api.census.gov/data/{year}/acs/acs5"
STATE_FIPS = "50"
STORAGE_LOCATION = "Data/Census/ACS_5"

# The one negative margin of error that is not missing: the estimate is
# controlled to an independent count, so it has no sampling error.
CONTROLLED_MOE = -555555555

# ---------------------------------------------------------------------------
# Geography registry
# ---------------------------------------------------------------------------

ALL_GEOS: dict[str, tuple[str, str]] = {
    "county": ("county:*", f"state:{STATE_FIPS}"),
    "county_subdivision": ("county subdivision:*", f"state:{STATE_FIPS}"),
    "state": (f"state:{STATE_FIPS}", ""),  # Vermont statewide → NAME = "Vermont"
    "national": ("us:1", ""),  # US overall       → NAME = "United States"
}

# Default: all geographies (preserves original scrape order)
GEOS = [(k, *v) for k, v in ALL_GEOS.items()]


MAX_YEAR = datetime.now(EASTERN_STD_TIME).year - 2

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class VarGroup:
    """
    Defines one output row in the tidy dataset per geography/year.

    label:   display name (the Variable column).
    section: category label (the Section column).
    codes:   Census variable codes to SUM for the Value.
    denom:   codes to SUM for the percent denominator; None → Percent is null.
    """

    label: str
    section: str
    codes: list[str]
    denom: list[str] | None = None


# ---------------------------------------------------------------------------
# Census API fetch
# ---------------------------------------------------------------------------


def moe_code(code: str) -> str:
    """The margin-of-error variable for an estimate: B19013_001E -> B19013_001M."""
    return code[:-1] + "M"


def fetch(
    year: int, table: str, codes: list[str], for_clause: str, in_clause: str
) -> pd.DataFrame | None:
    """
    Estimates and margins of error for `codes` from one table at one geography.

    group() returns every estimate and margin in the table, which keeps
    within the API's 50-variable limit (B01001 alone needs 49 estimates).
    Codes the year doesn't publish come back as all-NaN columns.
    """
    params = {
        # group() already includes NAME and GEO_ID.
        "get": f"group({table})",
        "for": for_clause,
        "key": API_KEY,
    }
    if params.get("key") is None:
        logger.error("API key is either missing or set to None.")
        return None

    if in_clause:  # state/national geos have no "in" clause
        params["in"] = in_clause

    try:
        r = requests.get(BASE_URL.format(year=year), params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data[1:], columns=data[0])
        df = df.loc[:, ~df.columns.duplicated()]
    except Exception as e:  # noqa: BLE001 -- skip and keep the run going
        logger.warning("SKIP %s / %s / %s: %s", year, table, for_clause, e)
        return None

    variables = [v for code in codes for v in (code, moe_code(code))]
    if missing := [v for v in variables if v not in df.columns]:
        logger.warning("%s / %s: no %s", year, table, ", ".join(missing))
    # Geography columns (NAME, state, county, ...), without GEO_ID or the
    # table's annotation columns.
    ids = [c for c in df.columns if not c.startswith(f"{table}_") and c != "GEO_ID"]
    df = df.reindex(columns=ids + variables)
    df[variables] = df[variables].apply(pd.to_numeric, errors="coerce")
    df["year"] = year
    return df


# ---------------------------------------------------------------------------
# Tidy computation
# ---------------------------------------------------------------------------


def pct(val: float, total: float) -> float | None:
    try:
        if total and total > 0:
            return round((val / total) * 100, 1)
    except OverflowError:
        logger.warning("OverflowError computing pct(%s, %s)", val, total)
    except FloatingPointError:
        logger.warning("FloatingPointError computing pct(%s, %s)", val, total)
    except ValueError:
        logger.warning("ValueError computing pct(%s, %s)", val, total)
    return None


def estimates(df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Estimates for `codes`: NaN where absent or a Census annotation value
    (https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html).
    No real estimate is negative."""
    est = df.reindex(columns=codes)
    return est.where(est >= 0)


def margins(df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Margins of error for the estimates `codes`: NaN where absent or not
    computable (e.g. -222222222, too few sample cases), 0 where controlled."""
    moe = df.reindex(columns=[moe_code(c) for c in codes])
    return moe.mask(moe == CONTROLLED_MOE, 0).where(lambda m: m >= 0)


def proportion_moe(
    p: pd.Series, num_moe: pd.Series, den: pd.Series, den_moe: pd.Series
) -> pd.Series:
    """
    Margin of error of the proportion p = num / den, where num is a subset of
    den: sqrt(num_moe^2 - p^2 * den_moe^2) / den, or the ratio form (+) when
    the term under the root is negative, per the ACS handbook.

    The ratio form also covers a zero term, which happens when num = den
    (a 100% share): the proportion form would then claim no sampling error
    at all, even for a town of 50 people.
    """
    under = num_moe**2 - p**2 * den_moe**2
    under = under.where(under > 0, num_moe**2 + p**2 * den_moe**2)
    return np.sqrt(under) / den


def sum_moe(est: pd.DataFrame, moe: pd.DataFrame) -> pd.Series:
    """
    Margin of error of a sum of estimates: the root sum of squared margins,
    counting only the largest margin among zero estimates. A zero estimate's
    margin is modeled, and summing many of them overstates the error (Census
    guidance, e.g. the 2017-2021 Variance Replicate Tables documentation).
    """
    sq = moe.to_numpy() ** 2
    zero = est.to_numpy() == 0
    nonzero_sq = np.where(zero, 0, sq).sum(axis=1)
    zero_sq = np.where(zero, sq, 0).max(axis=1, initial=0)
    return pd.Series(np.sqrt(nonzero_sq + zero_sq), index=est.index)


def compute_tidy_generic(df: pd.DataFrame, var_groups: list[VarGroup]) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "year": df["year"],
            "geo_type": df["geo_type"],
            "NAME": df["NAME"],
            "state": df.get("state"),
            "county": df.get("county"),
        }
    )

    def row_sum(codes: list[str]) -> tuple[pd.Series, pd.Series]:
        """The sum of `codes` and its margin of error; each null when any of
        its components is missing, since an incomplete sum is not an
        estimate."""
        est, moe = estimates(df, codes), margins(df, codes)
        value = est.sum(axis=1, min_count=len(codes))
        value_moe = sum_moe(est, moe).where(moe.notna().all(axis=1) & value.notna())
        return value, value_moe

    frames = []
    for var in var_groups:
        value, value_moe = row_sum(var.codes)
        if var.denom:
            denom, denom_moe = row_sum(var.denom)
            percent = (value / denom * 100).round(1).where(denom > 0)
            p = (value / denom).where(denom > 0)
            p_moe = proportion_moe(p, value_moe, denom, denom_moe)
            percent_moe = (100 * p_moe).round(1)
        else:
            percent = percent_moe = None
        if len(var.codes) > 1:
            value_moe = value_moe.round()  # a sum of counts
        frames.append(
            base.assign(
                Section=var.section,
                Variable=var.label,
                Value=value,
                Value_MOE=value_moe,
                Percent=percent,
                Percent_MOE=percent_moe,
            )
        )
    if not frames:
        return pd.DataFrame()

    return pd.concat(frames).sort_index(kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main scrape runner
# ---------------------------------------------------------------------------


def run_acs_b_scrape(
    fetch_specs: dict[str, list[str]],
    var_groups: list[VarGroup],
    year: int = MAX_YEAR,
    geos: list = GEOS,
) -> pd.DataFrame:
    """
    Fetch Census data, compute tidy rows, and return tidy DataFrame.

    Args:
        fetch_specs: dict of {table_name: list of variable codes to fetch}
        var_groups: list of VarGroup objects defining tidy output rows
        year: year to fetch (default = MAX_YEAR)
        geos: list of geographies to fetch (default = GEOS)

    Returns:
        pd.DataFrame: tidy DataFrame of the fetched data
    """
    logger.debug("=== %s ===", year)

    def fetch_geo(geo):
        geo_label, for_clause, in_clause = geo
        merged = None
        for table_name, codes in fetch_specs.items():
            logger.debug("%s / %s / %s...", year, table_name, geo_label)
            df = fetch(year, table_name, codes, for_clause, in_clause)
            if df is None:
                return None
            if merged is None:
                merged = df.copy()
                merged["geo_type"] = geo_label
            else:
                # Build merge key from whichever ID columns are present
                merge_cols = ["NAME"]
                for col in ("state", "county"):
                    if col in merged.columns and col in df.columns:
                        merge_cols.append(col)
                new_var_cols = [c for c in df.columns if c.startswith("B")]
                merged = merged.merge(
                    df[merge_cols + new_var_cols], on=merge_cols, how="left"
                )
        time.sleep(0.01)
        return merged

    all_frames = [m for m in pmap(fetch_geo, geos) if m is not None]

    if not all_frames:
        logger.warning("No data fetched.")
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True, sort=False)
    tidy = compute_tidy_generic(combined, var_groups)
    tidy.sort_values(["year", "geo_type", "NAME"], inplace=True)
    tidy = split_name_col(tidy)  # keeps NAME and adds Jurisdiction + County columns
    tidy.reset_index(drop=True, inplace=True)

    return tidy
