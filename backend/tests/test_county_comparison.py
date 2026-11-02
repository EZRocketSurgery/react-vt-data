"""
Tests for the Statewide County Comparison routes, run against a small
in-memory acs5_dp_combined_tidy instead of the warehouse.

Census files one education level under different label paths and measure
names across vintages; the route should stitch them into a single value per
place per year, for the 14 counties plus Vermont and the United States.

Set MCP_LIVE_WAREHOUSE (the repo's real-data test variable, as in
test_mcp_live.py) to also check every built indicator against
real data:

    MCP_LIVE_WAREHOUSE=/abs/path/warehouse.duckdb \\
        uv run pytest tests/test_county_comparison.py
"""

import os

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.metadata_registry import get_metadata
from api.routes.post_routes import post_acs5_db
from query.county_comparison_indicators import INDICATORS, INDICATORS_BY_KEY

EDU = "EDUCATIONAL ATTAINMENT"
ADULTS = "Population 25 years and over"
ESSEX = "Essex County, Vermont"

# (year, name, geo_type, subcategory, variable, measure, value)
ROWS = [
    # 2010-2016 path
    (
        2012,
        ESSEX,
        "county",
        "Percent bachelor's degree or higher",
        "Total",
        "Percent",
        15.5,
    ),
    # 2017 path, with the 2017-2018 measure name
    (
        2017,
        ESSEX,
        "county",
        ADULTS,
        "Percent bachelor's degree or higher",
        "Percent Estimate",
        14.7,
    ),
    # 2018+ path; the count (Estimate) must be ignored
    (2020, ESSEX, "county", ADULTS, "Bachelor's degree or higher", "Percent", 18.4),
    (2020, ESSEX, "county", ADULTS, "Bachelor's degree or higher", "Estimate", 876.0),
    # benchmarks
    (2020, "Vermont", "state", ADULTS, "Bachelor's degree or higher", "Percent", 39.7),
    (
        2020,
        "United States",
        "national",
        ADULTS,
        "Bachelor's degree or higher",
        "Percent",
        32.9,
    ),
    # a town and a different level: neither belongs in the result
    (
        2020,
        "Lunenburg town, Essex County, Vermont",
        "town",
        ADULTS,
        "Bachelor's degree or higher",
        "Percent",
        12.0,
    ),
    (2020, ESSEX, "county", ADULTS, "Bachelor's degree", "Percent", 11.0),
]


INCOME = "INCOME AND BENEFITS (IN {} INFLATION-ADJUSTED DOLLARS)"
MEDIAN_HH = "Median household income (dollars)"

# (year, name, geo_type, category, subcategory, variable, measure, value):
# the category names the year's dollars, and the label path changes in 2013.
INCOME_ROWS = [
    (
        2012,
        ESSEX,
        "county",
        INCOME.format(2012),
        MEDIAN_HH,
        "Total",
        "Estimate",
        41000.0,
    ),
    (
        2020,
        ESSEX,
        "county",
        INCOME.format(2020),
        "Total households",
        MEDIAN_HH,
        "Estimate",
        50000.0,
    ),
    # Census publishes no percent for a median; the empty row must be ignored
    (
        2020,
        ESSEX,
        "county",
        INCOME.format(2020),
        "Total households",
        MEDIAN_HH,
        "Percent",
        None,
    ),
]


POVERTY = (
    "PERCENTAGE OF FAMILIES AND PEOPLE WHOSE INCOME IN THE PAST 12 MONTHS IS "
    "BELOW THE POVERTY LEVEL"
)

# (year, name, geo_type, subcategory, variable, measure, value): children's
# poverty is its own subcategory through 2015, then moves under "All people".
POVERTY_ROWS = [
    (2015, ESSEX, "county", "Under 18 years", "Total", "Percent", 20.0),
    (2017, ESSEX, "county", "All people", "Under 18 years", "Percent Estimate", 18.0),
    (2020, ESSEX, "county", "All people", "Under 18 years", "Percent", 15.0),
    # the all-people rate is a different variable
    (2020, ESSEX, "county", "All people", "Total", "Percent", 10.0),
]


