# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vermont Data Exploration App — a full-stack web application for visualizing Vermont livability indicators (housing, demographics, zoning, flood hazard, soil suitability). Targeted at non-technical users such as Regional Planning Commissions, Select Boards, developers, and reporters.

## Tips

- Use `uv run` to run things.

## Commands

### Frontend (Next.js, `frontend/`)

```bash
npm run dev          # Dev server on localhost:3000
npm run build        # Production build (Turbopack)
npm run lint         # ESLint
npm run format       # Prettier (fixes in place)
npm run format:check # Check formatting without modifying
```

### Backend (FastAPI, `backend/`)

```bash
uvicorn api.main:app --reload --port 6767  # API server on localhost:6767
pip install -r requirements.txt            # Install dependencies
streamlit run Home.py                      # Legacy Streamlit interface (not primary)
uv run sqlfluff lint query/sql data_cleaning/sql   # Lint the Jinja SQL templates
uv run sqlfluff fix query/sql data_cleaning/sql    # Auto-fix SQL lint issues
```

SQL templates under `backend/query/sql/` and `backend/data_cleaning/sql/` are Jinja
templates rendered by `query/sql_render.py`, which also holds the
general-purpose filter compiler (it emits `$N` prepared-statement placeholders
plus a params list — execute with `DB.execute(sql, params)`). Lint-time
template context lives in `backend/.sqlfluff`.

## Architecture

### Frontend (`frontend/src/`)

**Next.js App Router pages:**

- `app/page.tsx` — Home/landing
- `app/data-viewer/page.tsx` — Auto-generated charts/tables from a selected profile
- `app/mapping/[slug]/page.tsx` — Dynamic map pages (zoning, soil-suitability, flood-insurance)
- `app/working-report/page.tsx` — PDF export of saved charts via `html2pdf.js`; users can save
- `app/data-export/page.tsx` — Raw data download

**Key components:**

- `components/Charts/` — Chart rendering (DualLine, Bar, DemographicsTable, ChartStack). Chart configs are centralized in `components/Charts/configs/ChartDefs.tsx`.
- `components/FilterUI/` — Hierarchical filter UI. `useApplyFilters.ts` handles backend calls; `FilterContext.tsx` holds filter state.
- `components/ItemsProvider/index.tsx` — Zustand store (localStorage-persisted) for the working report item list.
- `components/profile/profileStore.ts` — Zustand store for selected locations/comparison data.
- `components/mapping/` — Map visualization via Maplibre-GL and Deck.gl.

**Config:** `src/config.ts` exports the backend API base URL (`http://127.0.0.1:6767`).

**Types:** `src/types/cachedCharts.ts` defines `ChartItem`, `CounterItem`, and `MapItem` interfaces.

**UI:** Mantine v8 for components/layout; Tailwind for utility styles. Theme in `src/app/theme.ts`.

### Backend (`backend/`)

**FastAPI app:** `api/main.py` — CORS configured for `localhost:3000`. Registers GET and POST routers.

**Routes:**

- `api/routes/get_routes/get_filters.py` — `GET /load/mapping/{dataset}/filters` — returns hierarchical filter tree
- `api/routes/get_routes/get_wholedata.py` — full dataset fetch with optional filters
- `api/routes/post_routes/post_acs5_db.py` — Census ACS-5 tidy and time-series data (`/load/acs5-db/...`)
- `api/routes/post_routes/post_zoning.py` — Zoning data

**Response model:** `api/models/response_models.py` — `APIResponse` with `data`, `tableData`, and `metadata` fields.

**Query layer (`query/`):**

- `sql_render.py` — Jinja SQL rendering and the filter compiler (`sql_filter_block`, `compile_where`)
- `acs5.py` — ACS-5 tidy and time-series queries against `warehouse.duckdb`
- `production_db.py` — lazy DuckDB connection

**ETL census helpers:** `data_collection/census.py` (`tidy_census`, `split_name_col`).

**Data files:** `backend/Data/` — Census ACS-5, flood-hazard, soil-suitability, wastewater, zoning (CSV, Parquet, FGB, GeoJSON formats).

### Data Flow

1. **Filters:** Frontend requests `GET /load/mapping/{dataset}/filters` → backend builds `FilterState` tree from dataset → returns label hierarchy.
2. **Charts:** Frontend sends location filters to a POST route → backend filters dataframe, serializes to records → frontend renders via Recharts/Chart.js.
3. **Working Report:** User saves charts to Zustand `ItemsProvider` store → `/working-report` page renders them → `html2pdf.js` exports DOM as PDF.

## Code Style

- **Prettier:** semicolons on, single quotes, 80-char print width, 2-space indent, trailing commas everywhere.
- **ESLint:** `next/core-web-vitals` + TypeScript rules.
- **TypeScript:** strict mode, path alias `@/*` → `./src/*`.
- Run `npm run format` then `npm run lint` before committing frontend changes.
- Ruff for python linting. `ruff check --fix`
- Formatting is enforced by pre-commit hooks (`.pre-commit-config.yaml`) and the Format Check CI workflow; a Claude Code PostToolUse hook (`.claude/hooks/format.py`) also formats edited files automatically.
