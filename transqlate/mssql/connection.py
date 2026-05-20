from __future__ import annotations

import argparse

try:
    import pymssql
except ImportError as exc:
    pymssql = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from transqlate.config import require


def ensure_pymssql() -> None:
    if pymssql is None:
        raise SystemExit(
            "Missing pymssql. Run: pip install pymssql\n"
            f"Original error: {_IMPORT_ERROR}"
        )


def connect_mssql(args: argparse.Namespace) -> "pymssql.Connection":
    ensure_pymssql()
    return pymssql.connect(
        server=require(args.mssql_server, "MSSQL server"),
        port=args.mssql_port,
        user=require(args.mssql_user, "MSSQL user"),
        password=require(args.mssql_password, "MSSQL password"),
        database=require(args.mssql_database, "MSSQL database"),
        as_dict=True,
    )
