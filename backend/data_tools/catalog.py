"""Allowlisted datasets and discovery shared by MCP and native agent tools.

Importing this module never opens a database. Callers own connections, timeouts,
and result-size limits; discovery SQL never accepts a caller-supplied identifier.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Dataset:
    id: str
    label: str
    description: str
    table: str
    source_url: str
    source_name: str
    caveats: tuple[str, ...] = ()
    kind: Literal["tidy", "wide", "records", "dp"] = "records"
    year_column: str | None = None
    name_column: str | None = None
    geo_type_column: str | None = None
    id_column: str | None = None
    fixed_geo_type: str | None = None
    variable_columns: tuple[str, ...] = ()
    value_columns: dict[str, str] | None = None
    filter_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.value_columns is None:
            object.__setattr__(self, "value_columns", {})


ACS_URL = "https://www.census.gov/programs-surveys/acs/data.html"
_ACS_PERIOD = (
    "ACS five-year estimates: year is the final year of the five-year period, "
    "not a single-year count. Adjacent periods overlap."
)
_ACS_NULLS = (
    "Unavailable Census values and non-finite numbers are returned as null; "
    "null does not mean zero. Counts, percentages, and medians are separate measures."
)
ACS_CAVEATS = (
    _ACS_PERIOD,
    (
        "Margins of error are not included in these cleaned tables. Differences "
        "alone do not establish statistical significance."
    ),
    _ACS_NULLS,
)
# For tables that carry *_moe columns.
ACS_MOE_CAVEATS = (
    _ACS_PERIOD,
    (
        "Columns ending in _moe are 90% margins of error: the estimate plus or "
        "minus its margin is the 90% confidence interval; percent_moe is in "
        "percentage points. Margins of sums and percentages are Census "
        "approximations. For estimates from periods that do not overlap (such as "
        "2018 and 2023), or from separate places in the same period, a difference "
        "larger than the square root of the sum of their squared margins is "
        "significant at 90% confidence. That test does not apply to adjacent "
        "years, whose five-year periods share four years, or to a place and an "
        "area that contains it. A null margin means the Census could not compute one. Each margin has a "
        "reliability label (high, medium, low) from the coefficient of variation, "
        "CV = (moe / 1.645) / estimate: under 15% high, over 30% low; a zero "
        "estimate with a nonzero margin is low. Treat low-reliability estimates "
        "as rough, especially for small towns."
    ),
    _ACS_NULLS,
)
ZONING_URL = "https://geodata.vermont.gov/datasets/VCGI::vt-zoning-areas/about"
ZONING_CAVEATS = (
    (
        "A mapped inventory, not a legal determination. bylaw_date is the bylaw "
        "date recorded in the inventory."
    ),
    (
        "Overlay districts can overlap base districts. Acreage sums are not "
        "unique land area; some districts have missing geographic identifiers."
    ),
    (
        "geoid can be missing or conflict with the municipality name. Canonical "
        "location selection uses unambiguous names and reports the discrepancy; "
        "source IDs are preserved. Notes are inventory commentary, not ordinance text."
    ),
    (
        "district_type differs between tables: info maps Primarily Residential to "
        "Residential, Mixed with Residential to Mixed, and Overlay not Affecting Use "
        "to Overlay; wide retains source labels. Join districts on object_id."
    ),
    "Geometry is intentionally excluded from tool results.",
)
WASTEWATER_URL = (
    "https://verso-uvm.github.io/Wastewater-Infrastructure-Mapping/data.html"
)
INFRA_CAVEATS = (
    (
        "Inventory coverage and source dates vary; absence is not evidence that "
        "infrastructure or service does not exist."
    ),
    "Geometry is intentionally excluded from tool results.",
)


def _acs_tidy(key: str, label: str, description: str, table: str) -> Dataset:
    return Dataset(
        key,
        label,
        description,
        table,
        ACS_URL,
        "U.S. Census Bureau, American Community Survey five-year estimates",
        ACS_MOE_CAVEATS,
        "tidy",
        "year",
        "name",
        "geo_type",
        variable_columns=("section", "variable"),
        value_columns={
            "value": "varies by variable",
            "value_moe": "varies by variable",
            "percent": "percent",
            "percent_moe": "percentage points",
        },
        filter_columns=(
            "year",
            "name",
            "geo_type",
            "county",
            "county_fips",
            "geoid",
            "section",
            "variable",
            "value_reliability",
            "percent_reliability",
        ),
    )


def _acs_series(
    key: str,
    label: str,
    table: str,
    values: dict[str, str],
    *,
    dimensions: tuple[str, ...] = (),
    description: str | None = None,
    historic: bool = False,
    county: bool = True,
    caveats: tuple[str, ...] = (),
) -> Dataset:
    # ACS series carry the standard geoid/county_fips identifiers; `county` is
    # False for tables built with `with_county=False` in clean_acs5_timeseries.
    identifiers = ("geoid", "county_fips") + (("county",) if county else ())
    # Series with <measure>_moe columns also carry <measure>_reliability.
    margins = [c.removesuffix("_moe") for c in values if c.endswith("_moe")]
    acs_caveats = ACS_MOE_CAVEATS if margins else ACS_CAVEATS
    return Dataset(
        f"acs5_ts_{key}",
        label,
        description or f"{label} by geography and year.",
        table,
        "https://www.census.gov/programs-surveys/decennial-census.html"
        if historic
        else ACS_URL,
        "VCGI historic population, from the U.S. decennial census"
        if historic
        else "U.S. Census Bureau, ACS five-year estimates",
        (
            ("Historic boundaries and coverage can change between censuses.",)
            if historic
            else acs_caveats
        )
        + caveats,
        "tidy" if dimensions else "wide",
        "year",
        "name",
        "geo_type",
        "geoid" if historic else None,
        variable_columns=dimensions,
        value_columns=values,
        filter_columns=("year", "name", "geo_type")
        + dimensions
        + (("geoid", "county_fips", "County") if historic else identifiers)
        + tuple(f"{measure}_reliability" for measure in margins),
    )


_ZONING_COMMON = (
    "object_id",
    "county",
    "county_fips",
    "rpc",
    "town",
    "geoid",
    "district_name",
    "abbreviated_district_name",
    "district_type",
    "bylaw_date",
    "elderly_housing_district",
    "district_mapped",
    "overlay_district",
    "base_density",
    "affordable_housing_district",
    "notes",
)
_ZONING_STANDARDS = {
    "F1F": (
        "Allowance",
        "Front_Setback",
        "Side_Setback",
        "Rear_Setback",
        "Frontage",
        "Max_Height",
        "Max_Stories",
        "Min_Lot_Size",
        "Max_Lot_Building_Coverage",
        "Max_Lot_Impervious_Coverage",
        "Min_Parking_Spaces",
    ),
    "F2F": (
        "Allowance",
        "Front_Setback",
        "Side_Setback",
        "Rear_Setback",
        "Frontage",
        "Max_Density",
        "Max_Height",
        "Max_Stories",
        "Min_Lot_Size",
        "Max_Lot_Building_Coverage",
        "Max_Lot_Impervious_Coverage",
        "Min_Parking_Spaces_per_1BR",
        "Min_Parking_Spaces_per_mult_BR",
        "Elderly_Housing_Only",
        "Affordable_Housing_Only",
    ),
    "F3F": (
        "Allowance",
        "Front_Setback",
        "Side_Setback",
        "Rear_Setback",
        "Frontage",
        "Max_Density",
        "Max_Height",
        "Max_Stories",
        "Min_Lot_Size",
        "Max_Lot_Building_Coverage",
        "Max_Lot_Impervious_Coverage",
        "Min_Parking_Spaces_per_1BR",
        "Min_Parking_Spaces_per_mult_BR",
        "Elderly_Housing_Only",
        "Affordable_Housing_Only",
        "Proximity_to_Public_Transit_Required",
        "Connection_to_Sewage/Water_Required",
    ),
    "F4F": (
        "Allowance",
        "Front_Setback",
        "Side_Setback",
        "Rear_Setback",
        "Frontage",
        "Max_Density",
        "Max_Height",
        "Max_Stories",
        "Min_Lot_Size",
        "Max_Lot_Building_Coverage",
        "Max_Lot_Impervious_Coverage",
        "Min_Parking_Spaces_per_1BR",
        "Min_Parking_Spaces_per_mult_BR",
        "Elderly_Housing_Only",
        "Affordable_Housing_Only",
        "Proximity_to_Public_Transit_Required",
        "Connection_to_Sewage/Water_Required",
    ),
    "ADU": (
        "Allowance",
        "Elderly_Housing_Only",
        "Max_Size_as_Percent_of_Primary_Strcture",
        "Max_Size_in_sq_ft",
        "Min_Lot_Size",
        "Max_Bedrooms",
        "Min_Parking_Spaces",
        "Owner_Occupancy_Required",
        "Renter_Occupancy_Prohibited",
        "Employee_or_Family_Occupancy_Required",
        "Restricted_to_Primary_Structure",
    ),
    "Affordable_Housing": (
        "Allowance",
        "Elderly_Only",
        "Min_Lot_Size",
        "Max_Density",
        "Min_Parking_Spaces_per_mult_BR",
        "Max_Units_per_Building",
        "Min_Parking_Spaces_per_1BR",
    ),
    "PRD": (
        "Allowance",
        "Max_Density",
        "Max_Units",
        "Min_Lot_Size",
        "Mobile_or_Manufactured_Home_Park",
    ),
    "PUD": (
        "Allowance",
        "Required_with_Subdivision",
        "Requires_Land_Conservation",
        "Threshold_Number",
    ),
}
_ZONING_COLUMNS = tuple(
    f"{prefix}_{suffix}".lower()
    for prefix, suffixes in _ZONING_STANDARDS.items()
    for suffix in suffixes
)


def _zoning_unit(column: str) -> str:
    # Lot-size acres are documented in api/schema.json. Other ambiguous fields
    # keep their source units instead of inventing a conversion.
    if "min_lot_size" in column:
        return "acres"
    if "setback" in column or "frontage" in column or "max_height" in column:
        return "feet"
    if "coverage" in column or "as_percent" in column:
        return "percent"
    if "sq_ft" in column:
        return "square feet"
    if "density" in column:
        return "source-defined density"
    return "count"


def _zoning_numeric(column: str) -> bool:
    return any(
        token in column
        for token in (
            "setback",
            "frontage",
            "max_height",
            "max_stories",
            "min_lot_size",
            "coverage",
            "min_parking_spaces",
            "max_density",
            "max_size_",
            "max_bedrooms",
            "max_units",
            "threshold_number",
        )
    )


_DATASET_LIST = [
    _acs_tidy(
        "acs5_demographics",
        "Demographics",
        "Age, sex, race and population.",
        "acs5_demographics_tidy",
    ),
    _acs_tidy(
        "acs5_economics",
        "Economics",
        "Income and labor-force participation.",
        "acs5_economics_tidy",
    ),
    _acs_tidy(
        "acs5_housing",
        "Housing",
        "Housing units, values and vacancy rates.",
        "acs5_housing_tidy",
    ),
    _acs_tidy(
        "acs5_education",
        "Education and social",
        "Educational attainment.",
        "acs5_education_tidy",
    ),
    _acs_tidy(
        "acs5_snapshot",
        "Geography snapshot indicators",
        "Selected population, age, housing, income and employment indicators.",
        "acs5_snapshot_indicators_tidy",
    ),
    _acs_series(
        "historic_population",
        "Historic population",
        "VCGI_historicPopulation_timeseries",
        {"Population": "people"},
        historic=True,
    ),
    _acs_series(
        "historic_population_change",
        "Historic population change",
        "VCGI_historicPopulation_pctChange_timeseries",
        {"Population": "people", "Pct_Population_Change": "percent change"},
        historic=True,
        caveats=(
            (
                "Change is relative to the previous available observation, "
                "not necessarily an annual change."
            ),
        ),
    ),
    _acs_series(
        "population_change",
        "ACS population and change",
        "acs5Demographics_populationChange_timeseries",
        {"Population": "people", "Pct_Population_Change": "percent change"},
    ),
    _acs_series(
        "median_age",
        "Median age",
        "acs5Demographics_medianAge_timeseries",
        {"median_age": "years", "median_age_moe": "years"},
    ),
    _acs_series(
        "age_dependency_ratio",
        "Age dependency ratio",
        "acs5Demographics_ageDependencyRatio_timeseries",
        {"age_dependency_ratio": "dependents per 100 working-age people"},
    ),
    _acs_series(
        "median_home_value",
        "Median home value",
        "acs5Housing_medianHomeValue_timeseries",
        {
            "median_home_value": "USD (year-specific dollars)",
            "median_home_value_moe": "USD (year-specific dollars)",
        },
    ),
    _acs_series(
        "vacancy_rates",
        "Vacancy rates",
        "acs5Housing_vacancyRates_timeseries",
        {"percent": "percent", "percent_moe": "percentage points"},
        dimensions=("Variable",),
    ),
    _acs_series(
        "income_burden",
        "Housing cost burden by tenure",
        "acs5Housing_incomeBurden_timeseries",
        {"Value": "households", "Total": "households", "Percent": "percent"},
        dimensions=("Variable",),
        county=False,
        description="Households spending at least 30% of household income on "
        "housing, by tenure: Renters (gross rent, GRAPI), Owners with a "
        "mortgage and Owners without a mortgage (owner costs, SMOCAPI), and "
        "All households (the three summed). Value is cost-burdened "
        "households, Total is households where the percentage can be "
        "computed, and Percent is Value / Total. Covers 2013 onward.",
    ),
    _acs_series(
        "household_income",
        "Median household income",
        "acs5Economics_medianHouseholdIncome_timeseries",
        {
            "median_household_income": "USD (year-specific dollars)",
            "median_household_income_moe": "USD (year-specific dollars)",
        },
    ),
    _acs_series(
        "per_capita_income",
        "Per capita income",
        "acs5Economics_perCapitaIncome_timeseries",
        {
            "per_capita_income": "USD (year-specific dollars)",
            "per_capita_income_moe": "USD (year-specific dollars)",
        },
    ),
    _acs_series(
        "median_earnings",
        "Median earnings",
        "acs5Economics_medianEarnings_timeseries",
        {"Value": "USD (year-specific dollars)"},
        dimensions=("Variable",),
        county=False,
    ),
    _acs_series(
        "health_insurance",
        "Health insurance coverage",
        "acs5Economics_healthInsurance_timeseries",
        {"Value": "people"},
        dimensions=("Variable",),
        county=False,
        description="People by health insurance coverage category.",
    ),
    _acs_series(
        "housing_units",
        "Housing units",
        "acs5Housing_housingUnits_timeseries",
        {
            "total_housing_units": "housing units",
            "total_housing_units_moe": "housing units",
        },
    ),
    Dataset(
        "acs5_dp",
        "ACS detailed data profiles",
        "DP02–DP05 social, economic, "
        "housing and demographic profiles, with explicit measure types.",
        "acs5_dp_combined_tidy",
        ACS_URL,
        "U.S. Census Bureau, ACS data profiles",
        ACS_MOE_CAVEATS
        + (
            (
                "Estimate and percentage labels vary across source years. "
                "Discover measure values before selecting a series."
            ),
            (
                "Some source rows labelled Percent or Percent Estimate contain totals "
                "rather than percentages. Total-line units are unverified; do not "
                "interpret or aggregate them as percentages."
            ),
            (
                "Some profile rows share identical selectors but represent different "
                "source observations, notably historical mortgage/non-mortgage costs. "
                "Rows are preserved; do not arbitrarily deduplicate or sum them. "
                "Each row also carries the original variable_code and source_label from "
                "the Census API, which disambiguate colliding selectors within a year; "
                "there is no crosswalk yet resolving them into one series across years."
            ),
        ),
        "dp",
        "year",
        "name",
        variable_columns=("table", "category", "subcategory", "variable", "measure"),
        # moe is value's published 90% margin of error; reliability labels it.
        value_columns={
            "value": "varies by variable and measure",
            "moe": "same as value",
        },
        filter_columns=(
            "name",
            "geo_type",
            "geoid",
            "county_fips",
            "table",
            "category",
            "subcategory",
            "variable",
            "measure",
            "variable_code",
            "source_label",
            "year",
            "reliability",
        ),
    ),
    Dataset(
        "qcew_employment_by_sector",
        "Employment by sector (QCEW)",
        "Quarterly county employment by industry sector and a stored rolling average.",
        "qcew_sectorEmployment_timeseries",
        "https://www.bls.gov/cew/",
        "U.S. Bureau of Labor Statistics, Quarterly Census of Employment and Wages",
        (
            (
                "Covered employment is a job count, not employed residents. Industry totals "
                "can overlap; do not sum an all-industry total with its components."
            ),
            (
                "employment_4qma is a stored rolling average, not a guaranteed mean "
                "of four consecutive observed quarters. The current pipeline allows "
                "fewer than four observations, skips missing or suppressed values "
                "in the mean, and can carry averages forward through gaps."
            ),
            (
                "The current employment_4qma calculation runs separately for each "
                "county/year and restarts at year boundaries. It uses available "
                "rows without checking for consecutive quarters. Historical warehouse "
                "calculation details are not recorded; query filters do not recompute "
                "the stored averages."
            ),
        ),
        "tidy",
        "year",
        "county",
        fixed_geo_type="county",
        variable_columns=("sector",),
        value_columns={
            "employment": "jobs",
            "employment_4qma": "jobs (stored rolling average; see caveats)",
        },
        filter_columns=(
            "county",
            "county_fips",
            "geoid",
            "year",
            "quarter",
            "quarter_label",
            "sector",
        ),
    ),
    Dataset(
        "zoning_districts",
        "Zoning districts",
        "District inventory, classification, bylaw date and acreage; geometry omitted.",
        "VersoZoning_info",
        ZONING_URL,
        "VCGI / VERSO Vermont zoning inventory",
        ZONING_CAVEATS,
        name_column="town",
        id_column="geoid",
        fixed_geo_type="county_subdivision",
        value_columns={"base_density": "source-defined density", "acres": "acres"},
        filter_columns=_ZONING_COMMON + ("acres",),
    ),
    Dataset(
        "zoning_bylaws",
        "Zoning bylaw standards",
        "Use allowances and dimensional standards for each district and housing form.",
        "VersoZoning_wide",
        ZONING_URL,
        "VCGI / VERSO Vermont zoning inventory",
        ZONING_CAVEATS,
        name_column="town",
        id_column="geoid",
        fixed_geo_type="county_subdivision",
        value_columns={"base_density": "source-defined density"}
        | {
            column: _zoning_unit(column)
            for column in _ZONING_COLUMNS
            if _zoning_numeric(column)
        },
        filter_columns=_ZONING_COMMON + _ZONING_COLUMNS,
    ),
    Dataset(
        "wastewater_service_areas",
        "Wastewater service areas",
        "Service areas and their systems, owners, and treatment facilities.",
        "VersoWastewater_serviceAreas_info",
        WASTEWATER_URL,
        "VERSO Wastewater Infrastructure Mapping",
        INFRA_CAVEATS,
        name_column="town",
        id_column="geoid",
        fixed_geo_type="county_subdivision",
        filter_columns=(
            "area_id",
            "town_id",
            "treatment_facility",
            "system_name",
            "system_owner",
            "town",
            "county",
            "county_fips",
            "geoid",
            "rpc",
        ),
    ),
    Dataset(
        "wastewater_treatment_facilities",
        "Wastewater treatment facilities",
        "Facility inventory and reported design hydraulic capacity.",
        "VersoWastewater_treatmentFacilities_info",
        WASTEWATER_URL,
        "VERSO Wastewater Infrastructure Mapping",
        INFRA_CAVEATS,
        name_column="town",
        id_column="geoid",
        fixed_geo_type="county_subdivision",
        value_columns={"design_hydraulic_capacity_mgd": "million gallons per day"},
        filter_columns=(
            "facility_id",
            "design_hydraulic_capacity_mgd",
            "septage_received",
            "ww_inventory_url",
            "facility_name",
            "town",
            "county",
            "county_fips",
            "geoid",
            "rpc",
        ),
    ),
    Dataset(
        "wastewater_treatment_facility_permits",
        "Wastewater facility permits",
        "NPDES permits, indexed by the facility ID used in the facility inventory.",
        "VersoWastewater_treatmentFacilitiesPermits_info",
        WASTEWATER_URL,
        "VERSO Wastewater Infrastructure Mapping",
        INFRA_CAVEATS,
        filter_columns=(
            "Facility_ID",
            "PermitID",
            "PermitRecordID",
            "NPDESPermitNumber",
            "PermitLink",
            "PermitteeName",
        ),
    ),
    Dataset(
        "wastewater_soil_suitability",
        "Septic soil suitability",
        "Soil suitability polygons represented by classification and acreage.",
        "VersoWastewater_soilSuitability_info",
        "https://github.com/VERSO-UVM/Vermont-Livability-Map",
        "VERSO Vermont Livability Map",
        INFRA_CAVEATS
        + (
            (
                "Suitability is a mapped screening assessment, not a site-specific "
                "engineering or permitting determination."
            ),
        ),
        name_column="town",
        fixed_geo_type="county_subdivision",
        value_columns={"acres": "acres"},
        filter_columns=(
            "ogc_fid",
            "suitability",
            "town",
            "county",
            "county_fips",
            "geoid",
            "rpc",
            "acres",
        ),
    ),
    Dataset(
        "wastewater_stormwater_management",
        "Stormwater management areas",
        "Permitted stormwater system records with type and status.",
        "VersoWastewater_stormwaterManagement_info",
        WASTEWATER_URL,
        "VERSO Wastewater Infrastructure Mapping",
        INFRA_CAVEATS,
        name_column="town",
        id_column="geoid",
        fixed_geo_type="county_subdivision",
        filter_columns=(
            "global_id",
            "type",
            "status",
            "geoid",
            "town",
            "county",
            "county_fips",
            "rpc",
        ),
    ),
    *[
        Dataset(
            f"cdc_places_{level}",
            f"Health measures by {level} (CDC PLACES)",
            "Model-based health prevalence estimates, confidence limits, and "
            "explicit crude/age-adjusted measure types.",
            f"cdc_places_{level}",
            "https://www.cdc.gov/places/",
            "U.S. Centers for Disease Control and Prevention, PLACES",
            (
                (
                    "Model-based estimates, not individual clinical records. Do not mix "
                    "crude and age-adjusted prevalence. Year is the observation year "
                    "recorded in the source, not necessarily the release year."
                ),
                (
                    "natl_pct is a precomputed derived rank on a 0–1 scale, not "
                    "prevalence or a verified national percentile. The current "
                    "project pipeline collects Vermont only and ranks by measure "
                    "without separating years or crude/age-adjusted prevalence types."
                ),
                (
                    "The reference population used for stored natl_pct values is not "
                    "recorded. Query filters do not recompute these ranks. Do not use "
                    "them as verified national benchmarks; report data_value with its "
                    "year and prevalence type."
                ),
            ),
            "tidy",
            "year",
            None,
            id_column="geoid",
            fixed_geo_type=level,
            variable_columns=("category", "measure", "data_value_type"),
            value_columns={
                "data_value": "percent",
                "low_confidence_limit": "percent",
                "high_confidence_limit": "percent",
                "natl_pct": "derived percentile (0–1; see caveats)",
            },
            filter_columns=(
                "year",
                "geo_type",
                "county",
                "county_fips",
                "category",
                "measure",
                "data_value_unit",
                "data_value_type",
                "geoid",
                "category_id",
                "measure_id",
                "data_value_type_id",
                "short_question_text",
                "sme_highlight",
                "bin",
            ),
        )
        for level in ("county", "tract")
    ],
    Dataset(
        "ambulance_service_areas",
        "Ambulance services",
        "Service providers, certification levels, transport volume and reported costs.",
        "VCGI_ambulanceService_info",
        "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/"
        "FS_VCGI_OPENDATA_Emergency_AmbulanceServiceAreas_SP_v1/FeatureServer/0",
        "Vermont Center for Geographic Information",
        INFRA_CAVEATS
        + (
            "City is the provider address, not the complete service territory.",
            (
                "Cost and transport fields retain source definitions and reporting "
                "periods; a reporting year is not provided by this cleaned table."
            ),
        ),
        value_columns={
            "total_tran": "transports",
            "per_no_tran": "source-defined percent",
            "re_per_tran": "source-defined rate",
            "cost_per": "USD",
            "cost_call": "USD",
        },
        filter_columns=(
            "object_id",
            "serv_name",
            "cert_level",
            "address",
            "street_1",
            "street_2",
            "city",
            "state",
            "zip_code",
        ),
    ),
    Dataset(
        "flood_hazard",
        "Flood hazard areas",
        "Tabular FEMA flood hazard polygon "
        "classifications and source-provided base-flood-elevation display labels.",
        "FEMA_floodHazard_geom",
        "https://www.fema.gov/flood-maps/national-flood-hazard-layer",
        "Federal Emergency Management Agency, National Flood Hazard Layer",
        (
            (
                "Geometry is intentionally excluded. Rows are polygon records, not "
                "unique zones, properties, or a property-specific flood determination."
            ),
            (
                "No geographic identifiers or observation year are available in this "
                "cleaned table; municipality filters and time series are not supported."
            ),
        ),
        filter_columns=(
            "flood_zone_type",
            "zone_subtype",
            "base_flood_elevation",
            "flood_risk",
            "special_flood_hazard_zone",
        ),
    ),
]

DATASETS: dict[str, Dataset] = {dataset.id: dataset for dataset in _DATASET_LIST}


def get_dataset(dataset_id: str) -> Dataset:
    try:
        return DATASETS[dataset_id]
    except KeyError:
        raise ValueError(f"Unknown dataset: {dataset_id}. Use list_datasets.") from None


def quote_identifier(identifier: str) -> str:
    """Quote trusted catalog/warehouse metadata only, never raw caller SQL."""
    return '"' + identifier.replace('"', '""') + '"'


def _tables(conn: Any) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }


def _columns(conn: Any, table: str) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in conn.execute(f"DESCRIBE {quote_identifier(table)}").fetchall()
    ]


def _metadata(dataset: Dataset) -> dict[str, Any]:
    return {
        "dataset_id": dataset.id,
        "label": dataset.label,
        "description": dataset.description,
        "source": {"name": dataset.source_name, "url": dataset.source_url},
        "caveats": list(dataset.caveats),
        "kind": dataset.kind,
        "year_column": dataset.year_column,
        "name_column": dataset.name_column,
        "geo_type_column": dataset.geo_type_column,
        "geoid_column": dataset.id_column,
        "fixed_geo_type": dataset.fixed_geo_type,
        "variable_columns": list(dataset.variable_columns),
        "value_columns": dataset.value_columns,
        "filter_columns": list(dataset.filter_columns),
        **dataset_lineage(dataset),
    }


def dataset_lineage(dataset: Dataset) -> dict[str, Any]:
    """Verified current code path, distinct from unavailable per-row ETL history."""
    simple_series = {
        "acs5_ts_median_age": (
            "demographics",
            "Median Age",
            "median_age",
            "B01002_001E",
        ),
        "acs5_ts_household_income": (
            "economic",
            "Median Household Income",
            "median_household_income",
            "B19013_001E",
        ),
        "acs5_ts_per_capita_income": (
            "economic",
            "Per Capita Income",
            "per_capita_income",
            "B19301_001E",
        ),
        "acs5_ts_median_home_value": (
            "housing",
            "Median Home Value",
            "median_home_value",
            "B25077_001E",
        ),
        "acs5_ts_housing_units": (
            "housing",
            "Total Housing Units",
            "total_housing_units",
            "B25001_001E",
        ),
    }
    cleaners = {
        "acs5_demographics": "acs5_tidy",
        "acs5_economics": "acs5_tidy",
        "acs5_housing": "acs5_tidy",
        "acs5_education": "acs5_tidy",
        "acs5_snapshot": "acs5_tidy",
        "acs5_dp": "acs5",
        "acs5_ts_age_dependency_ratio": "acs5_timeseries",
        "acs5_ts_population_change": "acs5_timeseries",
        "acs5_ts_historic_population": "historic_population",
        "acs5_ts_historic_population_change": "historic_population",
        "acs5_ts_median_earnings": "acs5_timeseries",
        "acs5_ts_health_insurance": "acs5_timeseries",
        "acs5_ts_income_burden": "acs5_timeseries",
        "acs5_ts_vacancy_rates": "acs5_timeseries",
        "qcew_employment_by_sector": "qcew",
        "ambulance_service_areas": "ambulance",
        "flood_hazard": "flood",
    }
    cleaner = cleaners.get(dataset.id)
    if dataset.id in simple_series:
        cleaner = "acs5_timeseries"
    elif dataset.id.startswith("wastewater_"):
        cleaner = "wastewater"
    elif dataset.id.startswith("zoning_"):
        cleaner = "zoning"
    elif dataset.id.startswith("cdc_places_"):
        cleaner = "cdc"
    result: dict[str, Any] = {
        "warehouse_table": dataset.table,
        "transformations": [f"backend/data_cleaning/clean_{cleaner}.py"]
        if cleaner
        else [],
        "source_columns": {},
        "source_code_note": (
            "References describe the current repository pipeline. The warehouse does not "
            "retain per-row source files or Census codes, so this is not a certificate "
            "of historical lineage. Source-year labels and codes can change."
        ),
    }
    if dataset.id in simple_series:
        source, variable, output, code = simple_series[dataset.id]
        result["source_columns"] = {
            output: {
                "raw_table": f"RAW.{source}",
                "raw_column": "Value",
                "selectors": {"Variable": variable},
                "census_codes": [code],
                "code_reference": f"backend/data_collection/{source}.py",
            }
        }
        if f"{output}_moe" in dataset.value_columns:
            result["source_columns"][f"{output}_moe"] = {
                "raw_table": f"RAW.{source}",
                "raw_column": "Value_MOE",
                "selectors": {"Variable": variable},
                "census_codes": [code[:-1] + "M"],
                "code_reference": f"backend/data_collection/{source}.py",
            }
        result["transformations"].insert(0, f"backend/data_collection/{source}.py")
        if dataset.id == "acs5_ts_median_home_value":
            result["source_code_note"] += (
                " The served table is built by clean_acs5_timeseries.py; the retired "
                "build/acs5.py median-home-value CSV path is not this declared pipeline."
            )
    elif dataset.id == "acs5_ts_income_burden":
        subcategories = {
            "Renters": "Occupied units paying rent (excluding units where GRAPI cannot be computed)",
            "Owners with a mortgage": "Housing units with a mortgage (excluding units where SMOCAPI cannot be computed)",
            "Owners without a mortgage": "Housing unit without a mortgage (excluding units where SMOCAPI cannot be computed)",
        }
        selectors = {
            "Measure": "Estimate",
            "Subcategory_by_Variable": subcategories,
            "year_min": 2013,
        }
        result["source_columns"] = {
            "Value": {
                "raw_table": "RAW.acs5_housing",
                "raw_column": "Value",
                "aggregation": "SUM of the 30.0-34.9% and 35.0%+ household "
                "counts; All households sums the three tenures",
                "selectors": {
                    **selectors,
                    "Variable": ["30.0 to 34.9 percent", "35.0 percent or more"],
                },
                "census_codes": [],
            },
            "Total": {
                "raw_table": "RAW.acs5_housing",
                "raw_column": "Value",
                "aggregation": "Tenure Total; All households sums the three tenures",
                "selectors": {**selectors, "Variable": "Total"},
                "census_codes": [],
            },
            "Percent": {
                "derived_from": ["Value", "Total"],
                "aggregation": "ROUND(100 * Value / Total, 1); null when Total is 0",
                "census_codes": [],
            },
        }
        result["source_code_note"] += (
            " Counts are used rather than the published percentages, whose "
            "Measure label is 'Percent Estimate' in 2017-2018. Negative Census "
            "sentinels and non-numeric values are treated as missing before "
            "summing, and a row is missing unless every input is present "
            "exactly once."
        )
    elif dataset.kind == "dp":
        result["source_columns"] = {
            "value": {
                "raw_tables": [
                    "RAW.acs5_social",
                    "RAW.acs5_economic",
                    "RAW.acs5_housing",
                    "RAW.acs5_demographic",
                ],
                "raw_column": "Value",
                "census_codes": [],
                "selector_columns": list(dataset.variable_columns),
            },
            "moe": {
                "raw_tables": [
                    "RAW.acs5_social",
                    "RAW.acs5_economic",
                    "RAW.acs5_housing",
                    "RAW.acs5_demographic",
                ],
                "raw_column": "MOE",
                "census_codes": [],
                "selector_columns": list(dataset.variable_columns),
            },
        }
    return result


provenance_metadata = dataset_lineage


def _year_metadata(
    years: list[int], *, bounds: tuple[int, int] | None = None
) -> dict[str, Any]:
    years = sorted({year for year in years if year is not None})
    low, high = (years[0], years[-1]) if years else (None, None)
    span = bounds or ((low, high) if years else None)
    gaps = []
    if span and span[1] - span[0] <= 500:
        gaps = sorted(set(range(span[0], span[1] + 1)) - set(years))
    return {"years_available": years, "year_min": low, "year_max": high, "gaps": gaps}


def _coverage(conn: Any, dataset: Dataset) -> dict[str, Any]:
    if dataset.year_column:
        year = quote_identifier(dataset.year_column)
        rows = conn.execute(
            f"SELECT DISTINCT TRY_CAST({year} AS INTEGER) FROM {quote_identifier(dataset.table)}"
        ).fetchall()
        return _year_metadata([row[0] for row in rows])
    return _year_metadata([])


def _geography_expression(dataset: Dataset) -> str | None:
    if dataset.geo_type_column:
        column = quote_identifier(dataset.geo_type_column)
        return f"CASE WHEN {column} IN ('town', 'municipality') THEN 'county_subdivision' ELSE {column} END"
    if dataset.fixed_geo_type:
        return "'" + dataset.fixed_geo_type + "'"
    if dataset.kind == "dp":
        name = f"lower(trim({quote_identifier(dataset.name_column)}))"
        return f"""CASE
            WHEN {name} = 'united states' THEN 'national'
            WHEN {name} = 'vermont' THEN 'state'
            WHEN regexp_full_match({name}, '[^,]+ county, vermont') THEN 'county'
            WHEN regexp_full_match({name}, 'census tract [^,]+, [^,]+ county, vermont') THEN 'tract'
            WHEN regexp_full_match({name}, '[^,]+, [^,]+ county, vermont') THEN 'county_subdivision'
            ELSE 'unknown' END"""
    return None


def _geography_coverage(
    conn: Any, dataset: Dataset, years: list[int]
) -> dict[str, Any]:
    geography = _geography_expression(dataset)
    if geography is None:
        return {}
    if not dataset.year_column:
        return {
            str(row[0]): _year_metadata([])
            for row in conn.execute(
                f"SELECT DISTINCT {geography} FROM {quote_identifier(dataset.table)}"
            ).fetchall()
            if row[0] is not None
        }
    year = f"TRY_CAST({quote_identifier(dataset.year_column)} AS INTEGER)"
    name = quote_identifier(dataset.name_column) if dataset.name_column else "NULL"
    rows = conn.execute(
        f"SELECT {geography}, {year}, COUNT(DISTINCT {name}) "
        f"FROM {quote_identifier(dataset.table)} GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    grouped: dict[str, dict[int, int]] = {}
    for geo_type, year, count in rows:
        if geo_type is not None and year is not None:
            grouped.setdefault(str(geo_type), {})[year] = count
    bounds = (min(years), max(years)) if years else None
    return {
        geo_type: _year_metadata(list(counts), bounds=bounds)
        | {
            "geography_count_by_year": {
                str(year): count for year, count in counts.items()
            }
        }
        for geo_type, counts in grouped.items()
    }


def _filter_values(
    conn: Any, dataset: Dataset, column: str, filters: dict[str, list[Any]], limit: int
) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise ValueError("value_limit must be between 1 and 200.")
    if column not in dataset.filter_columns:
        raise ValueError(f"Unknown filter column: {column}.")
    types = dict(_columns(conn, dataset.table))
    if column not in types:
        raise ValueError(f"Filter column {column} is unavailable in this warehouse.")
    clauses, params = [], []
    if len(filters) > 20:
        raise ValueError("At most 20 value filters are supported.")
    for field, values in filters.items():
        if field not in dataset.filter_columns or field not in types:
            raise ValueError(f"Unknown filter column: {field}.")
        if not isinstance(values, list) or not 1 <= len(values) <= 50:
            raise ValueError(
                "Each value filter must be a nonempty list of at most 50 values."
            )
        if any(
            not isinstance(value, (str, int, float, bool))
            or (isinstance(value, str) and len(value) > 500)
            or (isinstance(value, float) and not math.isfinite(value))
            for value in values
        ):
            raise ValueError("Invalid filter value.")
        expression = quote_identifier(field)
        if types[field] == "VARCHAR":
            expression = f"lower(trim({expression}))"
            values = [str(value).strip().lower() for value in values]
        clauses.append(f"{expression} IN ({','.join('?' for _ in values)})")
        params.extend(values)
    expression = quote_identifier(column)
    if types[column] == "VARCHAR":
        expression = f"trim({expression})"
        sql = (
            f"SELECT MIN({expression}) AS __filter_value FROM {quote_identifier(dataset.table)} "
            f"WHERE {' AND '.join(clauses) or 'TRUE'} GROUP BY lower({expression}) "
            "ORDER BY lower(__filter_value) NULLS LAST, __filter_value LIMIT ?"
        )
    else:
        sql = (
            f"SELECT DISTINCT {expression} AS __filter_value FROM {quote_identifier(dataset.table)} "
            f"WHERE {' AND '.join(clauses) or 'TRUE'} ORDER BY __filter_value NULLS LAST LIMIT ?"
        )
    rows = conn.execute(sql, params + [limit + 1]).fetchall()
    values = []
    for (value,) in rows[:limit]:
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, float) and not math.isfinite(value):
            value = None
        values.append(value)
    return {
        "column": column,
        "values": values,
        "has_more": len(rows) > limit,
        "limit": limit,
        "applied_filters": filters,
    }


def list_datasets(conn: Any, query: str | None = None) -> list[dict[str, Any]]:
    tables = _tables(conn)
    needle = (query or "").casefold().strip()
    results = []
    for dataset in DATASETS.values():
        if (
            needle
            and needle
            not in (
                dataset.id + " " + dataset.label + " " + dataset.description
            ).casefold()
        ):
            continue
        available = dataset.table in tables
        results.append(
            _metadata(dataset)
            | {"available": available}
            | (
                _coverage(conn, dataset)
                if available
                else {"year_min": None, "year_max": None}
            )
        )
    return results


def describe_dataset(
    conn: Any,
    dataset_id: str,
    *,
    value_column: str | None = None,
    value_filters: dict[str, list[Any]] | None = None,
    value_limit: int = 50,
) -> dict[str, Any]:
    if value_filters and value_column is None:
        raise ValueError("value_column is required when using value_filters.")
    dataset = get_dataset(dataset_id)
    available = dataset.table in _tables(conn)
    result = _metadata(dataset) | {"available": available}
    if not available:
        return result | {
            "columns": [],
            "year_min": None,
            "year_max": None,
            "years_available": [],
            "gaps": [],
            "coverage_by_geo_type": {},
            "unavailable_reason": "Dataset table is absent from this warehouse.",
        }
    allowed = set(dataset.filter_columns) | set(dataset.value_columns or {})
    allowed.update(dataset.variable_columns)
    allowed.update(
        filter(
            None,
            (
                dataset.year_column,
                dataset.name_column,
                dataset.geo_type_column,
                dataset.id_column,
            ),
        )
    )
    result["columns"] = [
        {"name": name, "type": dtype, "unit": (dataset.value_columns or {}).get(name)}
        for name, dtype in _columns(conn, dataset.table)
        if name in allowed
    ]
    result |= _coverage(conn, dataset)
    result["coverage_by_geo_type"] = _geography_coverage(
        conn, dataset, result["years_available"]
    )
    result["geo_types"] = sorted(result["coverage_by_geo_type"])
    result["coverage_note"] = (
        "Coverage counts source rows, including unavailable values, across all variables. "
        "It does not guarantee every place or variable exists in every listed year. "
        "Gaps are calendar years without rows within the dataset span; historic census "
        "series are not annual. search_variables reports coverage for each exact selector."
    )
    filters = value_filters or {}
    if value_column is not None:
        result["filter_values"] = _filter_values(
            conn, dataset, value_column, filters, value_limit
        )
    else:
        column_names = {column["name"] for column in result["columns"]}
        suggested = (
            "table",
            "category",
            "measure",
            "section",
            "district_type",
            "overlay_district",
        )
        result["filter_values_by_column"] = {
            column: _filter_values(conn, dataset, column, filters, 25)
            for column in suggested
            if column in dataset.filter_columns and column in column_names
        }
    return result


def encode_variable_id(dataset: Dataset, selectors: dict[str, Any]) -> str:
    payload = json.dumps(
        {"dataset_id": dataset.id, "selectors": selectors},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "v1:" + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_variable_id(dataset: Dataset, variable_id: str) -> dict[str, Any]:
    if not isinstance(variable_id, str) or len(variable_id) > 16_384:
        raise ValueError("Invalid variable_id; use search_variables.")
    if not variable_id.startswith("v1:"):
        raise ValueError("Invalid variable_id version; use search_variables.")
    try:
        encoded = variable_id[3:]
        decoded = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(decoded)
    except (ValueError, UnicodeError, binascii.Error):
        raise ValueError("Malformed variable_id; use search_variables.") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"dataset_id", "selectors"}
        or payload["dataset_id"] != dataset.id
    ):
        raise ValueError("variable_id belongs to a different dataset or is invalid.")
    selectors = payload["selectors"]
    if not isinstance(selectors, dict):
        raise ValueError("Invalid variable selectors.")  # noqa: TRY004 - malformed token
    if dataset.variable_columns:
        if set(selectors) != set(dataset.variable_columns):
            raise ValueError("variable_id must specify every variable dimension.")
        if any(
            value is not None and (not isinstance(value, str) or len(value) > 2048)
            for value in selectors.values()
        ):
            raise ValueError("Invalid variable selector value.")
    elif (
        set(selectors) != {"$column"}
        or not isinstance(selectors["$column"], str)
        or selectors["$column"] not in dataset.value_columns
    ):
        raise ValueError("variable_id must identify an allowed value column.")
    return selectors


def margin_column(dataset: Dataset, measure: str) -> str | None:
    """The column holding `measure`'s 90% margin of error, if it has one."""
    columns = dataset.value_columns or {}
    if f"{measure}_moe" in columns:
        return f"{measure}_moe"
    # Data profile rows keep their published margin as `moe` beside `value`.
    if dataset.kind == "dp" and measure == "value" and "moe" in columns:
        return "moe"
    return None


