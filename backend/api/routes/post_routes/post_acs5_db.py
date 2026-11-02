import logging

from fastapi import APIRouter, HTTPException

from api.metadata_registry import get_metadata
from api.models import (
    CountyComparisonRequest,
    DPSeriesRequest,
    FilterRequest,
    make_response,
)

# TODO: Simplify / Refactor this script using the new query folder functions
from query.acs5 import (
    QUERY_CONFIG,
    get_acs5_tidy,
    get_acs5_timeseries,
    get_poverty_uninsured_timeseries,
)
from query.core_functions import to_export_geo
from query.county_comparison import comparison_query
from query.county_comparison_indicators import (
    INDICATORS_BY_KEY,
    indicator_options,
)
from query.dp_variable_names import add_variable_names
from query.production_db import get_db

DB = get_db()

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Export sources — merged into /export/sources by post_export.py. Adding a
# new ACS5 tidy dataset or timeseries to QUERY_CONFIG above? Register it here
# too and it appears in the CSV export tool automatically.
# ---------------------------------------------------------------------------


def _load_full_table(table: str):
    """Load an entire ACS5 table for CSV export.

    Adds `County` / `Jurisdiction` columns so every export source shares the
    same filter-column contract.
    """
    return to_export_geo(DB.execute(f'SELECT * FROM "{table}"').df())


EXPORT_SOURCES: dict[str, dict] = {
    "acs5_demographics": {
        "label": "Demographics",
        "group": "Census ACS 5-Year Estimates",
        "description": "Age, sex, race, and population characteristics, by town and year.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP05",
        "loader": lambda: _load_full_table(QUERY_CONFIG["demographics"]["table"]),
    },
    "acs5_economics": {
        "label": "Economics",
        "group": "Census ACS 5-Year Estimates",
        "description": "Employment, income, commute, and industry characteristics, by town and year.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP03",
        "loader": lambda: _load_full_table(QUERY_CONFIG["economics"]["table"]),
    },
    "acs5_housing": {
        "label": "Housing",
        "group": "Census ACS 5-Year Estimates",
        "description": "Housing occupancy, units, value, and cost characteristics, by town and year.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP04",
        "loader": lambda: _load_full_table(QUERY_CONFIG["housing"]["table"]),
    },
    "acs5_education": {
        "label": "Education & Social",
        "group": "Census ACS 5-Year Estimates",
        "description": "Education, language, disability, and citizenship characteristics, by town and year.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP02",
        "loader": lambda: _load_full_table(QUERY_CONFIG["education"]["table"]),
    },
    "acs5_snapshot": {
        "label": "Geography Snapshot Indicators",
        "group": "Census ACS 5-Year Estimates",
        "description": "Key demographic, housing, and economic indicators summarized per town.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP05",
        "loader": lambda: _load_full_table(QUERY_CONFIG["snapshot"]["table"]),
    },
    "acs5_ts_historic_population": {
        "label": "Historic Population by Year",
        "group": "Historical Trends",
        "description": "Vermont municipal population estimates by town and year.",
        "primary_source": "https://www.census.gov/programs-surveys/decennial-census.html",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["demographics"]["timeseries"]["historic_population"]["table"]
        ),
    },
    "acs5_ts_historic_population_change": {
        "label": "Historic Population % Change by Year",
        "group": "Historical Trends",
        "description": "Decade-over-decade percent population change by town and year.",
        "primary_source": "https://www.census.gov/programs-surveys/decennial-census.html",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["demographics"]["timeseries"]["historic_population_change"][
                "table"
            ]
        ),
    },
    "acs5_ts_population_change": {
        "label": "Population % Change by Year (ACS)",
        "group": "Historical Trends",
        "description": "Year-over-year percent population change (ACS 5-year) by town and year.",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP05",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["demographics"]["timeseries"]["population_change"]["table"]
        ),
    },
    "acs5_ts_median_age": {
        "label": "Median Age by Year",
        "group": "Historical Trends",
        "description": "Median age by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP05",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["demographics"]["timeseries"]["median_age"]["table"]
        ),
    },
    "acs5_ts_age_dependency_ratio": {
        "label": "Age Dependency Ratio by Year",
        "group": "Historical Trends",
        "description": "Age dependency ratio by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP05",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["demographics"]["timeseries"]["age_dependency_ratio"]["table"]
        ),
    },
    "acs5_ts_median_home_value": {
        "label": "Median Home Value by Year",
        "group": "Historical Trends",
        "description": "Median owner-occupied home value by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP04",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["housing"]["timeseries"]["median_home_value"]["table"]
        ),
    },
    "acs5_ts_vacancy_rates": {
        "label": "Vacancy Rates by Year",
        "group": "Historical Trends",
        "description": "Homeowner and rental vacancy rates by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP04",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["housing"]["timeseries"]["vacancy_rates"]["table"]
        ),
    },
    "acs5_ts_income_burden": {
        "label": "Housing Cost Burden by Year",
        "group": "Historical Trends",
        "description": "Share of households spending 30% or more of income on housing, by tenure (renters, owners with and without a mortgage, all households), town, and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP04",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["housing"]["timeseries"]["income_burden"]["table"]
        ),
    },
    "acs5_ts_household_income": {
        "label": "Median Household Income by Year",
        "group": "Historical Trends",
        "description": "Median household income by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP03",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["economics"]["timeseries"]["household_income"]["table"]
        ),
    },
    "acs5_ts_per_capita_income": {
        "label": "Per Capita Income by Year",
        "group": "Historical Trends",
        "description": "Per capita income by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP03",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["economics"]["timeseries"]["per_capita_income"]["table"]
        ),
    },
    "acs5_ts_median_earnings": {
        "label": "Median Earnings by Year",
        "group": "Historical Trends",
        "description": "Median earnings for full-time workers by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP03",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["economics"]["timeseries"]["median_earnings"]["table"]
        ),
    },
    "acs5_ts_health_insurance": {
        "label": "Health Insurance Coverage by Year",
        "group": "Historical Trends",
        "description": "Health insurance coverage rates by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP03",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["economics"]["timeseries"]["health_insurance"]["table"]
        ),
    },
    "acs5_ts_housing_units": {
        "label": "Total Housing Units by Year",
        "group": "Historical Trends",
        "description": "Total housing units by town and year (ACS 5-year).",
        "primary_source": "https://data.census.gov/table/ACSDP5Y2023.DP04",
        "loader": lambda: _load_full_table(
            QUERY_CONFIG["housing"]["timeseries"]["housing_units"]["table"]
        ),
    },
}


