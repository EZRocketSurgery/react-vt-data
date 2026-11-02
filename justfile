## Set up environment ##

export DATA_DIR := env("DATA_DIR", justfile_directory() / "backend" / "Data")
# Load environment variables
set dotenv-filename := ".env"

api_host := env("API_HOST", "127.0.0.1")
api_port := env("API_PORT", "6767")
api_url := env("NEXT_PUBLIC_API_URL", "http://localhost:6767/api")
mcp_host := env("MCP_HOST", "127.0.0.1")
mcp_port := env("MCP_PORT", "6768")
# Pass named variables without placing bearer-token values in podman arguments.
mcp_container_env := "-e MCP_ENABLED -e MCP_AUTH_MODE -e MCP_BEARER_TOKENS -e MCP_ALLOWED_HOSTS -e MCP_ALLOWED_ORIGINS -e MCP_MAX_ROWS -e MCP_MAX_BYTES -e MCP_QUERY_TIMEOUT -e MCP_MAX_CONCURRENCY -e MCP_RATE_LIMIT -e MCP_MAX_REQUEST_BYTES -e MCP_REQUEST_BODY_TIMEOUT"
# Data chat (docs/architecture/data-chat.md); the provider key is passed by name.
chat_container_env := "-e CHAT_ENABLED -e CHAT_MODEL -e OPENROUTER_API_KEY -e OPENAI_API_KEY -e CHAT_MAX_MODEL_REQUESTS -e CHAT_MAX_TOOL_CALLS -e CHAT_MAX_OUTPUT_TOKENS -e CHAT_PREVIEW_ROWS -e CHAT_MAX_HISTORY_MESSAGES -e CHAT_MAX_MESSAGE_CHARS -e CHAT_MAX_HISTORY_CHARS -e CHAT_RATE_LIMIT -e CHAT_CHART_MAX_ROWS"
# Host-specific podman flags. Empty by default (Docker, macOS, rootful podman).
# On the VM with rootless podman, override:  just podman_flags="--userns=keep-id:uid=1000,gid=1000"
podman_flags := env("PODMAN_FLAGS", "")

################
# CLI Development  #
################

[doc("initiate non-containerized backend. note: no longer turns off containers, you should do this manually")]
[group("CLI Rapid Development")]
[working-directory("backend")]
local-api:
    ALLOW_DEV_CORS=1 uv run uvicorn api.main:app --reload \
        --host {{ api_host }} --port {{ api_port }}

[doc("initiate non-containerized frontend. note: no longer turns off containers")]
[group("CLI Rapid Development")]
[working-directory("frontend")]
local-frontend:
    NEXT_PUBLIC_API_URL={{ api_url }} npm run dev -- --port 3000

[doc("turns on non-container full apps, interleaved in terminal (from Procfile). Note: no longer turns off containers")]
[group("CLI Rapid Development")]
local-dev:
    uvx honcho start

################
# Data Chat #
################

[doc("run the API with Data Chat on, plus the frontend (open http://localhost:3000/chat/)")]
[group("Data Chat")]
chat-dev:
    CHAT_ENABLED=1 uvx honcho start

[doc("compare models on the eval chats, e.g. just chat-eval openai/gpt-6.1-sol openai/gpt-6-luna")]
[group("Data Chat")]
[working-directory("backend")]
chat-eval +models:
    uv run python -m evals.chat run --models {{ models }}

[doc("list the eval chats")]
[group("Data Chat")]
[working-directory("backend")]
chat-eval-cases:
    uv run python -m evals.chat cases

[doc("list tool-capable OpenRouter models by price, e.g. just chat-eval-models qwen")]
[group("Data Chat")]
[working-directory("backend")]
chat-eval-models filter="":
    uv run python -m evals.chat models {{ if filter == "" { "" } else { "--filter " + filter } }}

[doc("serve saved eval runs side by side at http://localhost:3000/chat/evals/")]
[group("Data Chat")]
chat-eval-ui:
    CHAT_ENABLED=1 CHAT_EVALS_DIR="{{ justfile_directory() }}/backend/evals/chat/results" uvx honcho start

[doc("run the Data Chat and eval tests (no network or API key needed)")]
[group("Data Chat")]
[working-directory("backend")]
test-chat:
    uv run pytest -q tests/test_chat.py tests/test_chat_evals.py

################
# MCP Development #
################

[doc("run the standalone MCP on localhost:6768 (auth mode from environment; defaults to none)")]
[group("MCP")]
[working-directory("backend")]
mcp:
    uv run python -m mcp_server --host {{ mcp_host }} --port {{ mcp_port }}

