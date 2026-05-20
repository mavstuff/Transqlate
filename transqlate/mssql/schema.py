"""Discover tables, columns, keys, and indexes from SQL Server."""

from __future__ import annotations

from typing import Any

from transqlate.dump_format import table_key


def discover_schema(
    conn: Any,
    *,
    include_schemas: list[str] | None = None,
    exclude_tables: set[str] | None = None,
) -> dict[str, Any]:
    """Build schema.json document from live MSSQL metadata."""
    include_schemas = include_schemas or ["dbo"]
    exclude_tables = exclude_tables or set()

    schema_filter = ",".join(f"'{s}'" for s in include_schemas)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND TABLE_SCHEMA IN ({schema_filter})
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        )
        table_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT
                c.TABLE_SCHEMA,
                c.TABLE_NAME,
                c.COLUMN_NAME,
                c.ORDINAL_POSITION,
                c.DATA_TYPE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.NUMERIC_PRECISION,
                c.NUMERIC_SCALE,
                c.DATETIME_PRECISION,
                c.IS_NULLABLE,
                COLUMNPROPERTY(
                    OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)),
                    c.COLUMN_NAME,
                    'IsIdentity'
                ) AS is_identity,
                COLUMNPROPERTY(
                    OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)),
                    c.COLUMN_NAME,
                    'IsComputed'
                ) AS is_computed
            FROM INFORMATION_SCHEMA.COLUMNS c
            WHERE c.TABLE_SCHEMA IN ({schema_filter})
            ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
            """
        )
        column_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT
                tc.TABLE_SCHEMA,
                tc.TABLE_NAME,
                kcu.COLUMN_NAME,
                kcu.ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
             AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
              AND tc.TABLE_SCHEMA IN ({schema_filter})
            ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, kcu.ORDINAL_POSITION
            """
        )
        pk_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT
                fk.name AS constraint_name,
                sch.name AS table_schema,
                tab.name AS table_name,
                col.name AS column_name,
                fk_col.constraint_column_id AS ordinal_position,
                ref_sch.name AS referenced_schema,
                ref_tab.name AS referenced_table,
                ref_col.name AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fk_col ON fk.object_id = fk_col.constraint_object_id
            JOIN sys.tables tab ON fk.parent_object_id = tab.object_id
            JOIN sys.schemas sch ON tab.schema_id = sch.schema_id
            JOIN sys.columns col
              ON col.object_id = tab.object_id AND col.column_id = fk_col.parent_column_id
            JOIN sys.tables ref_tab ON fk.referenced_object_id = ref_tab.object_id
            JOIN sys.schemas ref_sch ON ref_tab.schema_id = ref_sch.schema_id
            JOIN sys.columns ref_col
              ON ref_col.object_id = ref_tab.object_id
             AND ref_col.column_id = fk_col.referenced_column_id
            WHERE sch.name IN ({schema_filter})
            ORDER BY sch.name, tab.name, fk.name, fk_col.constraint_column_id
            """
        )
        fk_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT
                s.name AS table_schema,
                t.name AS table_name,
                i.name AS index_name,
                i.is_unique,
                i.is_primary_key,
                i.type_desc,
                c.name AS column_name,
                ic.key_ordinal,
                ic.is_included_column
            FROM sys.indexes i
            JOIN sys.tables t ON i.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE s.name IN ({schema_filter})
              AND i.type > 0
              AND i.is_hypothetical = 0
            ORDER BY s.name, t.name, i.name, ic.key_ordinal, ic.index_column_id
            """
        )
        index_rows = cur.fetchall()

    tables: list[dict[str, Any]] = []
    columns_by_table: dict[str, list[dict[str, Any]]] = {}
    pk_by_table: dict[str, list[str]] = {}

    for row in column_rows:
        key = table_key(row["TABLE_SCHEMA"], row["TABLE_NAME"])
        if row.get("is_computed"):
            continue
        columns_by_table.setdefault(key, []).append(
            {
                "name": row["COLUMN_NAME"],
                "ordinal": row["ORDINAL_POSITION"],
                "data_type": row["DATA_TYPE"],
                "character_maximum_length": row["CHARACTER_MAXIMUM_LENGTH"],
                "numeric_precision": row["NUMERIC_PRECISION"],
                "numeric_scale": row["NUMERIC_SCALE"],
                "datetime_precision": row["DATETIME_PRECISION"],
                "nullable": row["IS_NULLABLE"] == "YES",
                "is_identity": bool(row.get("is_identity")),
            }
        )

    for row in pk_rows:
        key = table_key(row["TABLE_SCHEMA"], row["TABLE_NAME"])
        pk_by_table.setdefault(key, []).append(row["COLUMN_NAME"])

    fks_by_table: dict[str, list[dict[str, Any]]] = {}
    for row in fk_rows:
        key = table_key(row["table_schema"], row["table_name"])
        fks_by_table.setdefault(key, [])
        existing = next(
            (f for f in fks_by_table[key] if f["name"] == row["constraint_name"]),
            None,
        )
        if existing is None:
            existing = {
                "name": row["constraint_name"],
                "columns": [],
                "referenced_schema": row["referenced_schema"],
                "referenced_table": row["referenced_table"],
                "referenced_columns": [],
            }
            fks_by_table[key].append(existing)
        existing["columns"].append(row["column_name"])
        existing["referenced_columns"].append(row["referenced_column"])

    indexes_by_table: dict[str, dict[str, dict[str, Any]]] = {}
    for row in index_rows:
        if row["is_primary_key"]:
            continue
        key = table_key(row["table_schema"], row["table_name"])
        indexes_by_table.setdefault(key, {})
        idx = indexes_by_table[key].setdefault(
            row["index_name"],
            {
                "name": row["index_name"],
                "unique": bool(row["is_unique"]),
                "type": row["type_desc"],
                "columns": [],
                "included_columns": [],
            },
        )
        if row["is_included_column"]:
            idx["included_columns"].append(row["column_name"])
        elif row["key_ordinal"] > 0:
            idx["columns"].append(row["column_name"])

    for tr in table_rows:
        schema = tr["TABLE_SCHEMA"]
        name = tr["TABLE_NAME"]
        key = table_key(schema, name)
        if key in exclude_tables:
            continue
        cols = columns_by_table.get(key, [])
        if not cols:
            continue
        tables.append(
            {
                "schema": schema,
                "name": name,
                "columns": cols,
                "primary_key": pk_by_table.get(key, []),
                "foreign_keys": fks_by_table.get(key, []),
                "indexes": list(indexes_by_table.get(key, {}).values()),
            }
        )

    return {"tables": tables}


def bracket_columns(columns: list[str]) -> str:
    return ", ".join(f"[{c}]" for c in columns)


def export_select_sql(schema: str, table: str, columns: list[dict[str, Any]]) -> str:
    names = [c["name"] for c in columns]
    order_parts: list[str] = []
    pk = [c["name"] for c in columns if c.get("is_identity")]
    if pk:
        order_parts = pk[:1]
    elif names:
        order_parts = [names[0]]
    order = f" ORDER BY {bracket_columns(order_parts)}" if order_parts else ""
    qualified = f"{schema}.{table}"
    return f"SELECT {bracket_columns(names)} FROM {qualified}{order}"
