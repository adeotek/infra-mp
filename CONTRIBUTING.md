# Contributing to InfraMP

Thanks for considering a contribution! This document explains how to set up the
project, what conventions to follow, and how changes get merged.

## Code of conduct

Keep it professional and respectful: assume good faith, keep feedback constructive,
and remember this is a hobby-scale project maintained by volunteers. Discrimination
and harassment are not tolerated.

## Getting started

1. Fork the repository and clone your fork.
2. Follow [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) to set up the environment
   (`uv sync`, `cp .env.example .env`, `uv run alembic upgrade head`).
3. Create a feature branch off `main` — `main` is protected against direct pushes.

```bash
git checkout main && git pull origin main
git checkout -b feat/your-change
```

## Making changes

- **Tests** — add or update tests for any behavioural change. The suite uses
  pytest with fixtures defined in `tests/conftest.py`.
- **Style** — ruff is the single linter/formatter (`line-length = 100`):

  ```bash
  uv run ruff check .            # lint
  uv run ruff format .           # format
  uv run pytest                  # full test suite
  ```

- **Commit messages** — conventional commits (`feat:`, `fix:`, `chore:`, `docs:`,
  `test:`, `style:`, `refactor:`). Keep the first line under ~72 characters and
  explain *why* in the body when it is not obvious.
- **Pull requests** — push your branch to your fork and open a PR into `main`.
  CI runs lint, format check, tests, and a Docker build on every PR. Link any
  related issue, describe what changed and how you verified it.

### Where things live

```
app/
  auth/          # password hashing, sessions, RBAC, admin seeding
  models/        # SQLAlchemy models (static schema)
  routes/        # HTTP handlers per feature area
  schemas/       # pydantic input schemas
  services/      # business logic (schema engine, records, views, CSV, backup)
  templates/     # Jinja2 templates
  static/        # CSS + JS + vendored htmx
alembic/         # migration environment
tests/           # pytest suite
```

### Architecture notes

- **Records are JSON documents** validated against their entity's attribute schema
  at write time.
- **Relations are reference-typed attributes** (target entity + cardinality
  one/many), not a separate relations table.
- **Soft delete** — records are hidden via a `deleted_at` flag.
- **RBAC** is enforced through a single `require_capability(...)` dependency;
  roles map to a fixed capability set in `app/auth/permissions.py`.
- **Timestamps** are naive UTC everywhere (SQLite has no timezone support).
- **Static schema changes** (models) require an Alembic migration:
  `uv run alembic revision --autogenerate -m "describe change"`.

## Reporting bugs / requesting features

- Search [existing issues](https://github.com/adeotek/infra-mp/issues) first.
- For bugs include: version (sidebar footer), what you did, what you expected,
  what happened, and relevant logs. Fill in the issue template — it guides you.
- For features: describe the use case and how you would expect it to behave.

## Releases

- The version lives in `app/__init__.py` (single source of truth; pyproject reads
  it dynamically). Bump the patch for fixes, the minor for feature sets.
- Docker images are published to
  [GHCR](https://github.com/adeotek/infra-mp/pkgs/container/infra-mp) with the
  *Publish Docker image* workflow (`workflow_dispatch`). The image tag defaults to
  the app version and can be overridden when triggering the workflow.
- Release process for maintainers: merge to `main` → run tests → bump version →
  trigger the publish workflow.

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).
