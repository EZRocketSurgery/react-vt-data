"""
Ensure backend/ is on sys.path and the working directory is set to backend/
so relative paths (e.g., logger/logsapi.log) resolve correctly.

Route and query modules open the production warehouse when imported
(`DB = get_db()`). Without a built warehouse (e.g. in CI) they get an empty
in-memory DuckDB instead, so tests that swap in fixture tables can still import
them. Tests that read real warehouse data are marked `requires_warehouse` and
skip when it is absent.
"""

import os
import sys
from pathlib import Path

import duckdb
import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from query import production_db

WAREHOUSE_AVAILABLE = production_db.WAREHOUSE_PATH.exists()

if not WAREHOUSE_AVAILABLE:
    production_db.get_db = lambda: production_db._ThreadSafeDB(duckdb.connect())


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_warehouse: reads the built warehouse.duckdb; skipped without it",
    )


def pytest_collection_modifyitems(config, items):
    if WAREHOUSE_AVAILABLE:
        return
    skip = pytest.mark.skip(
        reason=f"no warehouse at {production_db.WAREHOUSE_PATH} (build it with `just etl`)"
    )
    for item in items:
        if "requires_warehouse" in item.keywords:
            item.add_marker(skip)
