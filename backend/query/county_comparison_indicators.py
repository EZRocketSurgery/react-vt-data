"""
Indicator definitions for the Statewide County Comparison page (queried by
`query/county_comparison.py`).

Census relabels Data Profile rows between vintages, so one indicator can sit
under several (subcategory, variable) label paths, e.g. the share of adults
with a bachelor's degree or higher is

    "Percent bachelor's degree or higher" / "Total"                  2010-2016
    "Population 25 years and over" / "Percent bachelor's degree..."  2017
    "Population 25 years and over" / "Bachelor's degree or higher"   2018-2024

and its percent is stored as measure "Percent Estimate" in 2017-2018 but
"Percent" otherwise. Each Indicator lists every path and measure it has
used, so the query stitches them into one series per place.

Some categories also change name every year, e.g. "INCOME AND BENEFITS (IN
2024 INFLATION-ADJUSTED DOLLARS)", so `category` is a SQL LIKE pattern.

Indicators not built yet are listed with available=False so the page can show
them as "coming soon".
"""

from dataclasses import dataclass

PERCENT_MEASURES = ("Percent", "Percent Estimate")

EDUCATION = "EDUCATIONAL ATTAINMENT"
POVERTY = (
    "PERCENTAGE OF FAMILIES AND PEOPLE WHOSE INCOME IN THE PAST 12 MONTHS IS "
    "BELOW THE POVERTY LEVEL"
)
DISABILITY = "DISABILITY STATUS OF THE CIVILIAN NONINSTITUTIONALIZED POPULATION"
ADULTS_25_PLUS = "Population 25 years and over"


@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    topic: str
    description: str = ""
    units: str = "percent"
    table: str = ""
    category: str = ""  # SQL LIKE pattern; a plain name matches exactly
    paths: tuple[tuple[str, str], ...] = ()  # (subcategory, variable)
    measures: tuple[str, ...] = PERCENT_MEASURES
    available: bool = True


def _education(key: str, label: str, *names: str) -> Indicator:
    """An educational attainment level, under every name Census has used.

    2010-2012 file each level as its own subcategory ("<name>" / "Total");
    from 2013 it is a variable under "Population 25 years and over".
    """
    return Indicator(
        key=key,
        label=label,
        topic="Educational attainment",
        description=f"{label}, as a percent of adults 25 years and over.",
        table="DP02",
        category=EDUCATION,
        paths=tuple((name, "Total") for name in names)
        + tuple((ADULTS_25_PLUS, name) for name in names),
    )


def _poverty(key: str, label: str, who: str, *paths: tuple[str, str]) -> Indicator:
    """A poverty rate. Census moved most groups under "All people" or "All
    families" over the years, so `paths` lists each heading it has used; the
    years each covers are noted beside it."""
    return Indicator(
        key=key,
        label=label,
        topic="Poverty",
        description=(
            f"Percent of {who} whose income in the past 12 months is below "
            "the poverty level."
        ),
        table="DP03",
        category=POVERTY,
        paths=paths,
    )


def _disability(key: str, label: str, who: str, group: str) -> Indicator:
    """Percent of a group with a disability. Census publishes these percents
    from 2013 only, so the series starts there."""
    return Indicator(
        key=key,
        label=label,
        topic="Disability",
        description=(
            f"Percent of {who} in the civilian noninstitutionalized population "
            "with a disability."
        ),
        table="DP02",
        category=DISABILITY,
        paths=((group, "With a disability"),),
    )


