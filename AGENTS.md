# AGENTS.md — InfraMP

Self-hosted infrastructure/hardware/config manager. FastAPI + SQLAlchemy 2.0 + SQLite + Jinja2 + HTMX. Server-rendered UI — **there is no frontend build step**; static assets under `app/static/` are served as-is.

## Commands

- Install: `uv sync` (uv is the only package manager; Python 3.12+, CI uses 3.14)
- Dev server: `make dev` (`uv run uvicorn app.main:app --reload`)
- Verify before done: `make check` → ruff check + ruff format --check + pytest (also the CI order)
- Single test: `uv run pytest tests/test_records.py -v`
- Migrations: `uv run alembic upgrade head` · autogenerate: `make migration m="describe change"`
- Docker: `make up` / `make down`; image runs `alembic upgrade head` at container start

## Architecture (non-obvious)

- **Custom schema engine**: entities/attributes are user-defined *data*, not DDL. Only the static schema (users, sessions, entities, attributes, records, views, dashboard widgets) is Alembic-managed. Changing the dynamic schema never needs a migration.
- **Records are JSON documents** (`Record.data`, JSON column) validated against their entity's attribute schema at write time. No per-entity tables.
- **Relations are reference-typed attributes** (target entity + one/many cardinality), not a separate relations table.
- **Soft delete**: records hidden via `deleted_at`; the UI never hard-deletes.
- **RBAC**: single enforcement point — `require_capability(...)` in `app/auth/dependencies.py`; roles map to fixed capability sets in `app/auth/permissions.py`. Never check roles/capabilities ad hoc in routes or services.
- **Timestamps**: naive UTC everywhere (`app/models/mixins.py` `utcnow()`); SQLite has no tz support. Do not introduce timezone-aware datetimes.
- **Composite entity keys** are joined with `" ^ "` (keyboard-typable) for display and CSV upsert — see `app/services/record_service.py`.
- **Admin seeding**: app lifespan seeds admin only when the users table is empty; if `INFRAMP_ADMIN_PASSWORD` is empty, a random password is printed to stdout once. Tests rely on this seeding (see below).
- **App factory**: `create_app(settings)` wires engine/session_factory/seed; tests inject a `Settings` with a tmp dir. Global `app = create_app()` is the uvicorn entrypoint (`app.main:app`).

## Configuration

- Env vars are prefixed `INFRAMP_`, loaded from `.env` (pydantic-settings, `app/config.py`). DB URL is derived: `sqlite:///{INFRAMP_DATA_DIR}/infra-mp.db`.
- `alembic.ini`'s URL is a placeholder — `alembic/env.py` overrides it with app settings. Don't edit the URL in `alembic.ini`.
- Migrations run with `render_as_batch=True` (required for SQLite ALTERs).

## Rendering & routes

- Always render via `render(request, name, ctx)` from `app/templates.py`, never `TemplateResponse` directly — it injects current_user, app name/version, flash, and sidebar data.
- HTMX requests (header `HX-Request: true`) render fragments (`fragment.html` base); plain requests render the full page as a no-JS fallback. Forms/partials must support both.
- Flash messages travel as `?flash=` query params via `redirect_with_flash` (`app/flash.py`).
- 401 → redirect to `/login?next=...`; 404/403 → rendered `error.html` (handler in `app/main.py`).
- Forms are hand-rolled (`app/form.py`, routes use `Form(...)` params) — no form library.

## Tests

- Tests do **not** run Alembic: `tests/conftest.py` creates schema via `Base.metadata.create_all`. If you change a model, fix the migration *and* note that tests validate against `create_all` output; add autogen migrations for real DBs.
- `client` fixture (TestClient) seeds admin via lifespan; login via `POST /login` with `ADMIN_PASSWORD = "admin-password-123"` (conftest constant). Fixtures: `settings`, `engine`, `db_session`, `client`, `login`.
- No type checker or coverage gate configured; `pytest -q` only.

## Style & conventions

- Conventional commits (`feat:`, `fix:`, `style:`, `docs:`, `test:`); version is single-sourced in `app/__init__.py` (hatchling reads it) and bumped in the same commit as the change — the sidebar displays it.
- Ruff is both linter and formatter: line-length 100, rules `E,F,I,UP,B`. FastAPI dependency calls in default args (`Depends`, `Query`, etc.) are idiomatic here — `extend-immutable-calls` in `pyproject.toml` already allows them; don't "fix" B008 there.
- Every module starts with `from __future__ import annotations` and has a module docstring.
- Layout: `app/routes/` HTTP handlers → `app/services/` business logic → `app/models/` SQLAlchemy → `app/schemas/` pydantic input schemas. Keep logic out of routes.
- Vendored frontend libs (`htmx.min.js`, FontAwesome) live in `app/static/` — do not npm-install equivalents.

## Docs

- Full setup walkthrough: `docs/DEVELOPMENT.md` (setup, migrations, tests, architecture notes).
