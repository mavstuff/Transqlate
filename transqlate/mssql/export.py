"""Export SQL Server database to Transqlate dump."""

from __future__ import annotations

import argparse
from pathlib import Path

from transqlate.archive import work_dir_for_output, zip_directory
from transqlate.config import env, env_int
from transqlate.dump_format import (
    open_tsv_writer,
    row_to_tsv_cells,
    table_key,
    table_rel_path,
    topological_table_order,
    write_manifest,
    write_schema,
)
from transqlate.mssql.connection import connect_mssql
from transqlate.mssql.schema import discover_schema, export_select_sql


def add_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        default="transqlate-export",
        help="Output directory or .zip file",
    )
    parser.add_argument("--mssql-server", default=env("MSSQL_SERVER", "localhost"))
    parser.add_argument(
        "--mssql-port",
        type=int,
        default=env_int("MSSQL_PORT", 1433),
        help="SQL Server TCP port",
    )
    parser.add_argument("--mssql-database", default=env("MSSQL_DATABASE"))
    parser.add_argument("--mssql-user", default=env("MSSQL_USER"))
    parser.add_argument("--mssql-password", default=env("MSSQL_PASSWORD"))
    parser.add_argument(
        "--mssql-schemas",
        default=env("MSSQL_SCHEMAS", "dbo"),
        help="Comma-separated schemas to export (default: dbo)",
    )
    parser.add_argument(
        "--exclude-tables",
        default="",
        help="Comma-separated schema.table names to skip",
    )
    parser.add_argument("--batch-size", type=int, default=2000)


def export_table(
    conn,
    schema: str,
    table: str,
    columns: list[dict],
    out_path: Path,
    batch_size: int,
) -> int:
    sql = export_select_sql(schema, table, columns)
    col_names = [c["name"] for c in columns]
    count = 0
    file_handle, writer = open_tsv_writer(out_path)
    writer.writerow(col_names)

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    if isinstance(row, dict):
                        values = [row.get(c) for c in col_names]
                    else:
                        values = list(row)
                    writer.writerow(row_to_tsv_cells(values))
                    count += 1
                if count and count % 10000 == 0:
                    print(f"  {schema}.{table}: {count} rows...", flush=True)
    finally:
        file_handle.close()

    return count


def run_export(args: argparse.Namespace) -> int:
    output = Path(args.output)
    work_dir, make_zip = work_dir_for_output(output)
    work_dir.mkdir(parents=True, exist_ok=True)

    schemas = [s.strip() for s in args.mssql_schemas.split(",") if s.strip()]
    exclude = {
        t.strip()
        for t in (args.exclude_tables or "").split(",")
        if t.strip()
    }

    print(f"Work directory: {work_dir.resolve()}")
    print(
        f"SQL Server: {args.mssql_server}:{args.mssql_port} / {args.mssql_database}"
    )

    conn = connect_mssql(args)
    try:
        print("Discovering schema...")
        schema_doc = discover_schema(
            conn, include_schemas=schemas, exclude_tables=exclude
        )
        write_schema(work_dir, schema_doc)
        import_order = topological_table_order(schema_doc)
        print(f"Tables: {len(import_order)}")

        row_counts: dict[str, int] = {}
        table_columns: dict[str, list[str]] = {}

        for key in import_order:
            t = next(
                x
                for x in schema_doc["tables"]
                if table_key(x["schema"], x["name"]) == key
            )
            schema, name = t["schema"], t["name"]
            columns = t["columns"]
            table_columns[key] = [c["name"] for c in columns]
            out_path = work_dir / table_rel_path(schema, name)
            print(f"Exporting {key}...")
            row_counts[key] = export_table(
                conn, schema, name, columns, out_path, args.batch_size
            )
            print(f"  {key}: {row_counts[key]} rows -> {out_path.relative_to(work_dir)}")
    finally:
        conn.close()

    write_manifest(
        work_dir,
        source="sqlserver",
        database=args.mssql_database,
        import_order=import_order,
        row_counts=row_counts,
        table_columns=table_columns,
    )

    if make_zip:
        zip_directory(work_dir, output)
        print(f"Created archive: {output.resolve()}")

    total = sum(row_counts.values())
    print(f"Done. {total} rows exported.")
    return 0
