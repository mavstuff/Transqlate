"""
Transqlate portable dump format: UTF-8 TSV tables + manifest.json + schema.json.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

FORMAT_NAME = "transqlate-tsv"
FORMAT_VERSION = 1
SCHEMA_FILE = "schema.json"
MANIFEST_FILE = "manifest.json"


def table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def table_rel_path(schema: str, table: str) -> Path:
    return Path(schema) / f"{table}.tsv"


def serialize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, memoryview):
        return bytes(value).hex()
    return str(value)


def row_to_tsv_cells(row: Sequence[Any]) -> list[str]:
    return [serialize_cell(v) for v in row]


def open_tsv_writer(path: Path) -> tuple[Any, csv.writer]:
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("w", encoding="utf-8", newline="")
    writer = csv.writer(
        f, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL
    )
    return f, writer


def write_schema(dump_dir: Path, schema_doc: dict[str, Any]) -> Path:
    path = dump_dir / SCHEMA_FILE
    path.write_text(json.dumps(schema_doc, indent=2) + "\n", encoding="utf-8")
    return path


def read_schema(dump_dir: Path) -> dict[str, Any]:
    path = dump_dir / SCHEMA_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{SCHEMA_FILE} not found in {dump_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(
    dump_dir: Path,
    *,
    source: str,
    database: str,
    import_order: list[str],
    row_counts: dict[str, int],
    table_columns: dict[str, list[str]],
) -> Path:
    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": source,
        "database": database,
        "exported_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "encoding": "utf-8",
        "delimiter": "tab",
        "import_order": import_order,
        "tables": {
            key: {
                "file": table_rel_path(*key.split(".", 1)).as_posix(),
                "rows": row_counts.get(key, 0),
                "columns": table_columns.get(key, []),
            }
            for key in import_order
        },
    }
    manifest_path = dump_dir / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def read_manifest(dump_dir: Path) -> dict[str, Any]:
    manifest_path = dump_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_FILE} not found in {dump_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT_NAME:
        raise ValueError(
            f"Unsupported dump format: {manifest.get('format')!r} "
            f"(expected {FORMAT_NAME!r})"
        )
    version = manifest.get("version")
    if version != FORMAT_VERSION:
        raise ValueError(
            f"Unsupported dump version: {version} (expected {FORMAT_VERSION})"
        )
    return manifest


def pg_quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def pg_column_list(columns: Sequence[str]) -> str:
    return ", ".join(pg_quote_ident(c) for c in columns)


def iter_tsv_rows(path: Path) -> Iterable[tuple[list[str], list[str | None]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        for row in reader:
            if not row:
                continue
            values: list[str | None] = [None if cell == "" else cell for cell in row]
            yield header, values


def topological_table_order(schema_doc: dict[str, Any]) -> list[str]:
    """Order tables so referenced tables come before dependents."""
    tables = schema_doc.get("tables", [])
    keys = [table_key(t["schema"], t["name"]) for t in tables]
    key_set = set(keys)
    deps: dict[str, set[str]] = {k: set() for k in keys}

    for t in tables:
        child = table_key(t["schema"], t["name"])
        for fk in t.get("foreign_keys", []):
            ref_schema = fk["referenced_schema"]
            ref_table = fk["referenced_table"]
            parent = table_key(ref_schema, ref_table)
            if parent in key_set and parent != child:
                deps[child].add(parent)

    ordered: list[str] = []
    remaining = set(keys)
    while remaining:
        ready = sorted(k for k in remaining if not (deps[k] - set(ordered)))
        if not ready:
            # cyclic FK graph — fall back to alphabetical
            ready = sorted(remaining)
        for k in ready:
            ordered.append(k)
            remaining.remove(k)
    return ordered