def with_margins(dataset: Dataset, measures: list[str]) -> list[str]:
    """`measures` with each one's margin right after it. A margin means nothing
    without its estimate, so the two always travel together."""
    paired = []
    for measure in measures:
        paired += [measure, margin_column(dataset, measure)]
    return list(dict.fromkeys(m for m in paired if m))


def variable_units(dataset: Dataset, selectors: dict[str, Any]) -> dict[str, str]:
    """Resolve row-specific units without treating every ACS value as a count."""
    units = dict(dataset.value_columns or {})
    column = selectors.get("$column")
    if column:
        return {c: units[c] for c in with_margins(dataset, [column])}
    variable = str(selectors.get("variable", ""))
    if dataset.id in {
        "acs5_demographics",
        "acs5_economics",
        "acs5_housing",
        "acs5_education",
        "acs5_snapshot",
    }:
        # These are the exact cleaned indicators, not guesses from label words.
        # A variable named "... Rate" still has a count in value and its rate
        # in percent. Future indicators retain an explicit unknown unit.
        value_units = {
            **dict.fromkeys(
                (
                    "Under 18",
                    "18 to 24",
                    "25 to 34",
                    "35 to 44",
                    "45 to 54",
                    "55 to 64",
                    "65 to 74",
                    "75 Plus",
                    "Female",
                    "Male",
                    "Population (ACS)",
                    "Hispanic or Latino (of any race)",
                    "American Indian and Alaska Native",
                    "Asian",
                    "Black or African American",
                    "Native Hawaiian and Other Pacific Islander",
                    "Some other race",
                    "Two or more races",
                    "White",
                    "Labor Force Participation Rate (16+)",
                    "Prime-Age Labor Force Participation Rate (25-54)",
                    "Associate's Degree",
                    "Bachelor's Degree",
                    "High School Graduate",
                    "No High School Diploma",
                    "Postgraduate Degree",
                    "Some College, No Degree",
                ),
                "people",
            ),
            **dict.fromkeys(
                ("Median Household Income", "Per Capita Income", "Median Home Value"),
                "USD (year-specific dollars)",
            ),
            **dict.fromkeys(
                (
                    "Homeowner Vacancy Rate",
                    "Rental Vacancy Rate",
                    "Renter-Occupied Units",
                    "Total Housing Units",
                ),
                "housing units",
            ),
            "Median Age": "years",
        }
        units["value"] = value_units.get(variable, "source-defined; unit unavailable")
        units["value_moe"] = units["value"]
    if dataset.kind == "dp":
        measure = str(selectors.get("measure", "")).casefold()
        subcategory = str(selectors.get("subcategory", "")).strip().casefold()
        percentage_bracket = re.fullmatch(
            r"(?:less than )?\d+(?:\.\d+)?(?: to \d+(?:\.\d+)?)? percent(?: or more)?",
            subcategory,
        )
        if (
            "percent" in measure
            and variable.strip().casefold() == "total"
            and not percentage_bracket
        ):
            units["value"] = "source-defined total; unit not verified"
        elif "percent" in measure:
            units["value"] = "percent"
        else:
            units["value"] = "source-defined estimate; inspect variable label"
        # A percent's margin (the PM code) is in percentage points.
        units["moe"] = (
            "percentage points" if units["value"] == "percent" else units["value"]
        )
    return units


