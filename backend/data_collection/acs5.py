"""
Fetch ACS 5-Year Data Profile tables (DP02-DP05) for Vermont
Geographies: counties + county subdivisions + Vermont statewide + United States
Years: 2009 - Latest published data
Output: one wide table and tidy table. Each tidy row carries its published
90% margin of error as MOE (the M code for an estimate, PM for a percent).

Geography selection
-------------------
Pass --geos on the CLI to scrape only specific geographic levels.
Use --append to merge new rows into existing files instead of overwriting.
"""

import logging
import os
import time
from datetime import datetime

import pandas as pd
import requests

from data_collection.base import ALL_GEOS
from data_collection.census import tidy_census
from data_collection.parallel import pmap
from query.clock import EASTERN_STD_TIME

logger = logging.getLogger(__name__)

# Define API key through the .env file
API_KEY = os.environ.get("CENSUS_API_KEY")


BASE_URL = "https://api.census.gov/data/{year}/acs/acs5/profile"
STATE_FIPS = "50"  # Vermont
TABLES = {
    "DP02": "Social",
    "DP03": "Economic",
    "DP04": "Housing",
    "DP05": "Demographic",
}
ID_VARS = ["year", "geo_type", "table", "NAME", "state", "county"]

MAX_YEAR = datetime.now(EASTERN_STD_TIME).year - 1

YEARS = range(2009, MAX_YEAR)

# Default geos list in (label, for_clause, in_clause) format
GEOS = [(k, *v) for k, v in ALL_GEOS.items()]


def fetch_table(year, table, for_clause, in_clause) -> pd.DataFrame | None:
    params = {
        "get": f"group({table}),NAME",
        "for": for_clause,
        "key": API_KEY,
    }
    if params.get("key") is None:
        logger.error("API key is either missing or set to None.")
        return None

    if in_clause:  # state/national geos have no "in" clause
        params["in"] = in_clause
    try:
        r = requests.get(BASE_URL.format(year=year), params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        # List of DP table columns ['NAME', Variable_Codes, 'GEO_ID', 'state', 'county']
        headers = data[0]
        # Deduplicate column names
        seen = {}
        deduped = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                deduped.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                deduped.append(h)
        df = pd.DataFrame(data[1:], columns=deduped)
        # Add year and table id columns
        df["year"] = year
        df["table"] = table
        return df
    except Exception as e:  # noqa: BLE001 -- skip and keep the run going
        logger.warning("SKIP %s / %s / %s: %s", year, table, for_clause, e)
        return None


def run_acs5_scrape(years: range = YEARS, geos: list = GEOS, append: bool = False):
    """
    Collect ACS 5-year profile tables for multiple years.
    """
    # Collect raw frames per table
    all_frames = {table: [] for table in TABLES}

    def fetch_one(task):
        year, (geo_label, for_clause, in_clause), table = task
        logger.debug("%s / %s / %s...", year, table, geo_label)
        df = fetch_table(year, table, for_clause, in_clause)
        time.sleep(0.01)
        return table, geo_label, df

    tasks = [(y, g, t) for y in years for g in geos for t in TABLES]
    for table, geo_label, df in pmap(fetch_one, tasks):
        if df is not None:
            df["geo_type"] = geo_label
            all_frames[table].append(df)

    results = {}

    # Process each ACS profile table independently
    for table, frames in all_frames.items():
        if not frames:
            logger.warning("No frames for %s, skipping.", table)
            continue

        label = TABLES[table]

        combined = pd.concat(frames, ignore_index=True, sort=False)

        # Key columns to front
        front = [c for c in ID_VARS if c in combined.columns]
        rest = [c for c in combined.columns if c not in front]

        combined = combined[front + rest]
        combined.sort_values(["year", "geo_type", "NAME"], inplace=True)
        combined.reset_index(drop=True, inplace=True)

        # Tidy: run per-year so column labels are year-accurate
        tidy_frames = []
        for year in sorted(combined["year"].unique()):
            year_df = combined[combined["year"] == year]

            if year_df.empty:
                continue

            try:
                tidy_year = tidy_census(year_df, year=year, id_vars=ID_VARS)
                tidy_year["table"] = table
                tidy_frames.append(tidy_year)

            except Exception as e:  # noqa: BLE001 -- skip and keep the run going
                logger.warning("SKIP tidy %s / %s: %s", year, table, e)

        if tidy_frames:
            tidy = pd.concat(
                tidy_frames,
                ignore_index=True,
            )

            results[f"acs5_{label.lower()}"] = tidy

    return results


def collect(years: range = YEARS, geos=GEOS, append=False):
    """
    Collect ACS profile tables and return tidy datasets.
    """

    tables = run_acs5_scrape(
        years=years,
        geos=geos,
        append=append,
    )

    return tables


if __name__ == "__main__":
    df = collect()
