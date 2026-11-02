-- Towns' unzoned areas as a GeoJSON FeatureCollection, drawn as a grey layer
-- underneath the zoning districts. Built by
-- data_cleaning/sql/zoning_empty_geom.sql, which already drops sliver-sized gaps.
--
-- This layer does not depend on the sidebar filters: it is the same "we have no
-- data here" backdrop regardless of which districts are being shown.
SELECT
    JSON_OBJECT(
        'type', 'FeatureCollection',
        'features', JSON_GROUP_ARRAY(feature)
    )::VARCHAR AS fc
FROM (
    SELECT
        JSON_OBJECT(
            'type', 'Feature',
            'geometry', ST_ASGEOJSON(
                ST_SIMPLIFY(
                    ST_GEOMFROMWKB(geom),
                    0.0001::DOUBLE
                )
            )::JSON,
            'properties', JSON_OBJECT(
                'rgba_color', JSON_ARRAY(170, 170, 170, 160),
                'tooltip', JSON_OBJECT(
                    '__title__', TOWN_NAME,
                    'Zoning', 'No zoning information for this area.'
                )
            )
        ) AS feature
    FROM VersoZoning_empty_geom
) AS features;
