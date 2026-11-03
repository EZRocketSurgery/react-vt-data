"""Bounded, parameterized warehouse operations shared by every agent transport.

Only identifiers from the server-owned catalog enter SQL. Client inputs are values.
Each call owns a read-only connection, a concurrency slot and an interrupt deadline.
"""

import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from . import catalog
from .models import TOOL_MODELS, QueryData
from .query_diagnostics import empty_filter_hints, filter_clause


class DataToolError(ValueError):
    """A safe, actionable error that may be shown to a tool client."""


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def json_bytes(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def clean_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) and value > -100_000_000 else None
    if isinstance(value, int) and value <= -100_000_000:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        raise DataToolError("Binary data is not available through tabular tools")
    if isinstance(value, (list, tuple)):
        return [clean_value(x) for x in value]
    return value


class DeadlineConnection:
    """Check the whole-call deadline between each catalog/query statement."""

    def __init__(self, connection, expired):
        self._connection = connection
        self._expired = expired

    def execute(self, *args, **kwargs):
        if self._expired.is_set():
            raise DataToolError("Query exceeded its time limit; narrow the filters")
        result = self._connection.execute(*args, **kwargs)
        if self._expired.is_set():
            raise DataToolError("Query exceeded its time limit; narrow the filters")
        return result


class DataToolService:
    def __init__(
        self,
        warehouse_path: str | Path | None = None,
        *,
        max_rows: int = 1000,
        max_bytes: int = 1_000_000,
        query_timeout: float = 20,
        max_concurrency: int = 4,
    ):
        default_dir = Path(__file__).resolve().parents[1] / "Data"
        self.warehouse_path = (
            Path(warehouse_path)
            if warehouse_path
            else Path(os.environ.get("DATA_DIR", default_dir)) / "warehouse.duckdb"
        )
        if not (1 <= max_rows <= 1000 and 4096 <= max_bytes <= 10_000_000):
            raise ValueError("max_rows must be 1..1000 and max_bytes 4096..10000000")
        if not (0 < query_timeout <= 300 and 1 <= max_concurrency <= 32):
            raise ValueError("Invalid query timeout or concurrency limit")
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.query_timeout = query_timeout
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._cursor_key = secrets.token_bytes(32)

    def _version(self):
        try:
            stat = self.warehouse_path.stat()
        except OSError as exc:
            raise DataToolError(
                "Warehouse unavailable. Build it with just load-data or configure DATA_DIR."
            ) from exc
        signature = f"{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"
        return {
            "warehouse_version": hashlib.sha256(signature.encode()).hexdigest()[:24],
            "warehouse_modified_at": datetime.fromtimestamp(
                stat.st_mtime, UTC
            ).isoformat(),
        }

    @contextmanager
    def _connection(self):
        if not self._slots.acquire(timeout=0.1):
            raise DataToolError("Server is busy; retry the request shortly")
        conn = None
        timer = None
        expired = threading.Event()
        stopped = threading.Event()
        try:
            self._version()  # Never let DuckDB create a missing warehouse.
            conn = duckdb.connect(str(self.warehouse_path), read_only=True)

            def interrupt():
                expired.set()
                # Repeat until the call unwinds: an interrupt immediately before
                # execute() must not leave the subsequent statement unbounded.
                while not stopped.is_set():
                    conn.interrupt()
                    stopped.wait(0.02)

            timer = threading.Timer(self.query_timeout, interrupt)
            timer.daemon = True
            timer.start()
            yield DeadlineConnection(conn, expired)
            if expired.is_set():
                raise DataToolError("Query exceeded its time limit; narrow the filters")
        except duckdb.InterruptException as exc:
            raise DataToolError(
                "Query exceeded its time limit; narrow the filters"
            ) from exc
        except duckdb.Error as exc:
            raise DataToolError(
                "The requested warehouse query could not run. Check dataset availability and filter value types."
            ) from exc
        finally:
            if timer:
                stopped.set()
                timer.cancel()
                timer.join()
            if conn:
                conn.close()
            self._slots.release()

    def health(self) -> dict:
        version = self._version()
        with self._connection() as conn:
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
            available = sum(ds.table in tables for ds in catalog.DATASETS.values())
            if not available:
                raise DataToolError("Warehouse has no supported datasets")
        return {"status": "ok", "available_datasets": available, **version}

    def call(self, tool_name: str, arguments: dict) -> dict:
        if tool_name not in TOOL_MODELS:
            raise DataToolError("Unknown data tool")
        request = TOOL_MODELS[tool_name].model_validate(arguments)
        version = self._version()
        with self._connection() as conn:
            if tool_name == "list_datasets":
                result = {"datasets": catalog.list_datasets(conn, request.query)}
            elif tool_name == "describe_dataset":
                result = catalog.describe_dataset(
                    conn,
                    request.dataset_id,
                    value_column=request.value_column,
                    value_filters=request.value_filters,
                    value_limit=request.value_limit,
                )
            elif tool_name == "search_variables":
                result = {
                    "dataset_id": request.dataset_id,
                    "variables": catalog.search_variables(
                        conn, request.dataset_id, request.query, request.limit
                    ),
                }
                result["limit"] = request.limit
                result["may_have_more"] = len(result["variables"]) == request.limit
            elif tool_name == "search_locations":
                result = {
                    "locations": catalog.search_locations(
                        conn, request.query, request.geo_type, request.limit
                    )
                }
                result["limit"] = request.limit
                result["may_have_more"] = len(result["locations"]) == request.limit
            elif tool_name == "get_zoning_summary":
                result = self._zoning(conn, request, version)
            else:
                result = self._query(conn, request, tool_name, version)
            if self._version()["warehouse_version"] != version["warehouse_version"]:
                raise DataToolError(
                    "Warehouse changed during this request; retry from the first page"
                )
        result.update(version)
        if len(json_bytes(result)) > self.max_bytes:
            raise DataToolError(
                "Result exceeds the byte limit; narrow the query or request a smaller page"
            )
        return result

    def _cursor(self, offset, fingerprint, version):
        payload = json_bytes(
            {
                "offset": offset,
                "query": fingerprint,
                "version": version["warehouse_version"],
            }
        )
        signature = hmac.digest(self._cursor_key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def _offset(self, cursor, fingerprint, version):
        if cursor is None:
            return 0
        try:
            decoded = base64.b64decode(
                cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
            )
            signature, payload = decoded[:32], decoded[32:]
            if not hmac.compare_digest(
                signature, hmac.digest(self._cursor_key, payload, "sha256")
            ):
                raise ValueError
            data = json.loads(payload)
            if (
                data["query"] != fingerprint
                or data["version"] != version["warehouse_version"]
            ):
                raise ValueError
            offset = data["offset"]
            if type(offset) is not int or not 0 <= offset < 2**63:
                raise ValueError
            return offset
        except (ValueError, KeyError, TypeError) as exc:
            raise DataToolError(
                "Invalid or stale cursor. Keep the same query arguments, or restart from the first page."
            ) from exc

    def _fingerprint(self, tool, request):
        data = request.model_dump(exclude={"cursor"})
        return hashlib.sha256(json_bytes({"tool": tool, "args": data})).hexdigest()

    def _schema(self, conn, ds):
        try:
            fields = conn.execute(f"DESCRIBE {quote(ds.table)}").fetchall()
        except duckdb.CatalogException as exc:
            raise DataToolError(
                f"Dataset {ds.id} is unavailable in this warehouse"
            ) from exc
        return {
            row[0]: row[1]
            for row in fields
            if row[1] not in ("GEOMETRY", "BLOB")
            and row[0].lower() not in ("geometry", "geom", "rgba_color", "geolocation")
        }

    def _columns(self, conn, ds):
        return list(self._schema(conn, ds))

    def _locations(self, conn, ids):
        all_places = catalog.build_locations(conn)
        index = {place["id"]: place for place in all_places}
        unknown = [item for item in ids if item not in index]
        if unknown:
            raise DataToolError(
                "Unknown location IDs: "
                + ", ".join(unknown)
                + ". Use search_locations."
            )
        return [index[item] for item in dict.fromkeys(ids)]

    def _location_clause(self, ds, locations):
        if not ds.name_column and not ds.id_column:
            raise DataToolError(
                f"Dataset {ds.id} does not support location filters; use its advertised fields"
            )
        parts, params = [], []
        for place in locations:
            if ds.fixed_geo_type and place["geo_type"] != ds.fixed_geo_type:
                raise DataToolError(
                    f"Dataset {ds.id} supports {ds.fixed_geo_type} locations"
                )
            if ds.id_column:
                expression = f"regexp_replace(CAST({quote(ds.id_column)} AS VARCHAR), '\\.0$', '')"
                parts.append(f"{expression} = ?")
                params.append(place["geoid"])
            else:
                names = list(dict.fromkeys([place["name"], *place.get("aliases", [])]))
                sub = f"lower(trim(CAST({quote(ds.name_column)} AS VARCHAR))) IN ({','.join('?' for _ in names)})"
                values = [name.lower().strip() for name in names]
                if ds.geo_type_column:
                    sub += f" AND {self._geo_expression(ds)} = ?"
                    values.append(place["geo_type"])
                parts.append(f"({sub})")
                params.extend(values)
        return "(" + " OR ".join(parts) + ")", params

    @staticmethod
    def _geo_expression(ds):
        col = quote(ds.geo_type_column)
        return f"CASE WHEN {col} IN ('town', 'municipality') THEN 'county_subdivision' ELSE {col} END"

    def _where(self, ds, request, locations, column_types=None, location_clause=None):
        clauses, params = [], []
        if locations:
            clause, values = location_clause or self._location_clause(ds, locations)
            clauses.append(clause)
            params.extend(values)
        if request.geo_type:
            if ds.geo_type_column:
                clauses.append(self._geo_expression(ds) + " = ?")
                params.append(request.geo_type)
            elif ds.fixed_geo_type:
                if request.geo_type != ds.fixed_geo_type:
                    raise DataToolError(
                        f"Dataset {ds.id} supports geography type {ds.fixed_geo_type}"
                    )
            elif ds.name_column and locations:
                if any(place["geo_type"] != request.geo_type for place in locations):
                    raise DataToolError("Location IDs do not match geo_type")
            else:
                raise DataToolError(
                    "This dataset has no geography-type field; select explicit location_ids"
                )
        if (
            request.years
            or request.year_min is not None
            or request.year_max is not None
        ):
            if not ds.year_column:
                raise DataToolError(
                    "This dataset has no observation year; year filters are unsupported"
                )
            year_expr = f"TRY_CAST({quote(ds.year_column)} AS INTEGER)"
            if request.years:
                clauses.append(
                    f"{year_expr} IN ({','.join('?' for _ in request.years)})"
                )
                params.extend(request.years)
            for operator, value in ((">=", request.year_min), ("<=", request.year_max)):
                if value is not None:
                    clauses.append(f"{year_expr} {operator} ?")
                    params.append(value)
        for field, values in request.filters.items():
            if field not in ds.filter_columns:
                raise DataToolError(
                    f"Unsupported filter {field!r}. Allowed fields: {', '.join(ds.filter_columns)}"
                )
            if column_types is not None and field not in column_types:
                raise DataToolError(
                    f"Filter {field!r} is not available in this warehouse"
                )
            clause, filter_values = filter_clause(
                field, values, (column_types or {}).get(field, "VARCHAR")
            )
            clauses.append(clause)
            params.extend(filter_values)
        variable_parts, selected_columns = [], []
        for variable_id in request.variable_ids:
            selector = catalog.decode_variable_id(ds, variable_id)
            if "$column" in selector:
                selected_columns.append(selector["$column"])
            else:
                subset = []
                for key, val in selector.items():
                    if val is None:
                        subset.append(f"{quote(key)} IS NULL")
                    else:
                        subset.append(f"{quote(key)} = ?")
                        params.append(val)
                if subset:
                    variable_parts.append("(" + " AND ".join(subset) + ")")
        if variable_parts:
            clauses.append("(" + " OR ".join(variable_parts) + ")")
        measures = request.measures or selected_columns or list(ds.value_columns)
        if set(measures) - set(ds.value_columns):
            raise DataToolError(
                f"Unsupported measures. Allowed: {', '.join(ds.value_columns)}"
            )
        margins = set(catalog.with_margins(ds, selected_columns)) - set(
            selected_columns
        )
        if (
            request.measures
            and selected_columns
            and set(request.measures) - margins != set(selected_columns)
        ):
            raise DataToolError(
                "measures must match the selected wide-column variable IDs"
            )
        return (
            " AND ".join(clauses) or "TRUE",
            params,
            catalog.with_margins(ds, measures),
        )

    def _query(self, conn, request, tool, version):
        ds = catalog.get_dataset(request.dataset_id)
        column_types = self._schema(conn, ds)
        source_columns = list(column_types)
        locations = (
            self._locations(conn, request.location_ids) if request.location_ids else []
        )
        if request.geo_type and any(
            place["geo_type"] != request.geo_type for place in locations
        ):
            raise DataToolError("Location IDs do not match geo_type")
        if tool in ("get_timeseries", "compare_places") and not ds.year_column:
            raise DataToolError(f"{tool} requires a dataset with observation years")
        fingerprint = self._fingerprint(tool, request)
        offset = self._offset(request.cursor, fingerprint, version)
        comparison = None
        if tool == "compare_places":
            if len({p["geo_type"] for p in locations}) != 1:
                raise DataToolError(
                    "Comparisons require locations at one geography level"
                )
            comparison = self._comparison_year(
                conn, ds, request, locations, column_types
            )
            request = QueryData.model_validate(
                request.model_dump(exclude={"year_policy"}) | {"years": [comparison]}
            )

        result_locations = locations
        if not result_locations and (ds.name_column or ds.id_column):
            result_locations = catalog.build_locations(conn)
        location_diagnostics = None
        location_clause = None
        if ds.id in ("zoning_districts", "zoning_bylaws"):
            from .zoning import resolve_zoning_locations

            predicate, parameters, location_diagnostics = resolve_zoning_locations(
                conn,
                locations
                or [
                    p for p in result_locations if p["geo_type"] == "county_subdivision"
                ],
                table=ds.table,
            )
            if locations:
                location_clause = (predicate, parameters)

        where, params, measures = self._where(
            ds, request, locations, column_types, location_clause
        )
        available = [
            col
            for col in source_columns
            if col not in ds.value_columns or col in measures
        ]
        computed = []
        if ds.name_column or ds.id_column:
            computed.append("_location_id")
        if ds.kind in ("tidy", "dp"):
            computed.append("_units")
        if request.columns is not None:
            unknown = set(request.columns) - set(available + computed)
            if unknown:
                raise DataToolError(
                    "Unsupported output columns: "
                    + ", ".join(sorted(unknown))
                    + ". Use describe_dataset; numeric columns must also be included in measures when measures is specified."
                )
            output_columns = list(dict.fromkeys(request.columns))
        else:
            output_columns = available + [
                field
                for field in computed
                if field != "_units" or request.include_row_units
            ]
        if not output_columns:
            raise DataToolError("No tabular columns available")
        # Fetch the small set of hidden identity/unit fields needed to interpret a
        # projection. Sort by the complete source row so paging is deterministic
        # even when callers select only a non-unique column.
        required = {
            ds.year_column,
            ds.name_column,
            ds.id_column,
            ds.geo_type_column,
            *ds.variable_columns,
        }
        if "_units" in output_columns:
            required.update(measures)
        selected = [
            col for col in source_columns if col in output_columns or col in required
        ]
        if not selected:
            selected = source_columns[:1]
        order = (
            [f"TRY_CAST({quote(ds.year_column)} AS INTEGER)"] if ds.year_column else []
        ) + [quote(col) for col in source_columns]
        limit = min(request.limit, self.max_rows)
        sql = f"SELECT {', '.join(quote(col) for col in selected)} FROM {quote(ds.table)} WHERE {where} ORDER BY {', '.join(order)} LIMIT ? OFFSET ?"
        raw_rows = conn.execute(sql, params + [limit + 1, offset]).fetchall()
        normalized = [
            self._normalize_row(
                dict(zip(selected, row)), ds, measures, result_locations
            )
            for row in raw_rows[:limit]
        ]
        if location_diagnostics is not None:
            from .zoning import zoning_location_id

            for row in normalized:
                row["_location_id"] = zoning_location_id(row, location_diagnostics)
        rows = [{col: row.get(col) for col in output_columns} for row in normalized]
        result = {
            "dataset_id": ds.id,
            "columns": output_columns,
            "units": {
                key: ds.value_columns[key] for key in measures if key in output_columns
            },
            "rows": rows,
            "provenance": self._provenance(ds),
            "applied_query": request.model_dump(exclude={"cursor"}),
            **version,
        }
        if "_units" in computed and "_units" not in output_columns:
            result["unit_note"] = (
                "Selected variables can have different units. Include _units in columns for row-specific units; source labels and provenance remain authoritative."
            )
        if location_diagnostics is not None:
            result["location_diagnostics"] = {
                key: value
                for key, value in location_diagnostics.items()
                if key != "municipality_location_ids"
            }
        suspect_units = sum(bool(row.get("_unit_issue")) for row in normalized)
        if suspect_units:
            result["warnings"] = [
                {
                    "code": "unverified_profile_units",
                    "message": "Some percent-labelled profile rows contain totals or values outside 0–100. Their source values are preserved, but units are marked unverified; do not interpret them as percentages.",
                }
            ]
        if comparison is not None:
            result["comparison_year"] = comparison
            result["year_policy"] = (
                "common observation year; no aggregation across places"
            )
            result["requested_locations"] = locations
        if tool == "get_timeseries" or (not rows and ds.year_column):
            coverage, hints = self._query_coverage(
                conn, ds, request, locations, column_types
            )
            result["coverage"] = coverage
            if hints:
                result["hints"] = hints
        if not rows and offset == 0:
            result.setdefault("hints", []).extend(
                empty_filter_hints(conn, ds, request.filters, column_types)
            )
        return self._bound_rows(
            result,
            rows,
            len(raw_rows) > limit,
            offset,
            fingerprint,
            version,
            export=tool == "export_data",
        )

    def _query_coverage(self, conn, ds, request, locations, column_types):
        base = QueryData.model_validate(
            request.model_dump()
            | {
                "years": [],
                "year_min": None,
                "year_max": None,
                "cursor": None,
                "filters": {
                    key: values
                    for key, values in request.filters.items()
                    if key != ds.year_column
                },
            }
        )
        where, params, _ = self._where(ds, base, locations, column_types)
        year = f"TRY_CAST({quote(ds.year_column)} AS INTEGER)"

        def years_for(condition, values):
            return [
                row[0]
                for row in conn.execute(
                    f"SELECT DISTINCT {year} FROM {quote(ds.table)} WHERE ({condition}) AND {year} BETWEEN 1700 AND 2200 ORDER BY 1",
                    values,
                ).fetchall()
            ]

        selected_years = years_for(where, params)
        dataset_years = years_for("TRUE", [])
        requested = list(request.years)
        if not requested and (
            request.year_min is not None or request.year_max is not None
        ):
            low = (
                request.year_min
                if request.year_min is not None
                else min(dataset_years, default=1700)
            )
            high = (
                request.year_max
                if request.year_max is not None
                else max(dataset_years, default=2200)
            )
            # Retain an explicit bound when an open-ended range is entirely
            # outside observed years; an empty range would lose the constraint.
            if request.year_max is None:
                high = max(low, high)
            if request.year_min is None:
                low = min(low, high)
            requested = list(range(low, high + 1))
        if not requested and ds.year_column in request.filters:
            requested = [
                int(value)
                for value in request.filters[ds.year_column]
                if str(value).isdigit()
            ]
        expected = requested or dataset_years
        missing = sorted(set(expected) - set(selected_years))
        coverage = {
            "selector_years_available": selected_years,
            "dataset_years_available": dataset_years,
            "requested_years": sorted(set(requested)) if requested else None,
            "requested_year_min": request.year_min,
            "requested_year_max": request.year_max,
            "years_without_matching_observations": missing,
            "note": "Coverage is the union of years with source rows for these exact selectors and locations before year constraints, including unavailable values. It does not guarantee every variable/place pair is present. Other labels or geographies may cover different years; no automatic crosswalk or interpolation is applied.",
        }
        hints = []
        if missing:
            hints.append(
                {
                    "code": "selector_year_coverage",
                    "years": missing,
                    "message": "These years have no observations for the selected variables/places. Search variable variants and inspect describe_dataset coverage before concluding the logical series is unavailable.",
                }
            )
        return coverage, hints

    @staticmethod
    def _provenance(ds):
        return {
            "source_name": ds.source_name,
            "source_url": ds.source_url,
            **catalog.provenance_metadata(ds),
            "caveats": list(ds.caveats),
            "missing_values": "null means unavailable, suppressed, invalid or missing; it is not zero. Census sentinel values are normalized to null.",
            "warehouse_timestamp_note": "Warehouse modification time is not the source publication date.",
        }

    @staticmethod
    def _normalize_row(row, ds, measures, locations):
        row = {key: clean_value(value) for key, value in row.items()}
        for field in measures:
            value = row.get(field)
            if isinstance(value, str):
                try:
                    row[field] = clean_value(float(value.replace(",", "")))
                except ValueError:
                    row[field] = None
        if ds.year_column and row.get(ds.year_column) is not None:
            row[ds.year_column] = int(row[ds.year_column])
        if ds.kind in ("tidy", "dp"):
            selectors = {key: row.get(key) for key in ds.variable_columns}
            row["_units"] = {
                field: unit
                for field, unit in catalog.variable_units(ds, selectors).items()
                if field in measures
            }
            value = row.get("value")
            if ds.kind == "dp" and "percent" in str(row.get("measure", "")).lower():
                if isinstance(value, (float, int)) and not 0 <= value <= 100:
                    row["_units"]["value"] = "source value; unit not verified"
                    row["_unit_issue"] = True
                elif value is not None and "not verified" in row["_units"].get(
                    "value", ""
                ):
                    row["_unit_issue"] = True
        if locations:
            matches = []
            for place in locations:
                if ds.fixed_geo_type and place["geo_type"] != ds.fixed_geo_type:
                    continue
                if ds.geo_type_column:
                    row_type = row.get(ds.geo_type_column)
                    row_type = (
                        "county_subdivision"
                        if row_type in ("town", "municipality")
                        else row_type
                    )
                    if row_type != place["geo_type"]:
                        continue
                if ds.id_column:
                    actual = str(row.get(ds.id_column, "")).removesuffix(".0")
                    match = actual == place["geoid"]
                else:
                    actual = str(row.get(ds.name_column, "")).lower().strip()
                    match = actual in {
                        str(n).lower().strip()
                        for n in [place["name"], *place.get("aliases", [])]
                    }
                if match:
                    matches.append(place)
            if len(matches) == 1:
                row["_location_id"] = matches[0]["id"]
            else:
                row["_location_id"] = None
        return row

    def _comparison_year(self, conn, ds, request, locations, column_types):
        common = None
        for place in locations:
            for variable in request.variable_ids:
                per_place = QueryData.model_validate(
                    request.model_dump(exclude={"year_policy"})
                    | {
                        "location_ids": [place["id"]],
                        "variable_ids": [variable],
                        "measures": [],
                    }
                )
                where, values, _ = self._where(ds, per_place, [place], column_types)
                year = f"TRY_CAST({quote(ds.year_column)} AS INTEGER)"
                available = {
                    row[0]
                    for row in conn.execute(
                        f"SELECT DISTINCT {year} FROM {quote(ds.table)} WHERE {where} AND {year} IS NOT NULL",
                        values,
                    ).fetchall()
                }
                common = available if common is None else common & available
        if not common:
            raise DataToolError(
                "No common observation year for all requested places and filters"
            )
        return max(common)

    def _bound_rows(
        self, result, rows, has_more, offset, fingerprint, version, *, export=False
    ):
        while True:
            result.update(
                row_count=len(rows),
                has_more=has_more,
                next_cursor=self._cursor(offset + len(rows), fingerprint, version)
                if has_more
                else None,
            )
            if export:
                output = io.StringIO(newline="")
                fields = list(result["columns"])
                writer = csv.DictWriter(
                    output,
                    fieldnames=fields,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {key: self._csv_cell(row.get(key)) for key in fields}
                    )
                result.update(
                    csv=output.getvalue(),
                    media_type="text/csv",
                    filename=f"vt-data-{result['dataset_id']}.csv",
                    truncated=has_more,
                )
                result.pop("rows", None)
            else:
                result["rows"] = rows
            if len(json_bytes(result)) <= self.max_bytes:
                return result
            if not rows or len(rows) == 1:
                raise DataToolError(
                    "A result row exceeds the byte limit; select fewer fields or narrower filters"
                )
            rows = rows[: max(1, len(rows) // 2)]
            has_more = True

    @staticmethod
    def _csv_cell(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value

    def _zoning(self, conn, request, version):
        from .zoning import zoning_summary

        ds = catalog.get_dataset("zoning_districts")
        self._columns(conn, ds)
        fingerprint = self._fingerprint("get_zoning_summary", request)
        offset = self._offset(request.cursor, fingerprint, version)
        limit = min(request.limit, self.max_rows)
        result = zoning_summary(conn, request, limit, offset)
        rows = [
            {key: clean_value(value) for key, value in row.items()}
            for row in result.pop("rows")
        ]
        has_more = result.pop("has_more")
        diagnostics = result.get("location_diagnostics", {})
        diagnostics.pop("municipality_location_ids", None)
        result.update(
            dataset_id=ds.id,
            provenance=self._provenance(ds),
            applied_query=request.model_dump(exclude={"cursor"}),
            **version,
        )
        if not rows and offset == 0:
            result.setdefault("hints", []).append(
                {
                    "code": "no_matching_zoning_districts",
                    "message": "No districts match this scope and overlay policy. Check excluded_overlays, inspect municipality values with describe_dataset(value_column='town'), or use a canonical location_id.",
                }
            )
        return self._bound_rows(result, rows, has_more, offset, fingerprint, version)