def search_variables(
    conn: Any, dataset_id: str, query: str = "", limit: int = 50
) -> list[dict[str, Any]]:
    dataset = get_dataset(dataset_id)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200.")
    if dataset.table not in _tables(conn):
        raise ValueError("Dataset is not available in this warehouse.")
    tokens = list(dict.fromkeys(re.findall(r"[a-z0-9]+", query.casefold())))
    phrase = " ".join(tokens)
    if query.strip() and not tokens:
        return []
    if dataset.variable_columns:
        columns = ", ".join(
            quote_identifier(column) for column in dataset.variable_columns
        )
        text_columns = ", ".join(
            f"COALESCE(CAST({quote_identifier(column)} AS VARCHAR), '')"
            for column in dataset.variable_columns
        )
        searchable = f"trim(regexp_replace(lower(concat_ws(' ', {text_columns})), '[^a-z0-9]+', ' ', 'g'))"
        condition = " AND ".join("contains(search_text, ?)" for _ in tokens) or "TRUE"
        year = (
            f"TRY_CAST({quote_identifier(dataset.year_column)} AS INTEGER)"
            if dataset.year_column
            else "NULL::INTEGER"
        )
        # Group first: normalization runs once per selector, not once per
        # observation in the multi-million-row profile table.
        rows = conn.execute(
            f"""WITH variables AS MATERIALIZED (
                SELECT {columns}, list_sort(list(DISTINCT {year}) FILTER (WHERE {year} IS NOT NULL)) AS observed_years
                FROM {quote_identifier(dataset.table)} GROUP BY {columns}
            ), searchable AS (
                SELECT *, {searchable} AS search_text FROM variables
            )
            SELECT {columns}, observed_years FROM searchable WHERE {condition}
            ORDER BY CASE WHEN search_text = ? THEN 0
                WHEN contains(search_text, ?) THEN 1 ELSE 2 END,
                length(search_text), {columns} LIMIT ?""",
            tokens + [phrase, phrase, limit],
        ).fetchall()
        selected = [
            (dict(zip(dataset.variable_columns, row[:-1], strict=True)), row[-1] or [])
            for row in rows
        ]
    else:
        # A margin column comes back with its estimate, not as its own variable.
        margins = {margin_column(dataset, c) for c in dataset.value_columns}
        selectors_list = [
            {"$column": column}
            for column in dataset.value_columns
            if column not in margins
            and all(
                token in " ".join(re.findall(r"[a-z0-9]+", column.casefold()))
                for token in tokens
            )
        ][:limit]
        years = _coverage(conn, dataset)["years_available"]
        selected = [(selectors, years) for selectors in selectors_list]
    return [
        {
            "variable_id": encode_variable_id(dataset, selectors),
            "label": " / ".join(
                str(value) for value in selectors.values() if value is not None
            ),
            "selectors": selectors,
            **_year_metadata(years),
            "coverage_note": (
                "This variable_id identifies this exact selector tuple, not a harmonized "
                "cross-year series. Other labels or Measure values can represent the "
                "same concept in other years. Search those variants separately. Years "
                "include source rows with unavailable values and do not guarantee every place."
            ),
            "value_columns": variable_units(dataset, selectors),
            "measures": [
                {"name": name, "unit": unit}
                for name, unit in variable_units(dataset, selectors).items()
            ],
        }
        for selectors, years in selected
    ]


