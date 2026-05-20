"""Import Transqlate dump into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from psycopg2.extras import execute_batch
except ImportError:
    execute_batch = None  # type: ignore[assignment]

from transqlate.archive import resolve_dump_dir
from transqlate.config import env
from transqlate.dump_format import (
    iter_tsv_rows,
    pg_column_list,
    read_manifest,
    read_schema,
    table_key,
    table_rel_path,
    topological_table_order,
)
from transqlate.postgres.connection import connect_postgres, ensure_psycopg2
from transqlate.postgres.schema import (
    apply_schema,
    qualified_pg_table,
    reset_identity_sequences,
    truncate_all,
)


def parse_cell(value: str | None, col: dict[str, Any]) -> Any:
    if value is None:
        return None
    data_type = (col.get("data_type") or "").lower()
    if data_type == "bit":
        return value.lower() == "true"
    if data_type in ("binary", "varbinary", "image"):
        return bytes.fromhex(value) if value else None
    return value


def add_import_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        default="transqlate-export",
        help="Dump directory or .zip file",
    )
    parser.add_argument("--postgres-host", default=env("POSTGRES_HOST", "localhost"))
    parser.add_argument(
        "--postgres-port", type=int, default=int(env("POSTGRES_PORT", "5432") or "5432")
    )
    parser.add_argument("--postgres-database", default=env("POSTGRES_DATABASE"))
    parser.add_argument("--postgres-user", default=env("POSTGRES_USER"))
    parser.add_argument("--postgres-password", default=env("POSTGRES_PASSWORD"))
    parser.add_argument(
        "--postgres-schema",
        default=env("POSTGRES_SCHEMA"),
        help="Target PG schema (default: map dbo->public, else keep name)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Do not truncate tables before import",
    )
    parser.add_argument(
        "--no-create-schema",
        action="store_true",
        help="Skip CREATE TABLE / FK / index DDL (schema must already exist)",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="DROP TABLE CASCADE before CREATE (destructive)",
    )
    parser.add_argument(
        "--skip-indexes",
        action="store_true",
        help="Do not create non-PK indexes",
    )
    parser.add_argument(
        "--skip-foreign-keys",
        action="store_true",
        help="Do not create foreign keys",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Apply DDL only, do not load data",
    )


def pg_insert_table_name(
    mssql_schema: str, table: str, target_schema: str | None
) -> str:
    return qualified_pg_table(mssql_schema, table, target_schema)


def insert_batch(
    pg: Any,
    qualified_table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> int:
    ensure_psycopg2()
    quoted = pg_column_list(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {qualified_table} ({quoted}) VALUES ({placeholders})"
    with pg.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=len(rows))
    pg.commit()
    return len(rows)


def import_table(
    pg: Any,
    dump_dir: Path,
    mssql_schema: str,
    table: str,
    columns: list[dict[str, Any]],
    target_schema: str | None,
    batch_size: int,
) -> int:
    path = dump_dir / table_rel_path(mssql_schema, table)
    if not path.is_file():
        print(f"Skip {mssql_schema}.{table}: {path} not found")
        return 0

    qualified = pg_insert_table_name(mssql_schema, table, target_schema)
    col_names = [c["name"] for c in columns]
    col_by_name = {c["name"]: c for c in columns}
    total = 0
    batch: list[tuple[Any, ...]] = []
    header: list[str] | None = None

    for file_header, values in iter_tsv_rows(path):
        if header is None:
            header = file_header
            if header != col_names:
                raise ValueError(
                    f"{path.name} column mismatch.\n"
                    f"  expected: {col_names}\n"
                    f"  got:      {header}"
                )
        parsed = tuple(
            parse_cell(v, col_by_name[name]) for name, v in zip(header, values)
        )
        batch.append(parsed)
        if len(batch) >= batch_size:
            total += insert_batch(pg, qualified, header, batch)
            batch.clear()
            if total % 10000 == 0:
                print(f"  {mssql_schema}.{table}: {total} rows...", flush=True)

    if batch and header is not None:
        total += insert_batch(pg, qualified, header, batch)
    return total


def run_import(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input not found: {input_path}")
        return 1

    dump_dir, tmp = resolve_dump_dir(input_path)
    try:
        manifest = read_manifest(dump_dir)
        schema_doc = read_schema(dump_dir)
        import_order = manifest.get("import_order") or topological_table_order(
            schema_doc
        )

        print(
            f"Dump: {manifest.get('source')} "
            f"db={manifest.get('database')} "
            f"exported {manifest.get('exported_at')} "
            f"({manifest.get('encoding')})"
        )

        pg = connect_postgres(args)
        target_schema = args.postgres_schema
        try:
            if not args.no_create_schema:
                print("Applying PostgreSQL schema...")
                apply_schema(
                    pg,
                    schema_doc,
                    target_schema=target_schema,
                    drop_existing=args.drop_existing,
                    skip_indexes=args.skip_indexes,
                    skip_foreign_keys=args.skip_foreign_keys,
                )
                print("Schema applied.")

            if args.schema_only:
                print("Schema-only mode; skipping data import.")
                return 0

            tables_by_key = {
                table_key(t["schema"], t["name"]): t
                for t in schema_doc.get("tables", [])
            }

            if not args.no_truncate:
                truncate_all(pg, import_order, schema_doc, target_schema)
                print("Truncated PostgreSQL tables.")

            grand_total = 0
            for key in import_order:
                t = tables_by_key.get(key)
                if not t:
                    continue
                schema, name = t["schema"], t["name"]
                cols = t["columns"]
                print(f"Importing {key}...")
                n = import_table(
                    pg, dump_dir, schema, name, cols, target_schema, args.batch_size
                )
                print(f"  {key}: {n} rows")
                grand_total += n

            reset_identity_sequences(pg, schema_doc, target_schema)
            print(f"Done. {grand_total} rows imported into PostgreSQL.")
        finally:
            pg.close()
    finally:
        if tmp is not None:
            tmp.cleanup()

    return 0
