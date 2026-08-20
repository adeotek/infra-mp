# InfraMP

[![CI](https://github.com/adeotek/infra-mp/actions/workflows/ci.yml/badge.svg)](https://github.com/adeotek/infra-mp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

**InfraMP** is a self-hosted web application for managing infrastructure, hardware,
and configuration data — built for home labs and small private data centres.

The core idea: **you define your own data model.** Model your environment as
entities (servers, switches, racks, certificates…), give them typed attributes and
relations, then fill in data through the UI or CSV, and organise it into dashboards
and custom views. No schema migrations, no code changes — the schema is data.

## Features

- **Runtime-defined schema** — entities with typed attributes (text, integer,
  float, boolean, date, enum, references) and relations between them, all defined
  from the UI.
- **Composite entity keys** — mark attributes as part of the entity key to enforce
  uniqueness (e.g. a NIC's `Vendor ^ Model` pair), including partial keys.
- **CSV import & export** — export any entity or view to CSV; import back with
  key-based upsert (matching rows update, new rows insert). Drag-and-drop upload,
  all-or-nothing validation with row-level error reporting.
- **Role-based access control** — three roles (Admin, Maintainer, Viewer) with a
  single enforcement point. No public registration; the admin account is seeded on
  first startup.
- **Configurable dashboard** — compose the homepage from widgets (counts, stats,
  tables) that can be resized, reordered, and linked to entities.
- **Saved views** — filter, sort (by any column, including related entities), and
  save custom views over any entity.
- **Comfortable data grids** — quick search, client-side sorting, full-width
  scrollable tables, icon actions.
- **SQLite storage** — zero external services required. One container, one process,
  one database file.
- **Backup & restore** — download a consistent database snapshot or upload one to
  restore, straight from the UI.
- **Server-rendered UI with HTMX** — no frontend build step.
- **Dark & light themes** — dark by default, switchable, persisted.

## Getting started

### Docker (recommended)

```bash
# Run the latest published image
docker run -d --name infra-mp \
  -p 8000:8000 \
  -v infra-mp-data:/data \
  -e INFRAMP_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  -e INFRAMP_ADMIN_PASSWORD="pick-a-strong-password" \
  ghcr.io/adeotek/infra-mp:latest
```

Or with the bundled compose file (builds from source):

```bash
cp .env.example .env   # then edit INFRAMP_SECRET_KEY / INFRAMP_ADMIN_PASSWORD
docker compose up -d
```

Open <http://localhost:8000> and log in with the admin account you configured. If
`INFRAMP_ADMIN_PASSWORD` is left empty, a random password is generated and printed
to the container logs once on first start.

The SQLite database persists in the `/data` volume — back it up regularly
(UI: *Settings → Backup*).

### Local development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full walkthrough.

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Configuration

All settings are read from environment variables (or a `.env` file) with the
`INFRAMP_` prefix. See [.env.example](.env.example) for the complete list with
descriptions. The essentials:

| Variable | Description |
| --- | --- |
| `INFRAMP_SECRET_KEY` | Secret used to sign session cookies. **Must** be a long random string. |
| `INFRAMP_ADMIN_USERNAME` / `INFRAMP_ADMIN_PASSWORD` | Initial admin account, seeded on first startup when the users table is empty. |
| `INFRAMP_DATA_DIR` | Where the SQLite database is stored (default `./data`). |
| `INFRAMP_SESSION_TTL_DAYS` | Session lifetime in days. |
| `INFRAMP_DEBUG` | FastAPI debug mode — never enable in production. |

## Usage overview

1. **Create entities** — e.g. *Servers*, *Racks*, *SSL Certificates* — and add
   typed attributes to each.
2. **Enter records** — manually or via CSV import. Attributes marked as key parts
   become the record's identity for uniqueness checks and CSV upserts.
3. **Link entities** — add reference attributes (one-to-one or one-to-many) to
   model relations such as *server → rack* or *certificate → servers*.
4. **Organise** — build dashboard widgets and save filtered/sorted views for the
   things you look at often.

## Stack

Python 3.12+ · FastAPI · SQLAlchemy 2.0 · SQLite (WAL) · Jinja2 · HTMX · Argon2id · Alembic.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
guidelines on setting up a development environment, the branch/PR workflow, and
code style.

## Security

Found a vulnerability? Please report it responsibly — see
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 George Benjamin-Schonberger