INDICATORS = [
    _education(
        "edu_bachelors_or_higher",
        "Bachelor's degree or higher",
        "Percent bachelor's degree or higher",
        "Bachelor's degree or higher",
    ),
    _education(
        "edu_hs_or_higher",
        "High school graduate or higher",
        "Percent high school graduate or higher",
        "High school graduate or higher",
    ),
    _education("edu_less_than_9th", "Less than 9th grade", "Less than 9th grade"),
    _education(
        "edu_9th_to_12th",
        "9th to 12th grade, no diploma",
        "9th to 12th grade, no diploma",
    ),
    _education(
        "edu_hs_graduate",
        "High school graduate (includes equivalency)",
        "High school graduate (includes equivalency)",
    ),
    _education(
        "edu_some_college", "Some college, no degree", "Some college, no degree"
    ),
    _education("edu_associates", "Associate's degree", "Associate's degree"),
    _education("edu_bachelors", "Bachelor's degree", "Bachelor's degree"),
    _education(
        "edu_graduate",
        "Graduate or professional degree",
        "Graduate or professional degree",
    ),
    _disability(
        "disability_all_people",
        "With a disability: all people",
        "all people",
        "Total Civilian Noninstitutionalized Population",
    ),
    _disability(
        "disability_children",
        "With a disability: children under 18",
        "children under 18",
        "Under 18 years",
    ),
    _disability(
        "disability_adults_18_64",
        "With a disability: adults 18 to 64",
        "adults 18 to 64",
        "18 to 64 years",
    ),
    _disability(
        "disability_seniors",
        "With a disability: adults 65 and over",
        "adults 65 and over",
        "65 years and over",
    ),
    Indicator(
        key="unemployment_rate",
        label="Unemployment rate",
        topic="Unemployment",
        description="Percent of the civilian labor force that is unemployed.",
        table="DP03",
        category="EMPLOYMENT STATUS",
        paths=(
            ("Percent Unemployed", "Total"),  # 2010-2012
            ("Civilian labor force", "Percent Unemployed"),  # 2013-2014
            ("Civilian labor force", "Unemployment Rate"),  # 2015+
        ),
    ),
    _poverty(
        "poverty_all_people",
        "Poverty rate: all people",
        "all people",
        ("All people", "Total"),
    ),
    _poverty(
        "poverty_children",
        "Poverty rate: children under 18",
        "children under 18",
        ("Under 18 years", "Total"),  # 2010-2015
        ("All people", "Under 18 years"),  # 2016+
    ),
    _poverty(
        "poverty_adults",
        "Poverty rate: adults 18 and over",
        "adults 18 and over",
        ("18 years and over", "Total"),  # 2010-2015
        ("All people", "18 years and over"),  # 2016+
    ),
    _poverty(
        "poverty_adults_18_64",
        "Poverty rate: adults 18 to 64",
        "adults 18 to 64",
        ("18 years and over", "18 to 64 years"),  # 2010-2012
        ("18 to 64 years", "Total"),  # 2013-2015
        ("All people", "18 years and over: 18 to 64 years"),  # 2016+
    ),
    _poverty(
        "poverty_seniors",
        "Poverty rate: adults 65 and over",
        "adults 65 and over",
        ("18 years and over", "65 years and over"),  # 2010-2012
        ("65 years and over", "Total"),  # 2013-2015
        ("All people", "18 years and over: 65 years and over"),  # 2016+
    ),
    _poverty(
        "poverty_families",
        "Poverty rate: all families",
        "all families",
        ("All families", "Total"),
    ),
    _poverty(
        "poverty_families_children",
        "Poverty rate: families with children under 18",
        "families with related children under 18",
        ("All families", "With related children under 18 years"),  # 2010-2014
        # 2015+
        ("All families", "With related children of the householder under 18 years"),
    ),
    _poverty(
        "poverty_married_couple",
        "Poverty rate: married-couple families",
        "married-couple families",
        ("Married couple families", "Total"),  # 2010-2018
        ("All families", "Married couple families"),  # 2019+
    ),
    _poverty(
        "poverty_female_householder",
        "Poverty rate: families with a female householder, no spouse",
        # Census wording: "no husband present" through 2018, "no spouse
        # present" from 2019.
        "families with a female householder and no spouse present",
        ("Families with female householder, no husband present", "Total"),
        ("All families", "Families with female householder, no spouse present"),
    ),
    Indicator(
        key="median_household_income",
        label="Median household income",
        topic="Income",
        # Each year is in that year's dollars, as Census publishes it (the
        # same as the Census Variable Comparison); not adjusted across years.
        description=(
            "Median household income, in dollars of the survey year "
            "(not adjusted for inflation between years)."
        ),
        units="dollars",
        table="DP03",
        category="INCOME AND BENEFITS (IN % INFLATION-ADJUSTED DOLLARS)",
        paths=(
            ("Median household income (dollars)", "Total"),  # 2010-2012
            ("Total households", "Median household income (dollars)"),  # 2013+
        ),
        measures=("Estimate",),
    ),
]

INDICATORS_BY_KEY = {i.key: i for i in INDICATORS}


def indicator_options() -> list[dict]:
    """The picker list: every indicator, built or not, without its SQL paths."""
    return [
        {
            "key": i.key,
            "label": i.label,
            "topic": i.topic,
            "description": i.description,
            "units": i.units,
            "available": i.available,
        }
        for i in INDICATORS
    ]
