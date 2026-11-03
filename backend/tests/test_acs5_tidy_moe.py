"""
Margins of error and their reliability labels through the ACS B-table
cleaners: RAW tidy rows (as written by data_collection/base.py) to the CLEANED
tidy tables and single-variable series.
"""

import math

import duckdb
import pandas as pd
import pytest

from data_cleaning import clean_acs5_tidy, clean_acs5_timeseries

TOWN = (2023, "county_subdivision", "Middlebury town, Addison County, Vermont")
ROWS = {
    "demographics": [
        ("Age/Sex", "Median Age", 38.2, 1.9, None, None),
        ("Age/Sex", "Population (ACS)", 2000.0, 0.0, 100.0, 0.0),
        # Age bands for the age dependency ratio: 500 dependents to 1,000 of
        # working age.
        ("Age/Sex", "Under 18", 300.0, 40.0, 15.0, 2.0),
        ("Age/Sex", "65 to 74", 200.0, 30.0, 10.0, 1.5),
        ("Age/Sex", "75 Plus", 0.0, 15.0, 0.0, 0.8),
        ("Age/Sex", "18 to 24", 100.0, 20.0, 5.0, 1.0),
        ("Age/Sex", "25 to 34", 200.0, 30.0, 10.0, 1.5),
        ("Age/Sex", "35 to 44", 200.0, 30.0, 10.0, 1.5),
        ("Age/Sex", "45 to 54", 250.0, 40.0, 12.5, 2.0),
        ("Age/Sex", "55 to 64", 250.0, 40.0, 12.5, 2.0),
        ("Race", "Asian", 0.0, 20.0, 0.0, 0.0),
        ("Race", "Native Hawaiian and Other Pacific Islander", 150.0, 80.0, 0.0, 0.0),
    ],
    "economic": [
        ("Income", "Median Household Income", 68854.0, 4120.0, None, None),
        ("Labor Force", "Unemployment Rate", 120.0, 45.0, 3.1, 1.2),
    ],
    "education": [("Education", "Bachelor's Degree", 1500.0, 210.0, 30.0, 4.0)],
    "housing": [
        ("Housing", "Median Home Value", 361200.0, 8938.0, None, None),
        ("Housing", "Rental Vacancy Rate", 25.0, 18.0, 2.6, 1.9),
    ],
}


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
    for table, rows in ROWS.items():
        raw = pd.DataFrame(
            [(*TOWN, "50", "001", *row) for row in rows],
            columns=["year", "geo_type", "NAME", "state", "county", "Section",
                     "Variable", "Value", "Value_MOE", "Percent", "Percent_MOE"],
        )  # fmt: skip
        con.register("raw_df", raw)
        con.execute(f"CREATE TABLE lake.RAW.{table} AS SELECT * FROM raw_df")
        con.unregister("raw_df")
    return con


def test_tidy_tables_keep_both_margins(lake):
    clean_acs5_tidy.main(lake)
    row = lake.execute(
        """
        SELECT geoid, value, value_moe, value_reliability,
            percent, percent_moe, percent_reliability
        FROM lake.CLEANED.acs5_economics_tidy WHERE variable = 'Unemployment Rate'
        """
    ).fetchone()
    # CV = (45 / 1.645) / 120 = 23% and (1.2 / 1.645) / 3.1 = 24%: medium
    assert row == ("5000144350", 120.0, 45.0, "medium", 3.1, 1.2, "medium")


def test_share_whose_margin_rounds_to_zero_is_labeled_by_its_count(lake):
    # Collection rounds percent_moe to 0.1 point, so a tiny share's real
    # margin reads 0.0. Only a controlled count makes that 'high'.
    clean_acs5_tidy.main(lake)
    rows = lake.execute(
        """
        SELECT variable, value_reliability, percent_reliability
        FROM lake.CLEANED.acs5_demographics_tidy
        WHERE percent_moe = 0 ORDER BY variable
        """
    ).fetchall()
    assert rows == [
        ("Asian", "low", "low"),  # zero count with a nonzero margin
        ("Native Hawaiian and Other Pacific Islander", "low", "low"),  # CV 32%
        ("Population (ACS)", "high", "high"),  # controlled: no sampling error
    ]


def test_snapshot_keeps_margins(lake):
    clean_acs5_tidy.main(lake)
    moe = lake.execute(
        """
        SELECT value_moe FROM lake.CLEANED.acs5_snapshot_indicators_tidy
        WHERE variable = 'Median Home Value'
        """
    ).fetchone()
    assert moe == (8938.0,)


def test_single_variable_series_carry_their_margin(lake):
    clean_acs5_timeseries.main(lake, ["median_hh_income", "vacancy_rate"])
    income = lake.execute(
        """
        SELECT median_household_income, median_household_income_moe,
            median_household_income_reliability
        FROM lake.CLEANED.acs5Economics_medianHouseholdIncome_timeseries
        """
    ).fetchone()
    vacancy = lake.execute(
        """
        SELECT Variable, percent, percent_moe, percent_reliability
        FROM lake.CLEANED.acs5Housing_vacancyRates_timeseries
        """
    ).fetchone()
    assert income == (68854.0, 4120.0, "high")  # CV 4%
    assert vacancy == ("Rental Vacancy Rate", 2.6, 1.9, "low")  # CV 44%


def test_age_dependency_ratio_carries_a_ratio_margin(lake):
    clean_acs5_timeseries.main(lake, ["age_dependency_ratio"])
    row = lake.execute(
        """
        SELECT age_dependency_ratio, age_dependency_ratio_moe,
            age_dependency_ratio_reliability
        FROM lake.CLEANED.acs5Demographics_ageDependencyRatio_timeseries
        """
    ).fetchone()
    num_moe = math.sqrt(40**2 + 30**2 + 15**2)
    den_moe = math.sqrt(20**2 + 30**2 + 30**2 + 40**2 + 40**2)
    # sqrt(num_moe^2 + R^2 * den_moe^2) / den, with R = 500 / 1000
    moe = round(100 * math.sqrt(num_moe**2 + 0.5**2 * den_moe**2) / 1000, 1)
    assert row == (50.0, moe, "high")  # CV 8%


def test_dp_series_carry_their_published_margins(lake):
    raw = pd.DataFrame(
        [
            (*TOWN, "50", "001", "SELECTED ECONOMIC CHARACTERISTICS: HEALTH INSURANCE",
             "Civilian noninstitutionalized population", "No health insurance coverage",
             "Estimate", "300", "45"),
            (*TOWN, "50", "001", "INCOME AND BENEFITS",
             "Median earnings for workers (dollars)", "Total", "Estimate", "41250",
             "-555555555"),
        ],
        columns=["year", "geo_type", "NAME", "state", "county", "Category",
                 "Subcategory", "Variable", "Measure", "Value", "MOE"],
    )  # fmt: skip
    lake.register("raw_df", raw)
    lake.execute("CREATE TABLE lake.RAW.acs5_economic AS SELECT * FROM raw_df")
    clean_acs5_timeseries.main(lake, ["health_insurance", "median_earnings"])

    uninsured = lake.execute(
        """
        SELECT "Value", "Value_MOE", "Value_Reliability"
        FROM lake.CLEANED.acs5Economics_healthInsurance_timeseries
        """
    ).fetchone()
    earnings = lake.execute(
        """
        SELECT "Value", "Value_MOE", "Value_Reliability"
        FROM lake.CLEANED.acs5Economics_medianEarnings_timeseries
        """
    ).fetchone()
    assert uninsured == (300.0, 45.0, "high")  # CV 9%
    assert earnings == (41250.0, 0.0, "high")  # controlled
