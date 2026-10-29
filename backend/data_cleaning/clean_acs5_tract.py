"""
**Description**:
    Tract-level poverty and health-insurance indicators from RAW.acs5_tract
    (see data_collection/acs5_tract.py), for pairing with CDC PLACES tracts.

    Each indicator is a share (count / universe) with a 90% margin of error,
    derived with the Census Bureau's formulas for sums (root sum of squared
    MOEs) and proportions. Census sentinels (negative estimates) and any
    missing component make the indicator NULL instead of a partial sum.

    Writes lake.CLEANED.acs5_tract_tidy: year, geoid, county_fips, county,
    name, geo_type, section, variable, value (count), universe, percent,
    percent_moe.
"""

import duckdb

from data_cleaning.geo_lookup import build_geo_lookups, write_table

TABLE_NAME = "acs5_tract_tidy"


def c27016(n: int) -> str:
    return f"C27016_{n:03d}"


# C27016 groups by ratio of income to poverty: each group's total is followed
# by under-19, 19-64 and 65+ subtotals, each split into with/without coverage,
# so a group starting at code s has "No health insurance" at s+3, s+6, s+9.
# 1.38 is Vermont's Medicaid income limit for adults (138% of poverty).
BELOW_138 = [2, 12]  # under 1.00, 1.00 to 1.37
AT_OR_ABOVE_138 = [22, 32, 42]  # 1.38 to 1.99, 2.00 to 3.99, 4.00 and over


def uninsured(groups: list[int]) -> list[str]:
    return [c27016(s + k) for s in groups for k in (3, 6, 9)]


# (section, variable, numerator codes, denominator codes)
INDICATORS: list[tuple[str, str, list[str], list[str]]] = [
    ("Poverty", "Below poverty level", ["B17001_002"], ["B17001_001"]),
    (
        "Health insurance",
        "No health insurance",
        uninsured(BELOW_138 + AT_OR_ABOVE_138),
        [c27016(1)],
    ),
    (
        "Health insurance",
        "No health insurance, below 138% of poverty",
        uninsured(BELOW_138),
        [c27016(s) for s in BELOW_138],
    ),
    (
        "Health insurance",
        "No health insurance, 138% of poverty or more",
        uninsured(AT_OR_ABOVE_138),
        [c27016(s) for s in AT_OR_ABOVE_138],
    ),
]


def _in_list(codes: list[str]) -> str:
    return ", ".join(f"'{c}'" for c in codes)


def indicator_sql(section: str, variable: str, num: list[str], den: list[str]) -> str:
    """One row per tract and year for a single count / universe indicator."""
    return f"""--sql
        SELECT
            year, NAME, state, county, tract,
            '{section}' AS section,
            '{variable}' AS variable,
            SUM(est) FILTER (WHERE code IN ({_in_list(num)})) AS num,
            COUNT(est) FILTER (WHERE code IN ({_in_list(num)})) = {len(num)}
                AS num_ok,
            SQRT(SUM(moe * moe) FILTER (WHERE code IN ({_in_list(num)})))
                AS num_moe,
            SUM(est) FILTER (WHERE code IN ({_in_list(den)})) AS den,
            COUNT(est) FILTER (WHERE code IN ({_in_list(den)})) = {len(den)}
                AS den_ok,
            SQRT(SUM(moe * moe) FILTER (WHERE code IN ({_in_list(den)})))
                AS den_moe,
            COUNT(moe) FILTER (WHERE code IN ({_in_list(num + den)}))
                = {len(set(num + den))} AS moe_ok
        FROM raw
        WHERE code IN ({_in_list(num + den)})
        GROUP BY ALL
    """


def tract_sql() -> str:
    unions = "\nUNION ALL\n".join(indicator_sql(*i) for i in INDICATORS)
    return f"""--sql
        WITH raw AS (
            SELECT
                year, NAME, state, county, tract, code,
                CASE WHEN estimate >= 0 THEN estimate END AS est,
                -- -555555555: the estimate is controlled, so its margin of
                -- error is zero. Other negative codes are missing, e.g.
                -- -222222222: too few sample cases to compute a margin.
                CASE
                    WHEN moe >= 0 THEN moe
                    WHEN moe = -555555555 THEN 0
                END AS moe
            FROM lake.RAW.acs5_tract
        ),
        indicators AS (
            {unions}
        ),
        rated AS (
            SELECT
                *,
                CASE WHEN num_ok AND den_ok AND den > 0 THEN num / den END AS p
            FROM indicators
        )
        SELECT
            -- Text, like the other ACS tables (comparison.py filters on it).
            CAST(r.year AS VARCHAR) AS year,
            CONCAT(r.state, r.county, r.tract) AS geoid,
            CONCAT(r.state, r.county) AS county_fips,
            c.county,
            -- "Census Tract 9601; Addison County; Vermont" (commas before
            -- 2023) -> "Census Tract 9601, Addison County"
            regexp_replace(
                regexp_replace(r.NAME, '[;,] Vermont$', ''), ';', ',', 'g'
            ) AS name,
            'tract' AS geo_type,
            r.section,
            r.variable,
            CASE WHEN r.num_ok THEN r.num END AS value,
            CASE WHEN r.den_ok THEN r.den END AS universe,
            ROUND(100 * r.p, 1) AS percent,
            -- Census proportion MOE; the + form when the difference goes
            -- negative, per the ACS handbook.
            CASE WHEN r.p IS NOT NULL AND r.moe_ok THEN ROUND(
                100 * SQRT(
                    CASE
                        WHEN r.num_moe ^ 2 >= r.p ^ 2 * r.den_moe ^ 2
                            THEN r.num_moe ^ 2 - r.p ^ 2 * r.den_moe ^ 2
                        ELSE r.num_moe ^ 2 + r.p ^ 2 * r.den_moe ^ 2
                    END
                ) / r.den,
                1
            ) END AS percent_moe
        FROM rated AS r
        LEFT JOIN geo_county_lookup AS c
            ON CONCAT(r.state, r.county) = c.county_fips
    """


def main(con: duckdb.DuckDBPyConnection):
    build_geo_lookups(con)
    write_table(con, TABLE_NAME, tract_sql())
