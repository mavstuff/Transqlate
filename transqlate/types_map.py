"""Map SQL Server column types to PostgreSQL DDL fragments."""

from __future__ import annotations

from typing import Any


def pg_type_for_column(col: dict[str, Any]) -> str:
    """Return a PostgreSQL type string for a discovered MSSQL column."""
    data_type = (col.get("data_type") or "").lower()
    char_max = col.get("character_maximum_length")
    num_prec = col.get("numeric_precision")
    num_scale = col.get("numeric_scale")
    dt_prec = col.get("datetime_precision")

    if data_type in ("bit",):
        return "boolean"
    if data_type in ("tinyint",):
        return "smallint"
    if data_type in ("smallint",):
        return "smallint"
    if data_type in ("int",):
        return "integer"
    if data_type in ("bigint",):
        return "bigint"
    if data_type in ("real",):
        return "real"
    if data_type in ("float",):
        return "double precision"
    if data_type in ("money", "smallmoney"):
        return "numeric(19,4)"
    if data_type in ("decimal", "numeric"):
        p = num_prec or 18
        s = num_scale if num_scale is not None else 0
        return f"numeric({p},{s})"
    if data_type in ("date",):
        return "date"
    if data_type in ("time",):
        return "time" + (f"({dt_prec})" if dt_prec else "")
    if data_type in ("datetime", "datetime2", "smalldatetime"):
        if dt_prec:
            return f"timestamp({dt_prec})"
        return "timestamp"
    if data_type in ("datetimeoffset",):
        if dt_prec:
            return f"timestamptz({dt_prec})"
        return "timestamptz"
    if data_type in ("uniqueidentifier",):
        return "uuid"
    if data_type in ("binary", "varbinary", "image"):
        if char_max and char_max > 0:
            return f"bytea"
        return "bytea"
    if data_type in ("xml", "text", "ntext"):
        return "text"
    if data_type in ("char", "nchar", "varchar", "nvarchar"):
        if char_max is None or char_max < 0:
            return "text"
        # nvarchar length is characters; PostgreSQL varchar is similar
        return f"varchar({char_max})"
    if data_type in ("timestamp", "rowversion"):
        return "bytea"
    if data_type in ("sql_variant", "geography", "geometry", "hierarchyid"):
        return "text"
    return "text"
