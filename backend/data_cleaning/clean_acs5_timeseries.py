"""
**Author**:
    Ian Sargent
**Created**:
    2026-07-16
**Description**:
    Cleaning for the ACS-5 timeseries tables derived from the raw
    `demographics`, `economic`, `housing`, `acs5_economic` and `acs5_housing`
    DuckLake tables:

    Cleaning Steps:
    1. Numeric -6666666 (UNAVALILABLE) turned into NA,
    2. Column "county_subdivision" renamed to "town"
    3. Columns "geoid" and "county_fips" are merged in.

**Run ALL datasets**:
python run_data_cleaning.py clean_acs5_timeseries

**Run only a SUBSET** (from Python):
main(con, ["median_age", "vacancy_rate"])
"""

import sys
from dataclasses import dataclass

import duckdb

from data_cleaning.geo_lookup import (
    UNAVAILABLE,
    acs_geo_sql,
    build_geo_lookups,
    write_table,
)
from data_cleaning.margins import reliability_sql

# Raw identifier columns every base query must expose (see `acs_geo_sql`)
KEYS = "year, NAME, geo_type, state, county"

# Housing cost burden: DP04 subcategory -> tenure label in the Variable column
BURDEN_FIRST_YEAR = 2013
BURDEN_TENURES = {
    "Occupied units paying rent (excluding units where GRAPI cannot be computed)": (
        "Renters"
    ),
    "Housing units with a mortgage (excluding units where SMOCAPI cannot be computed)": (
        "Owners with a mortgage"
    ),
    "Housing unit without a mortgage (excluding units where SMOCAPI cannot be computed)": (
        "Owners without a mortgage"
    ),
}
BURDEN_ALL_HOUSEHOLDS = "All households"
BURDEN_BRACKETS = ["30.0 to 34.9 percent", "35.0 percent or more"]


# A TimeSeries data class for
@dataclass(frozen=True)
class TimeSeries:
    """
    A cleaned time series table to be written to the
    lake.CLEANED DuckLake schema.

    Attributes:
        table: The final lake.CLEANED table name.
        base: Raw SELECT: KEYS plus the measure columns below.
        columns: Measure columns, in output order
        with_county: Include the "county" name column
    """

    table: str
    base: str
    columns: tuple[str, ...]
    with_county: bool = True


def numeric(expr: str) -> str:
    """
    Casting numeric values
    NULL when non-numeric or a census unavailable value.

    Args:
        expr: Column name to cast to numeric. (Typically the "Value" column)

    Returns:
        str: A string sql query line
    """
    return f"NULLIF(TRY_CAST({expr} AS DOUBLE), {UNAVAILABLE})"


def in_list(values: list[str]) -> str:
    """
    Condenses a list of strings into a comma (,) seperated list for SQL syntax.

    Args:
        values: A list of strings. Typically a list of column names

    Returns
        str: A string format of each list item, separated by a comma (,)
    """
    return ", ".join(f"'{v}'" for v in values)


def with_moe(column: str) -> tuple[str, str, str]:
    """A measure column with its margin of error and reliability columns."""
    return (column, f"{column}_moe", f"{column}_reliability")


def single_variable(
    source: str,
    variables: list[str],
    out_col: str,
    value_col: str = "Value",
    keep_variable: bool = False,
    moe_col: str | None = None,
) -> str:
    """
    Filters a RAW lake table to Key, variable (if true), and value columns

    Args:
        source: RAW table schema name from which the time series variable comes from.
        variables: List of variable names to filter dataset to.
        out_col:
        value_col: Column name containing the tracked value over time.
        keep_variable: (T/F) if you want to keep the variable column. Best for timeseries tables tracking multiple variables.
        moe_col: Column holding value_col's 90% margin of error, written as
            `{out_col}_moe` with its `{out_col}_reliability` label (see
            :func:`with_moe`). None leaves both out.

    Returns:
        str: A SQL query which filters the source table to contain the time series variable(s)


    """
    variable = ", Variable" if keep_variable else ""
    moe = (
        f", {numeric(moe_col)} AS {out_col}_moe, "
        f"{reliability_sql(numeric(value_col), numeric(moe_col))} "
        f"AS {out_col}_reliability"
        if moe_col
        else ""
    )
    return f"""--sql
        SELECT {KEYS}{variable}, {numeric(value_col)} AS {out_col}{moe}
        FROM lake.RAW.{source}
        WHERE Variable IN ({in_list(variables)})
        """


