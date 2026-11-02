{{ cte_filter_block }}
SELECT
    json_object(
        'type', 'FeatureCollection',
        'features', json_group_array(feature)
    )::VARCHAR AS fc
FROM (
    SELECT
        json_object(
            'type', 'Feature',
            'geometry', ST_AsGeoJSON(
                ST_Simplify(ST_GeomFromWKB(g.geometry), 0.0001)
            )::JSON,
            'properties', json_object(
                'Certification Level', i.cert_level,
                'Acres', ROUND(g.shape__area, 2),
                'rgba_color', c.rgba::JSON,
                'tooltip', json_object(
                    '__title__', 'Ambulance Service Areas',
                    'Company Name', i.serv_name,
                    'Address of Company', i.address,
                    'Certification Level', i.cert_level,
                    'Acres', ROUND(g.shape__area, 2)
                )
            )
        ) AS feature
    FROM VCGI_ambulanceService_info AS i
    INNER JOIN VCGI_ambulanceService_geom AS g USING (object_id)
    LEFT JOIN VCGI_ambulanceService_colors AS c
        ON i.cert_level = c.certification_level
    {{ join_filter_block }}
) AS features