def build_locations(conn: Any) -> list[dict[str, Any]]:
    """Canonical Census IDs; retain town/city distinctions and county context.

    This is a small geography index, not a scan of observations. Historical GEOIDs
    supplement boundary lookup records (for historical municipalities).
    """
    tables = _tables(conn)
    locations: dict[str, dict[str, Any]] = {}

    def add(
        geoid: Any,
        name: str,
        geo_type: str,
        aliases: list[str],
        county_name: str | None = None,
    ) -> None:
        geoid = str(geoid)
        if not geoid or not name:
            return
        aliases = sorted(
            {name, geoid, *[alias for alias in aliases if alias]}, key=str.casefold
        )
        if geoid in locations:
            locations[geoid]["aliases"] = sorted(
                set(locations[geoid]["aliases"]) | set(aliases), key=str.casefold
            )
            return
        locations[geoid] = {
            "id": geoid,
            "location_id": geoid,
            "geoid": geoid,
            "name": name,
            "geo_type": geo_type,
            "aliases": aliases,
            "county": geoid[:5]
            if geo_type in {"county_subdivision", "tract"}
            else None,
            "county_name": county_name,
        }

    add("US", "United States", "national", ["USA"])
    add("50", "Vermont", "state", ["VT"])
    counties: dict[str, str] = {}
    if "vt_county_geoids" in tables:
        for name, geoid in conn.execute(
            "SELECT name, geoid FROM vt_county_geoids"
        ).fetchall():
            if geoid is None or name is None:
                continue
            geoid = str(geoid).zfill(5)
            county = name.removesuffix(" County, Vermont")
            counties[geoid] = county
            add(geoid, name, "county", [county, f"{county} County"])
    elif "vt_county_lines_geom" in tables:
        for geoid, county in conn.execute(
            "SELECT county_fips, county FROM vt_county_lines_geom"
        ).fetchall():
            county = county.title()
            geoid = str(geoid).zfill(5)
            counties[geoid] = county
            add(
                geoid,
                f"{county} County, Vermont",
                "county",
                [county, f"{county} County"],
            )
    if "vt_town_lines_geom" in tables:
        for geoid, town in conn.execute(
            "SELECT FIPS_ID, TOWN_NAME FROM vt_town_lines_geom"
        ).fetchall():
            if geoid is None or town is None:
                continue
            geoid = str(geoid).zfill(10)
            county = counties.get(geoid[:5])
            # Without a county lookup keep the boundary name; never guess county.
            name = f"{town}, {county} County, Vermont" if county else town
            aliases = [town]
            # Bare town names can match city names. Only a resolver checking all
            # candidates may use these aliases; canonical IDs remain unambiguous.
            if town.lower().endswith(" town"):
                aliases.append(town[:-5])
            add(geoid, name, "county_subdivision", aliases, county)
    if "VCGI_historicPopulation_timeseries" in tables:
        for geoid, name, geo_type, county in conn.execute(
            "SELECT DISTINCT geoid, name, geo_type, County "
            "FROM VCGI_historicPopulation_timeseries"
        ).fetchall():
            if geoid is None or name is None:
                continue
            normalized = "county_subdivision" if geo_type == "town" else geo_type
            if normalized not in {"state", "county", "county_subdivision", "national"}:
                continue
            canonical_id = "US" if normalized == "national" else str(geoid)
            add(canonical_id, name, normalized, [], county)
    if "vt_tract_lines_geom" in tables:
        for geoid, name in conn.execute(
            "SELECT LocationID, name FROM vt_tract_lines_geom"
        ).fetchall():
            if geoid is None or name is None:
                continue
            geoid = str(geoid).zfill(11)
            county = counties.get(geoid[:5])
            full_name = f"{name}, {county} County, Vermont" if county else name
            add(geoid, full_name, "tract", [name], county)
    # Merge current Census spelling into the stable boundary/historic GEOIDs.
    # Explicit historical spelling changes avoid approximate-name geography joins.
    spelling_changes = {
        "alburg town": "alburgh town",
        "enosburg town": "enosburgh town",
    }
    fullname_lookup = {
        alias.casefold(): place["id"]
        for place in locations.values()
        for alias in place["aliases"]
        if "," in alias or place["geo_type"] in {"state", "national"}
    }
    census_names = set()
    for table in ("acs5_demographics_tidy", "acs5_housing_tidy"):
        if table in tables:
            census_names.update(
                conn.execute(
                    f"SELECT DISTINCT name, geo_type FROM {quote_identifier(table)}"
                ).fetchall()
            )
    for name, geo_type in census_names:
        if name is None:
            continue
        lookup_name = name.casefold()
        first, separator, remainder = lookup_name.partition(",")
        if first in spelling_changes:
            lookup_name = spelling_changes[first] + separator + remainder
        geoid = fullname_lookup.get(lookup_name)
        if geoid and locations[geoid]["geo_type"] == geo_type:
            add(geoid, locations[geoid]["name"], geo_type, [name])

    # Bare "Rutland" is ambiguous between city and town. Never let that alias
    # assign an unqualified infrastructure row to either canonical location.
    subdivisions: dict[str, list[dict[str, Any]]] = {}
    for place in locations.values():
        if place["geo_type"] != "county_subdivision":
            continue
        short = place["name"].split(",")[0]
        base = short
        for suffix in (" town", " city", " village", " gore", " grant"):
            if short.casefold().endswith(suffix):
                base = short[: -len(suffix)]
                break
        subdivisions.setdefault(base.casefold(), []).append(place)
    for base, places in subdivisions.items():
        for place in places:
            aliases = set(place["aliases"])
            if len(places) == 1:
                short = place["name"].split(",")[0]
                aliases.add(short[: len(base)])
            else:
                aliases = {alias for alias in aliases if alias.casefold() != base}
            # Tables spell "St." as Saint / St / St. inconsistently (e.g. "St. Albans city")
            aliases.update(
                variant + alias[4:]
                for alias in tuple(aliases)
                if "," not in alias and alias.casefold().startswith("st. ")
                for variant in ("Saint ", "St ")
            )
            # Some infrastructure inventories concatenate municipality words.
            aliases.update(
                alias.replace(" ", "")
                for alias in tuple(aliases)
                if "," not in alias and not alias.isdigit()
            )
            place["aliases"] = sorted(aliases, key=str.casefold)
    return sorted(
        locations.values(), key=lambda row: (row["name"].casefold(), row["id"])
    )


location_index = build_locations


def search_locations(
    conn: Any, query: str = "", geo_type: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200.")
    if geo_type not in {
        None,
        "national",
        "state",
        "county",
        "county_subdivision",
        "tract",
    }:
        raise ValueError(
            "Unknown geography type; use county_subdivision for towns and cities."
        )
    needle = query.casefold().strip()
    matches = [
        row
        for row in build_locations(conn)
        if (geo_type is None or row["geo_type"] == geo_type)
        and any(needle in alias.casefold() for alias in row["aliases"])
    ]

    def relevance(row: dict[str, Any]) -> int:
        if needle == row["id"].casefold():
            return 0
        primary = row["name"].split(",")[0].casefold()
        if primary == needle or any(
            primary == needle + suffix
            for suffix in (" town", " city", " village", " county", " gore", " grant")
        ):
            return 1
        if primary.startswith(needle):
            return 2
        if needle in primary:
            return 3
        return 4

    # A municipality's own name outranks incidental matches in its county name.
    matches.sort(
        key=lambda row: (
            relevance(row),
            row["name"].casefold(),
            row["id"],
        )
    )
    return matches[:limit]