# TODO: Percents might need to be weighted averages instead of simple averages for statewide aggregation
# TODO: In DB, add an aggregated statewide VT row to each table for easier aggregation requests

# -----------------------------
# CENSUS TIDY FORMAT TABLES
# -----------------------------


# Demographics
@router.post("/load/acs5-db/tidy/demographics")
def tidy_demographics(request: FilterRequest):
    rows = get_acs5_tidy(dataset="demographics", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("demographics"))


# Education
@router.post("/load/acs5-db/tidy/education")
def tidy_education(request: FilterRequest):
    rows = get_acs5_tidy(dataset="education", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("education"))


# Housing
@router.post("/load/acs5-db/tidy/housing")
def tidy_housing(request: FilterRequest):
    rows = get_acs5_tidy(dataset="housing", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("housing"))


# Economics
@router.post("/load/acs5-db/tidy/economics")
def tidy_economics(request: FilterRequest):
    rows = get_acs5_tidy(dataset="economics", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("labor_force"))


# Labor Force
@router.post("/load/acs5-db/tidy/labor-force")
def tidy_labor_force(request: FilterRequest):
    rows = get_acs5_tidy(dataset="labor_force", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("labor_force"))


# -----------------------------
# CENSUS TIMESERIES TABLES
# -----------------------------


