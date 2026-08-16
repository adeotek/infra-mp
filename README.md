# HomeLab Manager

A self-hosted web application for managing infrastructure, hardware, and
configuration data for home labs and small private data centres.

The core idea: **you define your own data model.** Build entities, attributes,
and relations to match how you think about your environment, then configure a
dashboard and views, and start entering data.

## Features

- **Custom schema engine** — define entities, attributes (typed: text, number,
  boolean, date, enum, reference), and relations between them at runtime.
- **Role-based access control** — three roles (Admin, Maintainer, Viewer) with
  a single enforcement point. No public registration; the admin is seeded on
  first startup.
- **Configurable dashboard & views** — compose the homepage from widgets and
  save filtered, sorted views over any entity.
- **SQLite storage** — zero external services required. One container, one
  process, one database file.
- **Server-rendered UI with HTMX** — no heavy frontend build step.

## Stack

Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite · Jinja2 · HTMX · Argon2id.

## Quick start

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for a full walkthrough.

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000 and log in with the seeded admin account.

## Docker

```bash
docker compose up -d
```

The SQLite database persists in a named volume at `/data`.
