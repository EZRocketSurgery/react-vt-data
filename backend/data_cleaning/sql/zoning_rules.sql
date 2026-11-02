CREATE OR REPLACE VIEW raw_rules AS
SELECT
    OBJECT_ID,
    col_name,
    val
FROM (
    UNPIVOT zoning_raw
    ON {{ rule_string }}
    INTO
    NAME col_name
    VALUE val
)
