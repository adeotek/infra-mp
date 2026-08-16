# Development Guide

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Setup

```bash
git clone <repo-url> infra-mp
cd infra-mp

# Install dependencies and create the virtualenv
uv sync

# Configure the app
cp .env.example .env
# (optional) generate a strong secret:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Database migrations

The static schema (users, sessions, entities, attributes, records, views,
dashboard widgets) is managed with Alembic. The *dynamic* schema — your
entities, attributes, and relations — is data, not DDL, so it never needs
migrations.

```bash
uv run alembic upgrade head          # apply migrations
uv run alembic revision --autogenerate -m "describe change"  # after editing models
```

## Run the dev server

```bash
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000. On first start the admin user is seeded:

- If `HOMELAB_ADMIN_PASSWORD` is set, use it to log in.
- Otherwise a random password is printed to the console once.

## Running tests

```bash
uv run pytest                 # full suite
uv run pytest tests/test_records.py -v   # a single module
```

## Linting & formatting

```bash
uv run ruff check .           # lint
uv run ruff format .          # format
```

## Make targets

A `Makefile` wraps the common commands:

```bash
make help        # list all targets
make dev         # run the dev server with hot reload
make migrate     # apply migrations
make check       # lint + format-check + tests
make build       # build the Docker image
make up / down   # docker compose up/down
```

## CI

`.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`, and
`pytest` on every push to `main` and every pull request, plus a Docker build
job that runs after tests pass.

## Project layout

```
app/
  auth/          # password hashing, sessions, RBAC, admin seeding
  models/        # SQLAlchemy models (static schema)
  routes/        # HTTP handlers per feature area
  schemas/       # pydantic input schemas
  services/      # business logic (schema engine, records, views, users)
  templates/     # Jinja2 templates
  static/        # CSS + vendored htmx
alembic/         # migration environment
tests/           # pytest suite
```

## Architecture notes

- **Records are JSON documents** validated against their entity's attribute
  schema at write time. This keeps the runtime-defined schema engine simple and
  correct at home-lab scale; swap in real columns later if data volumes grow.
- **Relations are reference-typed attributes** (target entity + cardinality
  one/many), not a separate relations table.
- **Soft delete**: records are hidden via a `deleted_at` flag, never hard
  deleted by the UI.
- **RBAC** is enforced through a single `require_capability(...)` dependency;
  roles map to a fixed capability set (see `app/auth/permissions.py`).
- **Timestamps** are naive UTC everywhere (SQLite has no timezone support).