##### DEMOGRAPHICS #####
# Age Dependency Ratio
@router.post("/load/acs5-db/timeseries/demographics/age-dependency-ratio")
def get_age_dependency_ratio(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="demographics", dataset="age_dependency_ratio", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("demographics"))


# Median Age
@router.post("/load/acs5-db/timeseries/demographics/median-age")
def get_median_age(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="demographics", dataset="median_age", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("demographics"))


# Historic Population
@router.post("/load/acs5-db/timeseries/demographics/historic-population")
def get_historic_population(request: FilterRequest):
    filters = {key: value for key, value in request.filters.items() if key != "year"}

    rows = get_acs5_timeseries(
        category="demographics",
        dataset="historic_population",
        filters=filters,
    )

    return make_response(data=rows, metadata=get_metadata("demographics"))


# Percent Population Change (Historic, Decade-over-Decade)
@router.post("/load/acs5-db/timeseries/demographics/historic-population-change")
def get_historic_population_change(request: FilterRequest):
    filters = {key: value for key, value in request.filters.items() if key != "year"}

    rows = get_acs5_timeseries(
        category="demographics",
        dataset="historic_population_change",
        filters=filters,
    )

    return make_response(data=rows, metadata=get_metadata("demographics"))


# Percent Population Change (ACS-5, Year-over-Year)
@router.post("/load/acs5-db/timeseries/demographics/population-change")
def get_population_change(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="demographics", dataset="population_change", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("demographics"))


##### ECONOMICS #####
# Health Insurance Coverage
@router.post("/load/acs5-db/timeseries/economics/health-insurance")
def get_health_insurance(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="economics", dataset="health_insurance", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("labor_force"))


# Poverty and Uninsured Rates (DP03 profile), trend context for the Community
# Health report. Filtered by `Location` (the ACS NAME), like the tidy routes.
@router.post("/load/acs5-db/timeseries/economics/poverty-uninsured")
def get_poverty_uninsured(request: FilterRequest):
    names = [str(n) for n in request.filters.get("Location", [])]
    rows = get_poverty_uninsured_timeseries(names)
    return make_response(data=rows, metadata=get_metadata("income"))


# Median Household Income
@router.post("/load/acs5-db/timeseries/economics/median-hh-income")
def get_household_income(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="economics", dataset="household_income", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("income"))


# Per Capita Income
@router.post("/load/acs5-db/timeseries/economics/per-capita-income")
def get_per_capita_income(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="economics", dataset="per_capita_income", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("income"))


# Median Earnings
@router.post("/load/acs5-db/timeseries/economics/median-earnings")
def get_median_earnings(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="economics", dataset="median_earnings", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("income"))


##### HOUSING #####
# Total Housing Units
@router.post("/load/acs5-db/timeseries/housing/total-units")
def get_housing_units(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="housing", dataset="housing_units", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("housing"))


# Median Home Value
@router.post("/load/acs5-db/timeseries/housing/median-home-value")
def get_median_home_value(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="housing", dataset="median_home_value", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("housing"))


# Vacancy Rates
@router.post("/load/acs5-db/timeseries/housing/vacancy-rates")
def get_vacancy_rates(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="housing", dataset="vacancy_rates", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("housing"))


# Housing Cost Burden
@router.post("/load/acs5-db/timeseries/housing/income-burden")
def get_income_burden(request: FilterRequest):
    rows = get_acs5_timeseries(
        category="housing", dataset="income_burden", filters=request.filters
    )
    return make_response(data=rows, metadata=get_metadata("housing_cost_burden"))


# Geography Snapshot Variables
@router.post("/load/acs5-db/tidy/snapshot")
def tidy_snapshot(request: FilterRequest):
    rows = get_acs5_tidy(dataset="snapshot", filters=request.filters)
    return make_response(data=rows, metadata=get_metadata("demographics"))


# ---------------------------------------------------------------------------
# DP-series combined explorer (DP02 / DP03 / DP04 / DP05)
# ---------------------------------------------------------------------------

# Summary fetch for data viewer snapshot


