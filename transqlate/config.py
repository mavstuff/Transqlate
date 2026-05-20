"""Shared configuration helpers (env vars, argparse utilities)."""

from __future__ import annotations

import os
from typing import TypeVar

T = TypeVar("T")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


def require(value: str | None, label: str) -> str:
    if not value:
        raise SystemExit(f"Error: {label} is required.")
    return value