# (year, name, geo_type, subcategory, variable, measure, value): the
# unemployment rate's label path changes in 2013 and again in 2015.
UNEMPLOYMENT_ROWS = [
    (2012, ESSEX, "county", "Percent Unemployed", "Total", "Percent", 9.0),
    (
        2014,
        ESSEX,
        "county",
        "Civilian labor force",
        "Percent Unemployed",
        "Percent",
        8.0,
    ),
    (
        2020,
        ESSEX,
        "county",
        "Civilian labor force",
        "Unemployment Rate",
        "Percent",
        6.0,
    ),
    # unemployed as a share of everyone 16+, not of the labor force
    (
        2012,
        ESSEX,
        "county",
        "In labor force",
        "Civilian labor force: Unemployed",
        "Percent",
        5.0,
    ),
]


def _client(monkeypatch, conn=None) -> TestClient:
    if conn is None:
        conn = duckdb.connect()
        conn.execute(
            """
            CREATE TABLE acs5_dp_combined_tidy (
                year BIGINT, name VARCHAR, geo_type VARCHAR, "table" VARCHAR,
                category VARCHAR, subcategory VARCHAR, variable VARCHAR,
                measure VARCHAR, value DOUBLE
            )
            """
        )
        for year, name, geo, sub, var, measure, value in ROWS:
            conn.execute(
                "INSERT INTO acs5_dp_combined_tidy VALUES (?, ?, ?, 'DP02', ?, ?, ?, ?, ?)",
                [year, name, geo, EDU, sub, var, measure, value],
            )
        for year, name, geo, cat, sub, var, measure, value in INCOME_ROWS:
            conn.execute(
                "INSERT INTO acs5_dp_combined_tidy VALUES (?, ?, ?, 'DP03', ?, ?, ?, ?, ?)",
                [year, name, geo, cat, sub, var, measure, value],
            )
        for year, name, geo, sub, var, measure, value in POVERTY_ROWS:
            conn.execute(
                "INSERT INTO acs5_dp_combined_tidy VALUES (?, ?, ?, 'DP03', ?, ?, ?, ?, ?)",
                [year, name, geo, POVERTY, sub, var, measure, value],
            )
        for year, name, geo, sub, var, measure, value in UNEMPLOYMENT_ROWS:
            conn.execute(
                "INSERT INTO acs5_dp_combined_tidy VALUES (?, ?, ?, 'DP03', ?, ?, ?, ?, ?)",
                [year, name, geo, "EMPLOYMENT STATUS", sub, var, measure, value],
            )
    monkeypatch.setattr(post_acs5_db, "DB", conn)
    app = FastAPI()
    app.include_router(post_acs5_db.router)
    return TestClient(app)


def _rows(client, indicator="edu_bachelors_or_higher"):
    response = client.post(
        "/load/acs5-db/county-comparison", json={"indicator": indicator}
    )
    assert response.status_code == 200, response.text
    return [
        (r["year"], r["place"], r["geo_type"], r["value"])
        for r in response.json()["data"]
    ]


def _expect(got, expected, what):
    __tracebackhide__ = True
    if got != expected:
        pytest.fail(f"{what}\nExpected: {expected}\nGot:      {got}", pytrace=False)


def test_stitches_every_label_path_into_one_series(monkeypatch):
    essex = [
        (y, v) for y, place, _, v in _rows(_client(monkeypatch)) if place == "Essex"
    ]
    _expect(
        essex,
        [(2012, 15.5), (2017, 14.7), (2020, 18.4)],
        "Essex bachelor's or higher by year",
    )


def test_returns_counties_and_benchmarks_but_not_towns(monkeypatch):
    places_2020 = [(p, g) for y, p, g, _ in _rows(_client(monkeypatch)) if y == 2020]
    _expect(
        places_2020,
        [("Essex", "county"), ("United States", "national"), ("Vermont", "state")],
        "2020 places",
    )


