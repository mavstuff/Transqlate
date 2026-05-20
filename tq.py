#!/usr/bin/env python3
"""
Transqlate — SQL Server to PostgreSQL migration.

Main entry point. See README.md for usage.
"""

from __future__ import annotations

import sys

from transqlate.cli import main

if __name__ == "__main__":
    sys.exit(main())
