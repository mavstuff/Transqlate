"""Command-line interface for Transqlate."""

from __future__ import annotations

import argparse
import sys

from transqlate import __version__
from transqlate.mssql.export import add_export_args, run_export
from transqlate.postgres.import_data import add_import_args, run_import


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tq",
        description="Transqlate: migrate SQL Server databases to PostgreSQL",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser(
        "export",
        help="Dump SQL Server to UTF-8 TSV package (folder or .zip)",
    )
    add_export_args(export_p)

    import_p = sub.add_parser(
        "import",
        help="Load dump into PostgreSQL (creates schema, FKs, indexes)",
    )
    add_import_args(import_p)

    schema_p = sub.add_parser(
        "schema",
        help="Write PostgreSQL DDL from an existing dump's schema.json",
    )
    schema_p.add_argument(
        "--input",
        default="transqlate-export",
        help="Dump directory or .zip containing schema.json",
    )
    schema_p.add_argument(
        "--output",
        default="-",
        help="Output .sql file path, or - for stdout",
    )
    schema_p.add_argument(
        "--postgres-schema",
        default=None,
        help="Target PG schema (default: map dbo->public)",
    )
    schema_p.add_argument(
        "--drop-existing",
        action="store_true",
        help="Emit DROP TABLE / DROP CONSTRAINT statements",
    )
    schema_p.add_argument("--skip-indexes", action="store_true")
    schema_p.add_argument("--skip-foreign-keys", action="store_true")

    return parser


def run_schema_sql(args: argparse.Namespace) -> int:
    from pathlib import Path

    from transqlate.archive import resolve_dump_dir
    from transqlate.dump_format import read_schema
    from transqlate.postgres.schema import (
        create_table_sql,
        foreign_key_sql,
        index_sql,
    )

    dump_dir, tmp = resolve_dump_dir(Path(args.input))
    try:
        schema_doc = read_schema(dump_dir)
        lines: list[str] = []
        for table in schema_doc.get("tables", []):
            lines.extend(
                create_table_sql(
                    table,
                    args.postgres_schema,
                    drop_if_exists=args.drop_existing,
                )
            )
        if not args.skip_foreign_keys:
            for table in schema_doc.get("tables", []):
                lines.extend(
                    foreign_key_sql(
                        table,
                        args.postgres_schema,
                        drop_if_exists=args.drop_existing,
                    )
                )
        if not args.skip_indexes:
            for table in schema_doc.get("tables", []):
                lines.extend(index_sql(table, args.postgres_schema))

        text = "\n".join(lines) + "\n"
        if args.output == "-":
            sys.stdout.write(text)
        else:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"Wrote {Path(args.output).resolve()}")
    finally:
        if tmp is not None:
            tmp.cleanup()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export":
        return run_export(args)
    if args.command == "import":
        return run_import(args)
    if args.command == "schema":
        return run_schema_sql(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