def population_change_sql() -> str:
    """
    Year-to-year percentage (%) change in `Population (ACS)` (first year is dropped).

    Returns:
        str: A SQL query that creates the population change table
    """
    return f"""--sql
        SELECT {KEYS}, Population, Pct_Population_Change
        FROM (
            SELECT
                {KEYS},
                Population,
                ROUND(
                    (
                        Population
                        / NULLIF(
                            LAG(Population) OVER (
                                PARTITION BY NAME, geo_type ORDER BY year
                            ),
                            0
                        )
                        - 1
                    ) * 100,
                    1
                ) AS Pct_Population_Change
            FROM (
                SELECT {KEYS}, {numeric("Value")} AS Population
                FROM lake.RAW.demographics
                WHERE Variable = 'Population (ACS)'
            )
        )
        WHERE Pct_Population_Change IS NOT NULL
        """


def age_dependency_ratio_sql() -> str:
    """
    SQL calculating age dependency ratio: (`Under 18` + `65 and over`) / (`18 to 64`) * 100.

    Returns:
        str: A SQL query that creates the age dependency ratio table
    """
    ages = [
        "Under 18",
        "18 to 24",
        "25 to 34",
        "35 to 44",
        "45 to 54",
        "55 to 64",
        "65 to 74",
        "75 Plus",
    ]
    wide = ",\n".join(
        f"MAX(CASE WHEN Variable = '{a}' THEN v END) AS \"{a}\"" for a in ages
    )
    working = " + ".join(f'"{a}"' for a in ages[1:6])

    return f"""--sql
        SELECT
            {KEYS},
            ROUND(
                CASE
                    WHEN ({working}) > 0
                        THEN ("Under 18" + "65 to 74" + "75 Plus")
                            / ({working}) * 100
                END,
                1
            ) AS age_dependency_ratio
        FROM (
            SELECT {KEYS}, {wide}
            FROM (
                SELECT {KEYS}, Variable, {numeric("Value")} AS v
                FROM lake.RAW.demographics
                WHERE Variable IN ({in_list(ages)})
            )
            GROUP BY {KEYS}
        )
        """