def test_metadata_describes_the_indicator(monkeypatch):
    body = (
        _client(monkeypatch)
        .post(
            "/load/acs5-db/county-comparison",
            json={"indicator": "edu_bachelors_or_higher"},
        )
        .json()
    )
    _expect(
        (body["metadata"]["label"], body["metadata"]["units"]),
        ("Bachelor's degree or higher", "percent"),
        "metadata label and units",
    )
    _expect(
        body["metadata"]["source"],
        get_metadata("DP TABLES")["source"],
        "metadata source (from api/metadata_registry.py)",
    )


@pytest.mark.parametrize("indicator", ["disability", "not_a_thing"])
def test_unknown_indicator_is_404(monkeypatch, indicator):
    response = _client(monkeypatch).post(
        "/load/acs5-db/county-comparison", json={"indicator": indicator}
    )
    _expect(
        (response.status_code, response.json()["detail"]),
        (404, f"Unknown indicator: {indicator}"),
        "response",
    )


def test_indicator_list_has_every_topic(monkeypatch):
    options = (
        _client(monkeypatch)
        .get("/load/acs5-db/county-comparison/indicators")
        .json()["data"]
    )
    topics = {}
    for o in options:
        if o["available"]:
            topics[o["topic"]] = topics.get(o["topic"], 0) + 1
    _expect(
        topics,
        {
            "Educational attainment": 9,
            "Disability": 4,
            "Unemployment": 1,
            "Poverty": 9,
            "Income": 1,
        },
        "built indicators per topic",
    )


def test_poverty_joins_headings_across_years(monkeypatch):
    rows = _rows(_client(monkeypatch), "poverty_children")
    _expect(
        [(y, p, v) for y, p, _, v in rows],
        [(2015, "Essex", 20.0), (2017, "Essex", 18.0), (2020, "Essex", 15.0)],
        "Essex child poverty rate by year",
    )


def test_unemployment_joins_label_paths(monkeypatch):
    rows = _rows(_client(monkeypatch), "unemployment_rate")
    _expect(
        [(y, p, v) for y, p, _, v in rows],
        [(2012, "Essex", 9.0), (2014, "Essex", 8.0), (2020, "Essex", 6.0)],
        "Essex unemployment rate by year",
    )


def test_income_joins_yearly_categories_and_label_paths(monkeypatch):
    rows = _rows(_client(monkeypatch), "median_household_income")
    _expect(
        [(y, p, v) for y, p, _, v in rows],
        [(2012, "Essex", 41000.0), (2020, "Essex", 50000.0)],
        "Essex median household income by year",
    )


# ---------------------------------------------------------------------------
# Real-data check: every built indicator has exactly 16 places (14 counties,
# Vermont, United States) in every year it covers, from 2010 (disability
# percents start in 2013).
# ---------------------------------------------------------------------------

WAREHOUSE = os.environ.get("MCP_LIVE_WAREHOUSE")


@pytest.mark.skipif(not WAREHOUSE, reason="Set MCP_LIVE_WAREHOUSE for real-data checks")
@pytest.mark.parametrize("indicator", [i.key for i in INDICATORS if i.available])
def test_warehouse_has_16_places_every_year(monkeypatch, indicator):
    client = _client(monkeypatch, duckdb.connect(WAREHOUSE, read_only=True))
    per_year: dict[int, list[str]] = {}
    for year, place, _, _ in _rows(client, indicator):
        per_year.setdefault(year, []).append(place)
    bad = {y: len(p) for y, p in per_year.items() if len(p) != 16 or len(set(p)) != 16}
    _expect(bad, {}, f"{indicator}: years without exactly 16 distinct places")
    first = 2013 if INDICATORS_BY_KEY[indicator].topic == "Disability" else 2010
    _expect(min(per_year), first, f"{indicator}: first year")
    _expect(max(per_year), 2024, f"{indicator}: last year")