[doc("run local MCP with the documented development bearer token")]
[group("MCP")]
[working-directory("backend")]
mcp-dev-auth:
    MCP_AUTH_MODE=development uv run python -m mcp_server --host {{ mcp_host }} --port {{ mcp_port }}

[doc("run the MCP over stdio for a local agent-managed subprocess")]
[group("MCP")]
[working-directory("backend")]
mcp-stdio:
    MCP_AUTH_MODE=none uv run python -m mcp_server --transport stdio

[doc("generate one random production bearer token; save its output in your secrets configuration")]
[group("MCP")]
[working-directory("backend")]
mcp-token:
    @uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'

[doc("check MCP Python formatting and lint without changing files")]
[group("MCP")]
[working-directory("backend")]
mcp-check:
    uv run ruff check data_tools mcp_server tests/test_mcp_*.py
    uv run ruff format --check data_tools mcp_server tests/test_mcp_*.py

[doc("run MCP tests with temporary fixture databases; no production warehouse needed")]
[group("MCP")]
[working-directory("backend")]
test-mcp:
    uv run pytest -q tests/test_mcp_*.py

[doc("smoke-test every MCP dataset against the configured real warehouse (read-only)")]
[group("MCP")]
[working-directory("backend")]
test-mcp-live:
    MCP_LIVE_WAREHOUSE="{{ DATA_DIR }}/warehouse.duckdb" uv run pytest -q tests/test_mcp_live.py

########################################################
########################################################
################## CONTAINERS ###########################
########################################################
########################################################

###############################
# Pod for containers sharing local-host  #
# ##############################

[doc("build the pod for local-host co communication")]
[group("Pod")]
build-pod:
    podman pod exists app || podman pod create --name app --userns=keep-id {{ podman_flags }} -p 6767:6767 -p 3000:8080

[doc("reset the local host pod (delete and recreate it)")]
[group("Pod")]
reset-pod:
    podman pod create --replace --name app --userns=keep-id {{ podman_flags }} -p 6767:6767 -p 3000:8080

###########
# Containers #
###########

# Combined
#########

[doc("Run and build both containers.")]
[group("Main")]
dev: down dev-api dev-frontend
    @echo "frontend hosted @ http://localhost:3000"
    @echo "api hosted @ http://localhost:3000/api/docs"

[doc("just run containers (if already built).")]
[group("Main")]
dev-run: run-api run-frontend

## API Container
#############

[doc("build the api image")]
[group("API Container")]
[working-directory("backend")]
build-api:
    podman build -t localhost/my-api -f dockerfile .

[doc("run the api image (detached)")]
[group("API Container")]
[working-directory("backend")]
run-api:
    podman run --pod app --name api -d --rm -v "{{ DATA_DIR }}:/data:ro,z" {{ mcp_container_env }} {{ chat_container_env }} localhost/my-api

[doc("build the api image and then check it with more error printing (non detached)")]
[group("API Container")]
[working-directory("backend")]
run-check-api: build-api
    podman run --pod app -v "{{ DATA_DIR }}:/data:ro,z" {{ mcp_container_env }} {{ chat_container_env }} localhost/my-api

[doc("everything to get the api up and running")]
[group("API Container")]
dev-api: build-pod build-api run-api

## Frontend Container
################

[doc("build the frontend image")]
[group("Frontend Container")]
[working-directory("frontend")]
build-frontend:
    podman build -t localhost/frontend --build-arg NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY="{{ env("NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY", "") }}" -f dockerfile .

[doc("run the frontend image (detached)")]
[group("Frontend Container")]
run-frontend:
    podman run --pod app --name frontend  -d --rm localhost/frontend

[doc("everything to get the frontend up and running")]
[group("Frontend Container")]
dev-frontend: build-pod build-frontend run-frontend

## Maintenance mode
################

[doc("build a frontend image that shows the 'Under Maintenance' page instead of the app")]
[group("Maintenance")]
[working-directory("frontend")]
build-frontend-maintenance:
    podman build -t localhost/frontend:maintenance --build-arg NEXT_PUBLIC_MAINTENANCE_MODE=true --build-arg NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY="{{ env("NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY", "") }}" -f dockerfile .

[doc("swap the running frontend container for the maintenance-mode one (api + pod stay up)")]
[group("Maintenance")]
maintenance-on: build-frontend-maintenance
    podman stop frontend || true
    podman rm frontend || true
    podman run --pod app --name frontend -d --rm localhost/frontend:maintenance

[doc("swap back to the real frontend image")]
[group("Maintenance")]
maintenance-off: build-frontend
    podman stop frontend || true
    podman rm frontend || true
    just run-frontend

################
# Lint, Format, and Test
################

