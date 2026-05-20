from __future__ import annotations

import argparse

try:
    import psycopg2
except ImportError as exc:
    psycopg2 = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from transqlate.config import require, resolve_password


def ensure_psycopg2() -> None:
    if psycopg2 is None:
        raise SystemExit(
            "Missing psycopg2. Run: pip install psycopg2-binary\n"
            f"Original error: {_IMPORT_ERROR}"
        )


def connect_postgres(args: argparse.Namespace) -> "psycopg2.extensions.connection":
    ensure_psycopg2()
    return psycopg2.connect(
        host=require(args.postgres_host, "PostgreSQL host"),
        port=args.postgres_port,
        dbname=require(args.postgres_database, "PostgreSQL database"),
        user=require(args.postgres_user, "PostgreSQL user"),
        password=resolve_password(
            args.postgres_password, prompt="PostgreSQL password: "
        ),
    )
