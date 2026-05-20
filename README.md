# Transqlate

Migrate a Microsoft SQL Server database to PostgreSQL in two steps:

1. **Export** — dump data to a portable, human-readable UTF-8 TSV package (folder or `.zip`), with schema metadata discovered from the live MSSQL database.
2. **Import** — recreate tables, foreign keys, and indexes in PostgreSQL, then load the TSV files.

The main entry point is `tq.py`. The implementation lives in the `transqlate` package.

**Schema is inferred from the source database**

## Requirements

- Python 3.10+
- SQL Server reachable from the export machine (`pymssql`)
- PostgreSQL reachable from the import machine (`psycopg2-binary`)

```bash
pip install -r requirements.txt
```

## Quick start

### 1. Export on Windows (SQL Server host)

```bash
set MSSQL_SERVER=localhost
set MSSQL_PORT=1433
set MSSQL_DATABASE=MyApp
set MSSQL_USER=sa
set MSSQL_PASSWORD=secret

python tq.py export --output myapp-export.zip
```

### 2. Transfer the dump

Copy `myapp-export.zip` (or the export folder) to the PostgreSQL host.

### 3. Import on Linux (or any host with network access to PostgreSQL)

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DATABASE=myapp
export POSTGRES_USER=myapp
export POSTGRES_PASSWORD=secret

python tq.py import --input myapp-export.zip --drop-existing
```

`--drop-existing` drops and recreates tables (destructive). Omit it when loading into empty tables created manually.

## Dump layout

```
myapp-export/
  manifest.json      # format version, import order, row counts
  schema.json        # tables, columns, PKs, FKs, indexes (from MSSQL)
  dbo/
    Customers.tsv
    Orders.tsv
    ...
```

- **Encoding:** UTF-8  
- **Delimiter:** tab (TSV)  
- **NULL:** empty field  
- **Booleans:** `true` / `false`  
- **Dates/times:** ISO-like `YYYY-MM-DD HH:MM:SS`  
- **Binary:** hex string (restored on import)

## Commands

### `tq export`

Discover schema and export all base tables in the given MSSQL schema(s).

```bash
python tq.py export --help
```

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--output` | | `transqlate-export` | Folder or `.zip` path |
| `--mssql-server` | `MSSQL_SERVER` | `localhost` | Server host |
| `--mssql-port` | `MSSQL_PORT` | `1433` | TCP port |
| `--mssql-database` | `MSSQL_DATABASE` | | Database name (required) |
| `--mssql-user` | `MSSQL_USER` | | Login (required) |
| `--mssql-password` | `MSSQL_PASSWORD` | | Password (required) |
| `--mssql-schemas` | `MSSQL_SCHEMAS` | `dbo` | Comma-separated schemas |
| `--exclude-tables` | | | `schema.table` to skip |
| `--batch-size` | | `2000` | Rows per fetch |

**Examples**

```bash
# Export dbo only to a directory
python tq.py export --output ./dump --mssql-database Sales

# Export dbo + custom schema to zip
python tq.py export --output sales.zip --mssql-schemas dbo,audit --mssql-database Sales

# Skip a table
python tq.py export --exclude-tables dbo.__MigrationHistory --mssql-database Sales

# Remote SQL Server
python tq.py export --mssql-server db.example.com --mssql-port 1433 \
  --mssql-database MyApp --mssql-user migrator --mssql-password "%PASS%"
```

### `tq import`

Apply DDL (unless disabled), truncate (unless disabled), load data in FK-safe order, reset identity sequences.

```bash
python tq.py import --help
```

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--input` | | `transqlate-export` | Dump folder or `.zip` |
| `--postgres-host` | `POSTGRES_HOST` | `localhost` | |
| `--postgres-port` | `POSTGRES_PORT` | `5432` | |
| `--postgres-database` | `POSTGRES_DATABASE` | | Target DB (required) |
| `--postgres-user` | `POSTGRES_USER` | | (required) |
| `--postgres-password` | `POSTGRES_PASSWORD` | | (required) |
| `--postgres-schema` | `POSTGRES_SCHEMA` | | Force all tables into this PG schema |
| `--batch-size` | | `500` | INSERT batch size |
| `--no-truncate` | | | Keep existing rows (may duplicate PKs) |
| `--no-create-schema` | | | Tables must already exist |
| `--drop-existing` | | | `DROP TABLE ... CASCADE` before create |
| `--skip-indexes` | | | Skip non-PK indexes |
| `--skip-foreign-keys` | | | Skip FK constraints |
| `--schema-only` | | | DDL only, no data |

**Examples**

```bash
# Full migration into a new database
createdb myapp
python tq.py import --input myapp-export.zip --postgres-database myapp \
  --postgres-user myapp --postgres-password secret --drop-existing

