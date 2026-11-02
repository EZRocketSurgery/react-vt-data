SELECT *
FROM {{ table }}
{{ where_string }}
ORDER BY year