[doc("run every lint check (frontend + backend + SQL)")]
[group("Lint & Format")]
lint: check-frontend lint-frontend lint-backend lint-sql

[doc("run every formatter (frontend + SQL)")]
[group("Lint & Format")]
format: format-frontend fix-sql

[doc("check typescript (not in the next.config, until fixed)")]
[group("Lint & Format")]
[working-directory("frontend")]
check-frontend:
    npx tsc --noEmit

[doc("lint the frontend with ESLint")]
[group("Lint & Format")]
[working-directory("frontend")]
lint-frontend:
    npm run lint

[doc("format the frontend with Prettier (fixes in place)")]
[group("Lint & Format")]
[working-directory("frontend")]
format-frontend:
    npm run format

[doc("check frontend formatting without modifying files")]
[group("Lint & Format")]
[working-directory("frontend")]
format-check-frontend:
    npm run format:check

[doc("lint the backend with ruff (fixes in place)")]
[group("Lint & Format")]
[working-directory("backend")]
lint-backend:
    uv run ruff check --fix .

[doc("lint the Jinja SQL templates with sqlfluff")]
[group("Lint & Format")]
[working-directory("backend")]
lint-sql:
    uv run sqlfluff lint query/sql data_cleaning/sql

[doc("auto-fix the Jinja SQL templates with sqlfluff")]
[group("Lint & Format")]
[working-directory("backend")]
fix-sql:
    uv run sqlfluff fix query/sql data_cleaning/sql

[doc("run the backend test suite")]
[group("Test")]
[working-directory("backend")]
test:
    uv run pytest

################
# ETL (Pipeline) Container
################

# --------- Pre-step: Lake Builder ---------------------
[doc("build and run the lake builder container")]
[group("ETL Pipeline")]
[working-directory("backend")]
build-lake:
    podman build -t localhost/vdc-lake -f ETL/dockerfile.lake .
    podman run --rm {{ podman_flags }} -v "{{ DATA_DIR }}:/data:z" -e DATA_DIR=/data localhost/vdc-lake

# --------- 1. Data Collection (E) ---------------------
[doc("build the backend COLLECTION image")]
[group("ETL Pipeline")]
[working-directory("backend")]
build-collection:
    podman build -t localhost/vdc-collection -f ETL/dockerfile.collect .

[doc("Collect the data for a specified year and add to lake.RAW tables (optionally pass only= to run a single scraper)")]
[group("ETL Pipeline")]
[working-directory("backend")]
get-data start_year end_year only="": build-collection
    podman run --rm {{ podman_flags }} \
        -v "{{ DATA_DIR }}:/data:z" \
        -e DATA_DIR=/data \
        -e CENSUS_API_KEY="$CENSUS_API_KEY" \
        localhost/vdc-collection {{ start_year }} {{ end_year }} {{ if only == "" { "" } else { "--only " + only } }}

# --------- 2. Data Cleaning (T) ---------------------
[doc("Run each RAW table through it's data cleaning script (optionally pass a single script name to run only that one)")]
[group("ETL Pipeline")]
[working-directory("backend")]
transform-data script_name="":
    podman build -t localhost/vdc-cleaning -f ETL/dockerfile.clean .
    podman run --rm {{ podman_flags }} \
     -v "{{ DATA_DIR }}:/data:z" localhost/vdc-cleaning {{ script_name }}

# --------- 3. Data Loading (L) ---------------------
[doc("Load the lake.CLEANED tables into a DuckDB database")]
[group("ETL Pipeline")]
[working-directory("backend")]
load-data:
    podman build -t localhost/vdc-loading -f ETL/dockerfile.load .
    podman run {{ podman_flags }} --rm -v "{{ DATA_DIR }}:/data:z" localhost/vdc-loading

[doc("Collect (E), clean (T), and load (L) the data (Full pipeline run)")]
[group("ETL Pipeline")]
[working-directory("backend")]
run-etl start_year end_year:
    # Collect the data for a certain year
    just get-data {{ start_year }} {{ end_year }}
    # Clean the RAW populated lake tables into CLEANED
    just transform-data
    # Load CLEANED tables into DuckDB instance
    just load-data

#####################
# Abstracted podman util #
#####################

[doc("stream logs for the whole app pod")]
[group("Utilities")]
logs:
    podman pod logs -f app

[doc("kill the localhost app and everything in it")]
[group("Utilities")]
down:
    podman pod rm -f app

[doc("see what containers are running")]
[group("Utilities")]
see-running:
    podman ps

[doc("see what's listening on the app ports (3000, 6767)")]
[group("Utilities")]
see-ports:
    ss -tulpn | grep -E ':(3000|6767)\b' || echo "nothing listening on 3000 or 6767"