# @router.get("/load/summary")
# def get_summary(location: str):
#     """Return a summary for the given loocation and variable list."""
#     variables = [
#         "Population (ACS)",
#         "Median Household Income",
#         "Median Home Value",
#         "Total Housing Units",
#     ]
#     total_housing_units = DB.execute()

#     return make_response(data=rows, metadata=None)


# TODO: Refactor this code to match zoning schema
@router.get("/load/acs5-db/dp-combined/tree")
def dp_combined_tree():
    """Return the global set of distinct cascade options across all DP tables."""
    rows = DB.execute(
        """--sql
        SELECT DISTINCT
            "table",
            category AS Category,
            subcategory AS Subcategory,
            variable AS Variable,
            measure AS Measure
        FROM acs5_dp_combined_tidy
        ORDER BY "table", Category, Subcategory, Variable, Measure
        """
    ).df()
    return make_response(data=rows, metadata=None)


# Census identity columns (added to the DP tables by the pipeline) to pass
# through when the warehouse has them: a label path can hold several
# observations in a year (issue #106, e.g. owner costs with and without a
# mortgage), and these let the chart draw and name one line for each. Rows
# also get a variable_name where the labels alone don't tell them apart
# (see query/dp_variable_names.py).
DP_IDENTITY_COLUMNS = ("variable_code", "source_label")


def _dp_identity_columns() -> list[str]:
    present = {
        row[0] for row in DB.execute("DESCRIBE acs5_dp_combined_tidy").fetchall()
    }
    return [c for c in DP_IDENTITY_COLUMNS if c in present]


@router.post("/load/acs5-db/dp-combined/series")
def dp_combined_series(request: DPSeriesRequest):
    """Return the annual time-series for a single
    (location, table, Category, Subcategory, Variable, Measure) selection.

    A year can have several rows (see DP_IDENTITY_COLUMNS); all are returned,
    in a stable order so each keeps its place across years: by variable code
    when the warehouse has it, otherwise by load order.
    """
    identity = _dp_identity_columns()
    extra = "".join(f", {c}" for c in identity)
    tiebreak = "variable_code" if "variable_code" in identity else "rowid"
    rows = DB.execute(
        f"""--sql
        SELECT CAST(year AS INTEGER) AS year,
               CAST(value AS DOUBLE) AS Value{extra}
        FROM acs5_dp_combined_tidy
        WHERE name = ?
          AND "table" = ?
          AND category = ?
          AND subcategory = ?
          AND variable = ?
          AND measure = ?
          AND CAST(year AS INTEGER) BETWEEN ? AND ?
        ORDER BY year, {tiebreak}
        """,
        [
            request.name,
            request.table,
            request.category,
            request.subcategory,
            request.variable,
            request.measure,
            request.year_min,
            request.year_max,
        ],
    ).df()
    if "variable_code" in identity:
        rows = add_variable_names(rows)
    return make_response(data=rows, metadata=None)


# ---------------------------------------------------------------------------
# Statewide County Comparison: one indicator, every county + VT + US.
# ---------------------------------------------------------------------------


@router.get("/load/acs5-db/county-comparison/indicators")
def county_comparison_indicators():
    """Every indicator for the picker; available=False ones are coming soon."""
    return make_response(data=indicator_options(), metadata=None)


@router.post("/load/acs5-db/county-comparison")
def county_comparison(request: CountyComparisonRequest):
    """Return {place, geo_type, year, value} for each county, Vermont and the
    United States, every year the indicator has data."""
    indicator = INDICATORS_BY_KEY.get(request.indicator)
    if indicator is None or not indicator.available:
        raise HTTPException(404, f"Unknown indicator: {request.indicator}")
    sql, params = comparison_query(indicator)
    rows = DB.execute(sql, params).df()
    return make_response(
        data=rows,
        # Source and caveats come from the registry; the rest describes the
        # indicator picked.
        metadata={
            **get_metadata("DP TABLES"),
            "label": indicator.label,
            "topic": indicator.topic,
            "description": indicator.description,
            "units": indicator.units,
        },
    )
