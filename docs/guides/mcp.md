# Vermont data MCP

The MCP server exposes nine read-only tools for discovering, querying, comparing,
and exporting the data in `warehouse.duckdb`. An external report-writing agent and
the application's internal agent can use the same tools over Streamable HTTP.
The underlying Python service and Pydantic input models can also be reused in
process, without maintaining a second tool implementation.

The MCP endpoint is `/api/mcp`. It is opt-in on the existing API, and can run as a
separate local process for development. No frontend changes or agent framework
are required to use it.

HTTP tool calls use stateless POST requests with JSON responses. The server does
not offer a standalone event stream: authenticated GET requests to `/api/mcp`
return `405 Method Not Allowed` with `Allow: POST`, as permitted by
[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#listening-for-messages-from-the-server).
These probes are rejected before taking a concurrency slot, so idle client
connections cannot occupy tool capacity. GET `/api/mcp/health` remains available.

## 1. Try it locally without authentication

Prerequisites: Python 3.13, `uv`, `just`, Claude Code, and an existing
`backend/Data/warehouse.duckdb`. MCP reads the warehouse; it does not download data
or build the warehouse on startup. See [Preparing the warehouse](#preparing-the-warehouse)
if that file is missing. Run these commands from the repository root.

```sh
just mcp
```

Without `just`, the equivalent command from the repository root is:

```sh
cd backend
uv run python -m mcp_server
```

The default bind is `127.0.0.1:6768`, and the default standalone authentication mode
is `none`. Existing `MCP_AUTH_MODE` values in your environment or `.env` take
precedence. For an explicit unauthenticated run:

```sh
MCP_AUTH_MODE=none just mcp
```

Keep that terminal open. In another terminal, register the server for the current
Claude Code project:

```sh
claude mcp add --transport http --scope local vt-data http://127.0.0.1:6768/api/mcp
claude mcp get vt-data
```

Open Claude Code and use `/mcp` to check its connection. Try:

> Use vt-data to discover the available housing datasets. Find Burlington city
> and Montpelier city, describe the dataset and its units, then compare their
> median home values for the latest year both have. Include the year, sources,
> and any data caveats in the report. Do not average medians or invent missing
> values.

The tool discovery response should list all nine tools below. Start with
`list_datasets`, `describe_dataset`, `search_variables`, and `search_locations`;
pass their returned IDs into subsequent calls. Dataset availability and year
coverage come from your local warehouse, so a different deployment can contain
different years or missing datasets.

The catalog includes ACS summary and detailed-profile data, Census historic
population, employment by sector, CDC health indicators, zoning, wastewater,
ambulance service areas, and flood-hazard attributes. Geometry columns are
excluded from these report-oriented tools.

The web application can continue to run on ports 3000/6767 while this standalone
MCP uses 6768. No-auth and development-token standalone modes are restricted to
loopback; they are not deployment modes.

For an agent-managed local subprocess, stdio is also supported. It needs no
listening port or bearer header. Replace the example checkout path:

```sh
claude mcp add --transport stdio --scope local vt-data-stdio -- \
  just --quiet --justfile /absolute/path/react-vt-data/justfile mcp-stdio
```

## 2. Try the development bearer token

Stop the first server with Ctrl-C, then run:

```sh
just mcp-dev-auth
```

This explicitly enables the hardcoded, public test token:

```text
vt-data-local-development-token
```

Replace the local Claude Code registration:

```sh
claude mcp remove vt-data
claude mcp add --transport http --scope local \
  --header "Authorization: Bearer vt-data-local-development-token" \
  vt-data http://127.0.0.1:6768/api/mcp
```

Requests without the header or with an incorrect token receive HTTP 401,
including discovery and the health route. This token is deliberately public and
is accepted only in `development` mode. Production bearer mode rejects it.

The CLI commands follow the [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).
This implementation uses fixed bearer headers, not an OAuth login flow. Clients
must support configuring an `Authorization` header; an OAuth-only connector needs
an authorization integration before it can connect.

## 3. Configure production bearer tokens

Use one random token per consumer so you can revoke or rotate consumers
independently. Generate each token with:

```sh
just mcp-token
```

Store the generated values in the VM's untracked `.env` or your deployment secret
store. For two consumers, the configuration is:

```dotenv
MCP_ENABLED=true
MCP_AUTH_MODE=bearer
MCP_BEARER_TOKENS=<first-generated-token>,<second-generated-token>
MCP_ALLOWED_HOSTS=data.example.org,localhost:*,127.0.0.1:*
MCP_ALLOWED_ORIGINS=https://data.example.org
```

Replace the example host and placeholder tokens. Never put production tokens in
the repository, frontend environment variables, URL query strings, or a shared
`.mcp.json`. Container recipes pass the named environment variables through to
the API; they do not put token values in the Podman command arguments.

All tokens currently grant the same read-only permissions. This is a simple
allowlist, not a user database: there are no token-specific scopes, automatic
expiry, OAuth discovery, or self-service token management. To rotate a token, add
its replacement, restart the service, update the client, then remove the old token
and restart again. To revoke one, remove it and restart. Give the internal agent
its own token if it connects over HTTP.

The allowlist accepts up to 32 distinct tokens of 32–512 ASCII characters without
whitespace. `just mcp-token` generates a value meeting these requirements.

The allowlist supports at most 32 distinct tokens. Each production token must
contain 32–512 ASCII characters with no whitespace and must differ from the
development token. Whitespace around comma-separated entries is trimmed.

For Claude Code, an untracked local configuration can read a token from the
environment. This example illustrates the client configuration; substitute your
actual deployment URL:

```json
{
  "mcpServers": {
    "vt-data": {
      "type": "http",
      "url": "https://data.example.org/api/mcp",
      "headers": {
        "Authorization": "Bearer ${VT_DATA_MCP_TOKEN}"
      }
    }
  }
}
```

Set `VT_DATA_MCP_TOKEN` in the environment of the Claude Code process. This is a
client variable; the server reads `MCP_BEARER_TOKENS` instead.

## Tool contract

| Tool                 | Purpose and important inputs                                                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `list_datasets`      | Discover registered datasets, actual availability, coverage, and source information. Optional `query` searches the catalog.                                                                                                                                              |
| `describe_dataset`   | Inspect one `dataset_id`, including fields, measures, units, lineage, and coverage by geography. Use `value_column`, optional `value_filters`, and `value_limit` to discover distinct filter values.                                                                     |
| `search_variables`   | Search words across source selector fields within a `dataset_id`; returns stable `variable_ids` and each variant's actual years. Accepts `query` and `limit`.                                                                                                            |
| `search_locations`   | Resolve a place name into canonical geography IDs, with optional `geo_type`. Town, city, and county candidates remain distinct.                                                                                                                                          |
| `query_data`         | Fetch one bounded page from a `dataset_id`. Supports `location_ids`, `geo_type`, `variable_ids`, `measures`, `columns`, advertised `filters`, and either `years` or `year_min`/`year_max`. Text filters ignore case and surrounding whitespace.                          |
| `get_timeseries`     | Retrieve temporal observations with the same selectors, ordered by year. Missing years remain missing; values are not interpolated.                                                                                                                                      |
| `compare_places`     | Compare selected `variable_ids` for 2–20 locations at a common geography level and year. Default `year_policy="latest_common"`; use `year_policy="explicit"` with `years=[2023]` to request a particular year.                                                           |
| `get_zoning_summary` | Summarize district counts and recorded acreage by municipality and district type. Select `municipality` or canonical `location_id`, with optional `county`. Overlays are excluded unless `include_overlays=true`; `excluded_overlays` reconciles their counts and acres. |
| `export_data`        | Return a bounded CSV page inline using the `query_data` selectors, with provenance and a continuation cursor. Spreadsheet formula cells are escaped.                                                                                                                     |

`query_data`, `get_timeseries`, `compare_places`, `get_zoning_summary`, and
`export_data` accept `limit` and `cursor`. Follow a returned `next_cursor` with
the same query arguments to continue. Do not manufacture cursor values or reuse
them with a different query. Limits bound each response; an export is a page, not
an unbounded warehouse dump. Save the returned CSV string in the agent's local
workspace. This version does not create server-side export files or download URLs.

Page cursors are signed with a per-process key and tied to the query and warehouse
version. They become invalid after restarting the service, replacing the
warehouse, or sending the next page to a different worker. Restart pagination
from the first page in those cases; the initial deployment uses one worker.

Rows retain the source's column names. Response metadata describes column units;
mixed-measure rows also include `_units`. Source values are preserved except for
documented numeric/missing-value conversion; text matching does not rewrite the
returned source text. `warehouse_modified_at` describes the warehouse file, not
the date every source was refreshed. Use the returned source and year information
when citing a result.

Call `describe_dataset` before adding `filters`. Unknown datasets, columns,
variables, invalid filter shapes, and unsupported operations return explicit
errors instead of silently dropping constraints. There is no raw SQL tool,
arbitrary file access, write operation, or geometry export. The query layer uses
server-owned dataset identifiers and parameterized values with read-only DuckDB
connections.

### Compact queries and filter discovery

Use `columns` to request exactly the output fields needed by a report. It is
available on `query_data`, `get_timeseries`, `compare_places`, and `export_data`.
For example, this avoids fetching long notes and every housing-form standard:

```json
{
  "dataset_id": "zoning_bylaws",
  "location_ids": ["5002161225"],
  "columns": [
    "OBJECT_ID",
    "Municipal_Name",
    "District_Name",
    "Base_Density",
    "GEO_ID",
    "_location_id"
  ],
  "limit": 100
}
```

Projection does not change row selection, ordering, or pagination. Empty results
return the same `columns` as populated results. `measures` selects the eligible
numeric measures; if provided, it must include numeric fields requested in
`columns`. Computed `_location_id` and `_units` can be selected explicitly.
With no `columns`, `include_row_units=false` omits repeated row-unit dictionaries.
For mixed Census variables, keep `_units` unless the report has obtained and
retained each variable's units separately: top-level units may say “varies.”

To inspect valid values, call `describe_dataset` with an advertised filter field:

```json
{
  "dataset_id": "acs5_dp",
  "value_column": "Measure",
  "value_filters": { "table": ["DP04"], "year": [2017, 2018] },
  "value_limit": 50
}
```

The bounded `filter_values` result includes `values` and `has_more`. Narrow
`value_filters` when there are more values; this discovery list is not paginated.
Without `value_column`, `filter_values_by_column` supplies bounded examples for
low-cardinality fields. Unknown fields are rejected. Text filters match complete
values, ignoring case and outer whitespace; they do not perform substring or
fuzzy matching. Empty queries include `hints` with independent filter-match counts
and nearby source values. Hints never substitute a suggested value into a query.

### Historical coverage and source defects

`search_variables` matches all query words across selector fields, so
`GROSS RENT Median (dollars)` finds historical label variants. Each result reports
`years_available` and gaps. A `variable_id` still identifies exact source labels;
it does not merge different historical definitions into one logical series.
`get_timeseries.coverage` reports the selected variables/places' available years
before year constraints, the dataset's overall years, and years without matching
observations. Multi-variable/place coverage is their union, not a guarantee that
every combination is present. `describe_dataset.coverage_by_geo_type` exposes
geography-specific gaps such as absent 2010 town profiles. No missing years are
interpolated.

Detailed-profile total cells sometimes carry a percentage label while containing
counts. The tools preserve these numbers, use conservative unverified units, and
emit a warning instead of asserting they are percentages. Underlying duplicate
selector rows are also preserved; do not sum or arbitrarily deduplicate them.
Provenance includes the warehouse table and verified current collection/cleaning
references. Source-code notes distinguish current pipeline mappings from a full
historical, row-level code crosswalk.

Zoning `location_ids` are matched through unambiguous canonical municipality
names. This prevents a city's districts from leaking into its same-named town
when the source GEOID is wrong, and supports unambiguous names with missing source
IDs. Returned `GEO_ID` remains the raw source value; `_location_id` is the resolved
canonical subdivision. `location_diagnostics` reports conflicts, missing IDs,
and unresolved names with bounded previews. An ambiguous summary request such as
`municipality="Rutland"` returns an error listing city/town choices; select an
explicit name or `location_id`. Composite/village names are not automatically
split or assigned to a guessed subdivision.

`excluded_overlays` covers the full summary selection, independently of its
page size, and includes a bounded district preview. Source overlay flags control
exclusion even when a classification is disputed. Review the underlying follow-up
items in [the 2026-09-16 data issues](../reports/2026-09-16-data-issues.md); MCP safeguards do not
repair those warehouse records.

### Report interpretation

- Preserve the returned source, units, geography, year, and dataset version in
  generated reports. Source-year coverage does not imply the warehouse was
  refreshed today.
- Keep counts and percentages distinct. Do not sum the same observation across
  state, county, and town rows. Do not average medians or treat dollar values as
  inflation-adjusted unless the source explicitly says so.
- ACS five-year estimates describe overlapping survey periods; a timeseries is
  not a set of independent annual census counts. Preserve source caveats.
- Comparisons use one common year. The tools do not silently select different
  years for different places or impute missing observations.
- CDC `natl_pct` is a stored derived rank with an unverified reference population.
  Preserve the returned caveats and avoid treating it as a verified national
  benchmark. Filtering to one year or prevalence type does not recalculate ranks.
- QCEW `employment_4qma` is a stored rolling average that may use partial windows
  or carry averages through gaps. The current pipeline restarts it each year;
  it is not guaranteed to cover four consecutive observed quarters. Query filters
  do not recalculate these values.
- Zoning acres are sums of recorded district areas. They are not a dissolved GIS
  calculation, and overlapping districts can double-count land. Including
  overlays makes that limitation especially important.
- CSV exports are intended for report inputs. Apply the same interpretation
  rules to exported rows as to tool responses.

## Shared definitions for the internal agent

`backend/data_tools` owns the input models, catalog, validation, queries, and
response metadata. `backend/mcp_server` adapts those definitions to MCP and adds
HTTP access controls. The internal agent can connect to the same MCP URL and
exercise exactly the external contract.

An in-process integration can instead construct `DataToolService` and invoke
`call(tool_name, arguments)` with the shared models from
`data_tools.models.TOOL_MODELS`. This preserves tool names, argument validation,
query behavior, and limits. HTTP authentication and HTTP rate limits apply only
to the HTTP adapter; direct callers must be trusted application code. Keep any
future user-specific authorization in a common service layer if both access
paths need it.

```mermaid
flowchart LR
    External[External report agent] --> MCP[MCP HTTP adapter]
    Internal[Internal agent] --> MCP
    Internal -. optional direct call .-> Service[Shared data tool service]
    MCP --> Service
    Service --> Warehouse[(Read-only warehouse.duckdb)]
```

## Configuration

Configuration is read when a service instance starts. Restart after changing it.
The justfile loads the root `.env`; direct Python/Uvicorn invocations need exported
environment variables. See the committed [`.env.example`](../../.env.example).

| Variable                   | Default                                              | Meaning                                                                                                                                        |
| -------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATA_DIR`                 | `backend/Data` locally; `/data` in the API container | Directory containing the materialized `warehouse.duckdb`. Use an absolute host path when overriding it in `.env`.                              |
| `MCP_ENABLED`              | `false`                                              | Mount MCP in the existing FastAPI app. The standalone server does not need this flag.                                                          |
| `MCP_AUTH_MODE`            | `none` for standalone                                | `none`, `development`, or `bearer`. The existing API mount requires `bearer`.                                                                  |
| `MCP_BEARER_TOKENS`        | unset                                                | Comma-separated production token allowlist. Required in `bearer` mode.                                                                         |
| `MCP_HOST`                 | `127.0.0.1`                                          | Standalone bind address used by `just mcp` and `just mcp-dev-auth`.                                                                            |
| `MCP_PORT`                 | `6768`                                               | Standalone port used by the just recipes.                                                                                                      |
| `MCP_ALLOWED_HOSTS`        | loopback hosts                                       | Comma-separated accepted HTTP Host values; `localhost:*` permits a port. Include the public host at deployment.                                |
| `MCP_ALLOWED_ORIGINS`      | loopback origins                                     | Comma-separated accepted Origin values when clients send an Origin header. This does not enable browser CORS or replace bearer authentication. |
| `MCP_MAX_ROWS`             | `1000`                                               | Maximum data rows per response, within the tool schema's upper bound.                                                                          |
| `MCP_MAX_BYTES`            | `1000000`                                            | Maximum serialized tool-response size.                                                                                                         |
| `MCP_QUERY_TIMEOUT`        | `20`                                                 | Query time budget in seconds.                                                                                                                  |
| `MCP_MAX_CONCURRENCY`      | `4`                                                  | Maximum concurrent HTTP requests and data-service calls per process.                                                                           |
| `MCP_RATE_LIMIT`           | `120`                                                | HTTP requests per minute per client, per process.                                                                                              |
| `MCP_MAX_REQUEST_BYTES`    | `65536`                                              | Maximum HTTP request-body size, checked before tool execution.                                                                                 |
| `MCP_REQUEST_BODY_TIMEOUT` | `10`                                                 | Total seconds allowed to receive an HTTP request body (0.1–120), before tool execution.                                                        |

Incomplete HTTP request bodies receive `408 Request Timeout` after the body-read
deadline and release their concurrency slot. Receiving another chunk does not
restart the timer. HTTP/1.x timeout responses close the connection, so clients
should retry on a new connection. This limit covers body receipt only;
`MCP_QUERY_TIMEOUT` separately bounds database queries. It applies to both the
standalone HTTP server and the shared API mount, and does not affect stdio.

The hardcoded development token is never a fallback for missing production
configuration. An invalid bearer configuration fails closed.

## Deployment in this repository

### What already exists

The backend deployment is a **manual Podman deployment on a VM**. The
[justfile](../../justfile) builds API and frontend images locally and runs them in a
shared pod named `app`. The API reads `/data` from a read-only host volume. Nginx
serves the static Next.js export on container port 8080, published as host port
3000, and proxies `/api/` to the API on port 6767. MCP follows that same route.

The [GitHub Pages workflow](../../.github/workflows/deploy.yml) deploys only the
static frontend. It does **not** deploy Python, the warehouse, or MCP. There is no
backend image registry push, production secret provisioning, VM rollout, TLS
configuration, or automatic rollback in that workflow. Existing background is in
[the containerization design](../architecture/containers.md).

This change adds an MCP test workflow, API container packaging for the MCP
modules, environment propagation in the run recipes, and nginx proxy settings
that disable buffering for MCP traffic. It does not perform a deployment.

### Preparing the warehouse

The API and MCP require a materialized `warehouse.duckdb` built by the current
ETL. An old `vt_data.duckdb`, a DuckLake catalog by itself, or Git LFS pointer files
are not substitutes. The warehouse is gitignored and is not baked into the image.

Use the VM's existing compatible warehouse, transfer a validated warehouse to the
host data directory, or run the current ETL recipes. For a full collection, the
pipeline recipes are `just build-lake` (initial lake setup),
`just run-etl START_YEAR END_YEAR` (collection, cleaning, and loading), or
`just load-data` when the cleaned lake is already ready. Collection can require
`CENSUS_API_KEY`, source downloads, and considerable time; do not run it as a
side effect of starting the API. Preserve the old warehouse before replacing it.

The loading step also writes `warehouse.schema.json` beside the warehouse. This
small, deterministic snapshot contains table names, column names, and SQL types;
it contains no records or build timestamps. Schema changes do **not** fail the
warehouse build. Commit the generated `backend/Data/warehouse.schema.json` with
data updates so the existing MCP test job can compare it with the zoning catalog.
The test reports missing fields, newly unmapped fields, and nonnumeric types for
numeric measures. Review those differences and update the catalog or cleaner;
do not hand-edit the snapshot to make a mismatch disappear.

When `DATA_DIR` points outside the checkout, copy its generated snapshot to
`backend/Data/warehouse.schema.json` for review. To generate the snapshot from an
existing warehouse without rebuilding or changing the data, run from `backend/`:

```sh
uv run python -m warehouse_schema --warehouse /path/to/warehouse.duckdb --output Data/warehouse.schema.json
```

Compatibility is checked only by the regression test, not during loading or API
startup. CI sees the committed snapshot; it cannot detect an independently
replaced warehouse until its updated snapshot is included in the repository.

Stop readers before replacing the database, keep the new database at the same
mounted path, and restart the API. That avoids mixed data versions across
connections and invalidates old pagination cursors. Validate real dataset
availability and source-year coverage after replacement. A healthy process alone
does not guarantee that every source is present or current.

### Deployment procedure

1. Log in using the VM's application account (the README previously identified
   `appuser0`). Check out the reviewed commit. Have `just`, `uv`, Podman, and the
   warehouse available, with the file readable by the container's UID 1000.
2. Back up the current warehouse and save the current API/frontend image IDs or
   tag them for rollback. Prepare `.env` with `MCP_ENABLED=true`, bearer mode,
   generated per-client tokens, and the actual allowed hostname/origin. Preserve
   any existing Census key and VM-specific Podman configuration.
3. Run the local checks before rollout:

   ```sh
   just mcp-check
   just test-mcp
   just build-api
   just build-frontend
   ```

4. During the deployment window, recreate the app using the existing recipes:

   ```sh
   just dev
   just see-running
   just logs
   ```

   `just dev` stops and recreates the pod and rebuilds both images, so expect
   downtime. For an existing pod, operators can replace only the API and frontend
   containers with `just run-api` and `just run-frontend` after stopping the old
   containers. The maintenance page also lives in this pod and does not survive
   removing the entire pod.

5. Configure the VM's outer reverse proxy/load balancer to terminate HTTPS and
   forward `/api/mcp` and `/api/mcp/health` unchanged to port 3000. Preserve the
   public `Host` and the `Authorization`, `Origin`, and MCP protocol headers.
   **Overwrite** `X-Forwarded-Proto` with the original request scheme (`https`
   for public TLS requests); do not append to or pass through a client-supplied
   value. The inner nginx preserves `http`/`https` and falls back to its own
   connection scheme for missing or invalid values. This keeps trailing-slash
   redirects on the public scheme and hostname. Nginx connects to the API via
   `127.0.0.1`, Uvicorn's default trusted proxy address; keep that trust limited
   to loopback, never `*`.

   Forward POST/GET/DELETE and preserve the endpoint's intentional GET 405
   response; GET health checks must still work. Disable response buffering.
   The included nginx handles the inner hop. Keep host ports 3000 and
   6767 reachable only from the trusted proxy/network using VM firewall or bind
   configuration; the existing Podman recipes publish both ports.

6. Run the acceptance checks below against the public HTTPS URL before sharing
   credentials with a consumer. Give each consumer its own token and connection
   instructions.

The initial deployment should use one API process. Rate limits and concurrency
limits are process-local; multiplying workers multiplies their effective limits.
For a multi-instance deployment, add shared rate limiting at the gateway and a
controlled, consistent warehouse distribution process. Read-only database access
does not provide authorization for other existing REST endpoints: these MCP
tokens protect the MCP route only.

### Acceptance checks and rollback

- An unauthenticated request to `/api/mcp/health` must return 401 in bearer mode;
  the same request with a configured token must succeed. An incorrect token
  must fail. Verify each active token independently.
- Register the public URL with Claude Code using its bearer header. Check that
  all nine tools are discoverable; call `list_datasets`, describe a present
  dataset, query a known fact, follow a page cursor, and export a small CSV.
- Check at least one fact independently (for example, Vermont's 2020 Census
  population of 643,077 in the historic population dataset). Select a single
  geography and the intended year; do not sum state and county records together.
- Check MCP through nginx and the outer HTTPS proxy, not only by direct access
  to port 6767. Confirm an unexpected Host/Origin is rejected and browser CORS
  has not been broadly enabled. Requests to `/api/mcp/` and
  `/api/mcp/health/` must redirect to the corresponding path without the final
  slash, retaining `https://`, the public hostname/port, and any query string.
  Check the `Location` header before following a redirect with credentials.
- Restart the API and repeat a tool call. Remove a test token, restart again,
  and confirm that token no longer works. Monitor service logs and HTTP 429/5xx
  rates without logging authorization headers.

For MCP-only rollback, set `MCP_ENABLED=false` and recreate the API container;
the website and existing REST endpoints can remain on the new build. For a full
rollback, restore the previous reviewed checkout/image tags and compatible
warehouse, then recreate the containers with the same read-only mount. Do not
run collection/cleaning as a rollback operation. Retain token configuration in
the deployment secret store rather than copying it into source control.

## Tests and known boundaries

```sh
just mcp-check
just test-mcp
```

The MCP tests create small temporary DuckDB warehouses, so they run in CI without
Git LFS datasets, external source APIs, or production credentials. They exercise
the shared tool contract and HTTP transport/authentication. The CI workflow uses
the locked Python dependencies, runs the repository's nginx configuration
against a temporary MCP server, and builds the deployable API image. These
checks do not perform a rollout.

Proxy tests are opt-in locally and require nginx plus permission to bind
temporary loopback ports. They use fixture data and test credentials:

```sh
MCP_NGINX_TESTS=1 just test-mcp
```

Set `NGINX_BINARY` to an absolute executable path if nginx is not on `PATH`.
The proxy tests check HTTPS redirects, local HTTP fallback, and MCP
authentication/tool calls through nginx. They run automatically in CI, where
a missing nginx executable is a failure rather than a skip.

To opt in to read-only smoke tests against the configured real warehouse:

```sh
just test-mcp-live
```

The live suite checks catalog datasets and an end-to-end comparison workflow,
plus a known historic population value. It is skipped in the fixture-only run
unless `MCP_LIVE_WAREHOUSE` is set. Live-warehouse and deployed-proxy checks
complement fixture tests; fixtures cannot establish the freshness of deployed data.

The MCP workflow runs the MCP fixture suite explicitly. The whole backend suite
runs separately in `.github/workflows/backend-tests.yml`, without a warehouse:
tests that read real warehouse data are marked `requires_warehouse` and skip
there. The DuckLake diagnostic, which opens the lake at import time, lives in
`tests/inspect_lake.py` so pytest does not collect it.

This release supplies data tools for report generation. It does not implement an
agent orchestration loop, report templates, scheduled reports, a PDF renderer,
OAuth, token-specific roles, distributed rate limiting, or server-side artifact
storage. Those can be added without duplicating the current tool contract.
