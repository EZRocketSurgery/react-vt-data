-- One value per place per year for one Data Profile indicator, for the
-- Statewide County Comparison page. where_string (compiled by
-- query/county_comparison.py) picks the indicator's table, category, every
-- label path and measure name it has used, and the county/state/national rows.
-- Those paths cover separate years, so each place gets one row per year;
-- tests/test_county_comparison.py checks that against the real warehouse.
SELECT
    -- Short display name: "Essex County, Vermont" -> "Essex"
    REGEXP_REPLACE(name, ' County, Vermont$', '') AS place,
    geo_type,
    CAST(year AS INTEGER) AS year,
    CAST(value AS DOUBLE) AS value
FROM {{ table }}
{{ where_string }}
ORDER BY year, place