# Data only (schema created manually)
psql -d myapp -f schema.sql
python tq.py import --input myapp-export.zip --no-create-schema

# Reload data without dropping tables
python tq.py import --input myapp-export.zip --drop-existing --schema-only
python tq.py import --input myapp-export.zip --no-create-schema

# Map everything into a single PG schema
python tq.py import --input dump.zip --postgres-schema app --drop-existing

# Staging: tables + data, defer FKs for speed
python tq.py import --input dump.zip --skip-foreign-keys --drop-existing
python tq.py import --input dump.zip --no-create-schema --no-truncate --schema-only
# then add FKs manually or re-run with only FK DDL from `tq schema`
```

### `tq schema`

Emit PostgreSQL DDL from `schema.json` inside a dump (no database connection).

```bash
python tq.py schema --input myapp-export.zip --output postgresql-schema.sql
python tq.py schema --input ./dump --output - | less
```

Useful for review, manual edits, or DBA sign-off before import.

## Schema mapping

| SQL Server | PostgreSQL (default) |
|------------|----------------------|
| `dbo` schema | `public` |
| Other schemas | Same name (created if missing) |
| `bit` | `boolean` |
| `tinyint` | `smallint` |
| `int` / `bigint` | `integer` / `bigint` |
| `nvarchar(n)` / `varchar` | `varchar(n)` |
| `nvarchar(max)` / `text` | `text` |
| `datetime` / `datetime2` | `timestamp` |
| `uniqueidentifier` | `uuid` |
| `decimal(p,s)` | `numeric(p,s)` |
| Identity columns | `GENERATED BY DEFAULT AS IDENTITY` |

Identifiers keep their original names (quoted in PostgreSQL when needed). Foreign keys and non-clustered indexes are recreated from MSSQL metadata. Computed columns are omitted from export.

## Import order

Tables are ordered topologically using foreign-key dependencies so parent rows load before children. Cycles fall back to alphabetical order; use `--skip-foreign-keys` if you need to load in a custom order and add constraints later.

## Typical workflows

### Greenfield database

```bash
python tq.py export --output prod.zip --mssql-database Prod ...
# on PG server
createdb prod_pg
python tq.py import --input prod.zip --postgres-database prod_pg --drop-existing
```

### Review DDL before load

```bash
python tq.py export --output prod.zip ...
python tq.py schema --input prod.zip --output review.sql
# edit review.sql if needed, then:
psql -d prod_pg -f review.sql
python tq.py import --input prod.zip --no-create-schema
```

### Partial export (one schema, exclude staging tables)

```bash
python tq.py export --mssql-schemas dbo \
  --exclude-tables dbo.StagingOrders,dbo.TempImport \
  --output partial.zip
```

### Re-run data after failed import

```bash
python tq.py import --input prod.zip --drop-existing
# or truncate-only:
python tq.py import --input prod.zip --no-create-schema
```

## Troubleshooting

| Problem | Things to try |
|---------|----------------|
| `Missing pymssql` | `pip install pymssql` on export host |
| `Missing psycopg2` | `pip install psycopg2-binary` on import host |
| Column mismatch on import | Re-export; dump and code version must match |
| FK violation on import | Ensure full dump; try `--skip-foreign-keys` then add FKs |
| Duplicate key | Use default truncate or `--drop-existing` |
| Permission denied on PG | Grant `CREATE` on database and schemas |
| Unicode garbled | Confirm TSV opened as UTF-8; export always writes UTF-8 |

## Project layout

```
tq.py                      # CLI entry
transqlate/
  cli.py                   # argparse subcommands
  dump_format.py           # TSV + manifest + schema.json
  types_map.py             # MSSQL → PG type mapping
  archive.py               # zip helpers
  mssql/
    connection.py
    schema.py              # discover metadata
    export.py
  postgres/
    connection.py
    schema.py              # DDL generation
    import_data.py
```

(c) 2026 Artem Moroz <artem.moroz@gmail.com>
