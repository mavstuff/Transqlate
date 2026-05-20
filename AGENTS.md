# AGENTS.md — Transqlate

Guidance for AI agents and automation working in Transqlate repository.

## Project goal

**Transqlate** migrates SQL Server → PostgreSQL:

1. `tq export` — introspect MSSQL, write `schema.json` + UTF-8 TSV tables + `manifest.json` (folder or zip).
2. `tq import` — read dump, emit PG DDL (tables, FKs, indexes), load data, reset identity sequences.

Entry point: `tq.py` → `transqlate.cli.main()`.


## Architecture

```
tq.py
  └── transqlate/cli.py          # subcommands: export, import, schema
        ├── mssql/export.py      # run_export
        │     └── mssql/schema.py   # discover_schema, export_select_sql
        ├── postgres/import_data.py # run_import
        │     └── postgres/schema.py  # apply_schema, DDL helpers
        ├── dump_format.py       # TSV, manifest, schema.json, topo sort
        ├── types_map.py         # MSSQL data_type → PG type string
        └── archive.py           # zip in/out
```

### Dump contract (`transqlate-tsv` v1)

- `manifest.json` — `format`, `version`, `import_order`, per-table `file` / `rows` / `columns`
- `schema.json` — `tables[]` with `columns`, `primary_key`, `foreign_keys`, `indexes`
- `{schema}/{table}.tsv` — header row + tab-separated UTF-8 data

Changing on-disk format requires bumping `FORMAT_VERSION` in `dump_format.py` and updating import validation.

## Safe change zones

| Area | Notes |
|------|--------|
| `types_map.py` | Add MSSQL type mappings; keep symmetric with `parse_cell` in `postgres/import_data.py` for binary/bool |
| `mssql/schema.py` | Discovery queries; exclude computed columns from export |
| `postgres/schema.py` | DDL generation; FK/index order: tables → FKs → indexes |
| `mssql/export.py` / `postgres/import_data.py` | Batch sizes, CLI flags only if behavior stays compatible |

Avoid breaking existing dumps without a version bump.

## Common agent tasks

### Add a SQL Server type mapping

1. `transqlate/types_map.py` — `pg_type_for_column()`
2. If special serialization: `dump_format.serialize_cell()` and `postgres/import_data.parse_cell()`

### Add a CLI flag

1. `add_export_args` or `add_import_args` in the respective module
2. Wire through `run_export` / `run_import`
3. Document in `README.md`

### Fix import order / FK errors

- Check `dump_format.topological_table_order()`
- Import applies FKs after all `CREATE TABLE`; data load uses `import_order` from manifest
- For circular FKs: `--skip-foreign-keys` on import, then manual `ALTER TABLE`

### Generate DDL without loading data

```bash
python tq.py schema --input DUMP --output out.sql
python tq.py import --input DUMP --schema-only --drop-existing
```

## Environment variables

**Export:** `MSSQL_SERVER`, `MSSQL_PORT`, `MSSQL_DATABASE`, `MSSQL_USER`, `MSSQL_PASSWORD`, `MSSQL_SCHEMAS`

**Import:** `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DATABASE`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SCHEMA`

## Testing checklist (manual)

Agents should run when possible:

```bash
pip install -r requirements.txt
python tq.py --help
python tq.py export --help
python tq.py import --help
python -m py_compile tq.py transqlate/**/*.py
```

With live databases:

```bash
python tq.py export --output /tmp/tq-test --mssql-database ... 
python tq.py schema --input /tmp/tq-test --output /tmp/tq-test.sql
python tq.py import --input /tmp/tq-test --postgres-database ... --drop-existing
```

Verify row counts in `manifest.json` match `SELECT COUNT(*)` on PG.

## Pitfalls

- **pymssql** on Windows often targets local SQL Server; Linux export needs network route to MSSQL.
- **Quoted identifiers:** PG uses `"ColumnName"` for PascalCase MSSQL columns.
- **`dbo` → `public`:** override with `--postgres-schema` on import.
- **Computed columns** are skipped in discovery; do not expect TSV columns for them.
- **Binary data** is hex in TSV; import decodes via `parse_cell`.
- **`reset_identity_sequences`** uses `pg_get_serial_sequence` on the qualified PG table name after import.
- Do not commit secrets; use env vars only in docs/examples.
- Passwords: `resolve_password()` in `config.py` — uses CLI/env when set, else `getpass` prompt in `mssql/connection.py` and `postgres/connection.py`.


## Commit style

Short imperative subject; mention whether export format version changed.

Example: `Add datetimeoffset mapping for PostgreSQL timestamptz`
