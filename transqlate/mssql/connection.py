from __future__ import annotations

import argparse

try:
    import pymssql
except ImportError as exc:
    pymssql = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from transqlate.config import require, resolve_password


def ensure_pymssql() -> None:
    if pymssql is None:
        raise SystemExit(
            "Missing pymssql. Run: pip install pymssql\n"
            f"Original error: {_IMPORT_ERROR}"
        )


def connect_mssql(args: argparse.Namespace) -> "pymssql.Connection":
    ensure_pymssql()
    kwargs = {
        "server": require(args.mssql_server, "MSSQL server"),
        "port": args.mssql_port,
        "user": require(args.mssql_user, "MSSQL user"),
        "password": resolve_password(
            args.mssql_password, prompt="MSSQL password: "
        ),
        "database": require(args.mssql_database, "MSSQL database"),
        "as_dict": True,
    }
    tds_version = getattr(args, "mssql_tds_version", None)
    encryption = getattr(args, "mssql_encryption", None)
    if tds_version:
        kwargs["tds_version"] = tds_version
    if encryption:
        kwargs["encryption"] = encryption
    return pymssql.connect(**kwargs)