def housing_cost_burden_sql(source: str = "lake.RAW.acs5_housing") -> str:
    """
    Share of households spending 30% or more of income on housing, by tenure.

    Renters come from GRAPI and both owner groups from SMOCAPI (DP04). For each
    tenure, the 30.0-34.9% and 35.0%+ household counts (Measure = 'Estimate')
    are summed and divided by the tenure's Total (households where the
    percentage can be computed). Counts are used rather than the published
    percentages because their labels are stable across years (percentages are
    'Percent Estimate' in 2017-2018) and because they can be summed into an
    "All households" row.

    Every negative Census sentinel and any non-numeric value is NULL before
    summing, so two missing brackets never add up to a value. A tenure row is
    NULL unless both brackets and the Total are present exactly once; "All
    households" is NULL unless all three tenures are complete. Percent is NULL
    when the universe is 0 (no households of that tenure).

    Starts in 2013: earlier DP04 layouts differ, and 2010-2012 do not separate
    owners with and without a mortgage.

    Args:
        source: Raw DP04 table (overridable for tests).

    Returns:
        str: SELECT of KEYS, Variable, Value (burdened households),
            Total (universe), and Percent.
    """
    tenure_cases = "\n".join(
        f"WHEN '{subcategory}' THEN '{label}'"
        for subcategory, label in BURDEN_TENURES.items()
    )
    return f"""--sql
        WITH src AS (
            SELECT
                {KEYS},
                CASE Subcategory {tenure_cases} END AS tenure,
                Variable,
                CASE
                    WHEN TRY_CAST(Value AS DOUBLE) >= 0
                        THEN TRY_CAST(Value AS DOUBLE)
                END AS v
            FROM {source}
            WHERE year >= {BURDEN_FIRST_YEAR}
                AND Measure = 'Estimate'
                AND Subcategory IN ({in_list(list(BURDEN_TENURES))})
                AND Variable IN ({in_list(BURDEN_BRACKETS)}, 'Total')
        ),

        by_tenure AS (
            SELECT
                {KEYS},
                tenure,
                SUM(v) FILTER (WHERE Variable <> 'Total') AS burdened,
                COUNT(v) FILTER (WHERE Variable <> 'Total') AS n_brackets,
                COUNT(*) FILTER (WHERE Variable <> 'Total') AS n_bracket_rows,
                MAX(v) FILTER (WHERE Variable = 'Total') AS total,
                COUNT(v) FILTER (WHERE Variable = 'Total') AS n_totals,
                COUNT(*) FILTER (WHERE Variable = 'Total') AS n_total_rows
            FROM src
            GROUP BY {KEYS}, tenure
        ),

        tenure_rows AS (
            SELECT
                {KEYS},
                tenure AS Variable,
                CASE
                    WHEN n_brackets = 2 AND n_bracket_rows = 2 THEN burdened
                END AS "Value",
                CASE WHEN n_totals = 1 AND n_total_rows = 1 THEN total END AS Total
            FROM by_tenure
        ),

        all_rows AS (
            SELECT
                {KEYS},
                '{BURDEN_ALL_HOUSEHOLDS}' AS Variable,
                CASE WHEN COUNT("Value") = 3 THEN SUM("Value") END AS "Value",
                CASE WHEN COUNT(Total) = 3 THEN SUM(Total) END AS Total
            FROM tenure_rows
            GROUP BY {KEYS}
        ),

        combined AS (
            SELECT * FROM tenure_rows
            UNION ALL
            SELECT * FROM all_rows
        )

        SELECT
            {KEYS},
            Variable,
            "Value",
            Total,
            CASE
                WHEN "Value" IS NOT NULL AND Total > 0
                    THEN ROUND(100 * "Value" / Total, 1)
            END AS Percent
        FROM combined
        """


