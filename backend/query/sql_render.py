"""
**Created**:
    2026-07-02
**Description**:
    Jinja SQL rendering plus the general-purpose filter compiler.

    SQL files under `query/sql/` and `data_cleaning/sql/` are Jinja templates, so
    they can be linted with sqlfluff (`uv run sqlfluff lint query/sql
    data_cleaning/sql` from `backend/`; lint-time template context lives in
    `backend/.sqlfluff`).

    Python compiles FilterSource objects into SQL fragments (filter CTEs, joins,
    and WHERE clauses) and injects them through the Jinja context. This keeps the
    filter mechanism general purpose: the same compiled filters can be joined onto
    any specialized query template.

    Filter *values* are never interpolated into the SQL text. The compiler emits
    DuckDB numbered placeholders ($1, $2, ...) and collects the values into a
    params list, so callers execute with `DB.execute(sql, params)` and user input
    cannot alter the query. Column and table names still appear literally, but
    those come from server-side schema config, not from requests.

    EG:
    ```
    sql, params = sql_filter_block(sql_path / "acs5_tidy.sql", [source])
    # sql:    ... WHERE "NAME" IN ($1) AND TRY_CAST("year" AS DOUBLE) >= $2 ...
    # params: ['Vergennes', 2015.0, 2020.0]
    result = DB.execute(sql, params).df()
    ```

    This module lives at the backend root, outside `query/`, on purpose: it is a
    separate concern with no database dependency, so `build/` -- which runs
    before the processed DB exists -- and the tests can import it without
    triggering `query/__init__.py`'s DB connection.
"""

import logging
from pathlib import Path

from jinja2 import Environment, StrictUndefined, meta

from api.models import FilterSource, RangeFilter

logger = logging.getLogger(__name__)

JINJA_ENV = Environment(undefined=StrictUndefined, keep_trailing_newline=True)


def render_sql(sql_path: Path, **context) -> str:
    """Render a Jinja SQL template file with the given context."""
    return JINJA_ENV.from_string(sql_path.read_text()).render(**context)


def _placeholder(value, params: list) -> str:
    """Register a filter value and return its $N placeholder."""
    params.append(value)
    return f"${len(params)}"


def filter_clauses(filters: dict | None, params: list) -> list[str]:
    """Compile a {column: value} mapping into SQL boolean clauses.

    Values are appended to `params` and referenced as $N placeholders, numbered
    by their (1-indexed) position in `params`.

    Filter values are either:
        a discrete list -> "IN"
        a RangeFilter -> ">= / <="
            NOTE: Range comparisons TRY_CAST the column to DOUBLE so they work on
            numeric columns and numbers stored as text (e.g. the ACS "year" column).
    """
    clauses: list[str] = []
    for col, values in (filters or {}).items():
        if values is None:
            continue

        if isinstance(values, RangeFilter):
            if values.min is not None:
                clauses.append(
                    f'TRY_CAST("{col}" AS DOUBLE) >= {_placeholder(values.min, params)}'
                )
            if values.max is not None:
                clauses.append(
                    f'TRY_CAST("{col}" AS DOUBLE) <= {_placeholder(values.max, params)}'
                )
            continue

        if not isinstance(values, (list, tuple, set)):
            values = [values]
        placeholders = ", ".join(_placeholder(v, params) for v in values)
        clauses.append(f'"{col}" IN ({placeholders})')

    return clauses


def compile_where(filters: dict | None, params: list) -> str:
    """Compile filters into a full WHERE clause ("" when there are no filters)."""
    clauses = filter_clauses(filters, params)
    return ("WHERE " + " AND ".join(clauses)) if clauses else ""


def compile_cte(filter_source: FilterSource, params: list) -> str:
    where_string = compile_where(filter_source.filters, params)
    return (
        f"SELECT DISTINCT {filter_source.join_key} "
        f"FROM {filter_source.filter_table} {where_string}"
    ).strip()


def compile_join(src: FilterSource, i: int) -> str:
    match src.join_type:
        case "inner":
            return f"JOIN f{i} USING ({src.join_key})"
        case "left":
            return f"LEFT JOIN f{i} USING ({src.join_key})"
        case "spatial_intersect":
            return f"JOIN f{i} ON ST_Intersects(g.geom, f{i}.geom)"
        case _:
            raise ValueError("No logic for that join type")


def compile_filters(sources: list[FilterSource], params: list) -> tuple[str, str]:
    ctes, joins = [], []
    for i, src in enumerate(sources):
        ctes.append(f"f{i} AS ({compile_cte(src, params)})")
        joins.append(compile_join(src, i))
    cte_block = ("WITH " + ",\n".join(ctes)) if ctes else ""
    join_block = "\n".join(joins)
    return cte_block, join_block


def sql_filter_block(sql_path: Path, sources: list[FilterSource]) -> tuple[str, list]:
    """Render a query template with compiled filters; returns (sql, params).

    Only the fragments the template actually references are compiled, so `params`
    contains exactly the values behind the $N placeholders present in the SQL.
    Execute with `DB.execute(sql, params)`.
    """
    source_text = sql_path.read_text()
    used = meta.find_undeclared_variables(JINJA_ENV.parse(source_text))

    params: list = []
    context: dict = {}
    if used & {"cte_filter_block", "join_filter_block"}:
        cte_block, join_block = compile_filters(sources, params)
        context["cte_filter_block"] = cte_block
        context["join_filter_block"] = join_block
    if "where_string" in used:
        # Direct single-table filtering: apply the first source's filters straight
        # to the main query. {{ table }} resolves to that source so one template
        # can serve multiple tables (e.g. ACS).
        context["where_string"] = compile_where(
            sources[0].filters if sources else None, params
        )
    if "table" in used:
        context["table"] = sources[0].filter_table

    sql = JINJA_ENV.from_string(source_text).render(**context)
    return sql, params
