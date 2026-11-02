-- Filter PLACES before joining the county lines: the compiled WHERE clause
-- names columns unqualified, and both tables have county, county_fips and geoid.
WITH places AS (
    SELECT *
    FROM cdc_places_county
    {{ where_string }}
)

SELECT
    p.geoid,
    p.measure,
    p.data_value,
    p.bin,
    ROUND(p.natl_pct * 100, 2) AS natl_pct,
    p.county,
    ST_ASGEOJSON(ST_GeomFromWKB(c.geometry)) AS geometry
FROM places AS p
LEFT JOIN vt_county_lines_geom AS c
    ON p.geoid = c.geoid
