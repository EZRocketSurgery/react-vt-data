{{ cte_filter_block }}
SELECT
    b.object_id,
    b.town,
    b.county,
    b.geoid,
    b.name,
    b.height_ft,
    b.building_type,
    ST_AsGeoJSON(b.geometry) AS geometry
FROM VCGI_buildingFootprints_geom AS b
{{ join_filter_block }}