# Define a dictionary of defined TimeSeries objects
CONFIGS: dict[str, TimeSeries] = {
    # Median age
    "median_age": TimeSeries(
        table="acs5Demographics_medianAge_timeseries",
        base=single_variable(
            "demographics", ["Median Age"], "median_age", moe_col="Value_MOE"
        ),
        columns=with_moe("median_age"),
    ),
    # Median Household Income
    "median_hh_income": TimeSeries(
        table="acs5Economics_medianHouseholdIncome_timeseries",
        base=single_variable(
            "economic",
            ["Median Household Income"],
            "median_household_income",
            moe_col="Value_MOE",
        ),
        columns=with_moe("median_household_income"),
    ),
    # Median Home Value
    "median_home_value": TimeSeries(
        table="acs5Housing_medianHomeValue_timeseries",
        base=single_variable(
            "housing", ["Median Home Value"], "median_home_value", moe_col="Value_MOE"
        ),
        columns=with_moe("median_home_value"),
    ),
    # Per Capita Income
    "per_capita_income": TimeSeries(
        table="acs5Economics_perCapitaIncome_timeseries",
        base=single_variable(
            "economic", ["Per Capita Income"], "per_capita_income", moe_col="Value_MOE"
        ),
        columns=with_moe("per_capita_income"),
    ),
    # Total Housing Units
    "total_housing_units": TimeSeries(
        table="acs5Housing_housingUnits_timeseries",
        base=single_variable(
            "housing",
            ["Total Housing Units"],
            "total_housing_units",
            moe_col="Value_MOE",
        ),
        columns=with_moe("total_housing_units"),
    ),
    # Vacancy Rates
    "vacancy_rate": TimeSeries(
        table="acs5Housing_vacancyRates_timeseries",
        base=single_variable(
            "housing",
            ["Homeowner Vacancy Rate", "Rental Vacancy Rate"],
            "percent",
            value_col="Percent",
            keep_variable=True,
            moe_col="Percent_MOE",
        ),
        columns=("Variable", *with_moe("percent")),
    ),
    # Population Change (%)
    "population_change": TimeSeries(
        table="acs5Demographics_populationChange_timeseries",
        base=population_change_sql(),
        columns=("Population", "Pct_Population_Change"),
    ),
    # Age Dependency Ratio
    "age_dependency_ratio": TimeSeries(
        table="acs5Demographics_ageDependencyRatio_timeseries",
        base=age_dependency_ratio_sql(),
        columns=("age_dependency_ratio",),
    ),
    # Health Insurance Coverage (Public, Private, None)
    "health_insurance": TimeSeries(
        table="acs5Economics_healthInsurance_timeseries",
        base=f"""--sql
            SELECT {KEYS}, Variable, {numeric("Value")} AS "Value"
            FROM lake.RAW.acs5_economic
            WHERE Category LIKE '%INSURANCE%'
                AND Subcategory = 'Civilian noninstitutionalized population'
                AND Variable IN (
                    'With health insurance coverage: With public coverage',
                    'With health insurance coverage: With private health insurance',
                    'No health insurance coverage'
                )
                AND Measure = 'Estimate'
            """,
        columns=("Variable", "Value"),
        with_county=False,
    ),
    # Median Earnings (Male, Female, All Workers)
    "median_earnings": TimeSeries(
        table="acs5Economics_medianEarnings_timeseries",
        base=f"""--sql
            SELECT {KEYS}, Subcategory AS Variable, {numeric("Value")} AS "Value"
            FROM lake.RAW.acs5_economic
            WHERE Category LIKE '%INCOME AND BENEFITS%'
                AND Subcategory IN (
                    'Median earnings for male full-time, year-round workers (dollars)',
                    'Median earnings for female full-time, year-round workers (dollars)',
                    'Median earnings for workers (dollars)'
                )
                AND Variable = 'Total'
                AND Measure = 'Estimate'
            """,
        columns=("Variable", "Value"),
        with_county=False,
    ),
    # Housing Cost Burden (30%+ of income on housing), by tenure
    "housing_cost_burden": TimeSeries(
        table="acs5Housing_incomeBurden_timeseries",
        base=housing_cost_burden_sql(),
        columns=("Variable", "Value", "Total", "Percent"),
        with_county=False,
    ),
}


def final_sql(cfg: TimeSeries) -> str:
    """
    Final table schema selection for TimeSeries datasets using the
    :func:`geo_lookup.acs_geo_sql`

    Args:
        cfg: A TimeSeries dataclass object

    Returns:
        str: A SQL query selecting the final table schema including the 'geo_type' column.

    """
    county = ["county"] if cfg.with_county else []
    columns = ["year", "name", "geoid", "county_fips", *county, *cfg.columns]
    select = ", ".join(f'{c} AS "{c}"' if c == "geoid" else c for c in columns)

    return f"""--sql
        SELECT {select}, geo_type
        FROM ({acs_geo_sql(cfg.base)})
        """


def main(con: duckdb.DuckDBPyConnection, names: list[str] | None = None) -> None:
    targets = names or list(CONFIGS)
    unknown = [n for n in targets if n not in CONFIGS]

    if unknown:
        sys.exit(
            f"Unknown dataset(s): {', '.join(unknown)}. Choices: {', '.join(CONFIGS)}"
        )

    build_geo_lookups(con)

    for name in targets:
        cfg = CONFIGS[name]
        write_table(con, cfg.table, final_sql(cfg))
