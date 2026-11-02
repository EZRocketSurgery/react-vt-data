"""
Diagnostic script for inspecting DuckLake table structure.

Usage (from backend):
python -m tests.inspect_lake
"""

from lake_build import get_connection

con = get_connection()


def inspect_schema(schema: str) -> None:
    print("\n" + "=" * 80)
    print(f"SCHEMA: {schema}")
    print("=" * 80)

    # ------------------------------------------------------------------
    # List tables
    # ------------------------------------------------------------------
    tables = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = ?
        ORDER BY table_name
        """,
        [schema],
    ).fetchall()

    if not tables:
        print("No tables found.")
        return

    print(f"\nFound {len(tables)} table(s):")

    for (table_name,) in tables:
        print(f"\n{'-' * 80}")
        print(f"TABLE: {schema}.{table_name}")
        print("-" * 80)

        # --------------------------------------------------------------
        # Column structure
        # --------------------------------------------------------------
        columns = con.execute(
            """
            SELECT
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = ?
              AND table_name = ?
            ORDER BY ordinal_position
            """,
            [schema, table_name],
        ).fetchall()

        # --------------------------------------------------------------
        # Year information
        # --------------------------------------------------------------
        column_names = [column[0].lower() for column in columns]

        if "year" in column_names:
            try:
                years = con.execute(
                    f'''
                    SELECT
                        MIN(year),
                        MAX(year),
                        COUNT(DISTINCT year)
                    FROM "lake"."{schema}"."{table_name}"
                    '''
                ).fetchone()

                print(f"Years: {years[0]} → {years[1]} ({years[2]} distinct)")

            except Exception as e:  # noqa: BLE001 -- skip and keep the run going
                print(f"Could not inspect years: {e}")


def query_lake_metadata(
    table: str = "ducklake_snapshot",
) -> None:
    """Query and print a DuckLake metadata table."""

    metadata_table = f"__ducklake_metadata_lake.{table}"

    df = con.execute(
        f"""
        SELECT *
        FROM {metadata_table}
        """
    ).df()

    print(f"\n{metadata_table}")
    print("=" * 80)
    print(df.head(8))


def inspect_table_files(schema: str, table: str) -> None:
    """Inspect DuckLake metadata for the physical files belonging to a table."""

    df = con.execute(
        f"""--sql
        SELECT *
        FROM lake.{schema}.{table}
        """
    ).df()

    print(df.columns)


def find_stale_file() -> None:
    """Find the stale demographics parquet reference in DuckLake metadata."""

    metadata_table = "__ducklake_metadata_lake.ducklake_data_file"

    df = con.execute(
        f"""
        SELECT *
        FROM {metadata_table}
        WHERE CAST(file_path AS VARCHAR)
              LIKE '%019ff1aa-37d5-75c6-8641-45e2a35075f1%'
        """
    ).fetchdf()

    print("\nSTALE FILE REFERENCE")
    print("=" * 80)

    if df.empty:
        print("No matching metadata entry found.")
    else:
        print(df.to_string(index=False))


def inspect_demographics_files() -> None:
    df = con.execute(
        """
        SELECT
            data_file_id,
            table_id,
            path,
            begin_snapshot,
            end_snapshot
        FROM __ducklake_metadata_lake.ducklake_data_file
        WHERE table_id = 7
        ORDER BY data_file_id
        """
    ).fetchdf()

    print("\nDEMOGRAPHICS DATA FILES")
    print("=" * 80)
    print(df.to_string(index=False))


def main() -> None:
    inspect_table_files("RAW", "vt_town_lines")


if __name__ == "__main__":
    main()
