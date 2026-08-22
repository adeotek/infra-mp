# InfraMP Code Review — Security, Performance, UI & Quality Audit

- **Date:** 2026-08-22
- **Scope:** `app/` (routes, services, models, schemas, auth), templates, static assets, Docker/CI, alembic, tests
- **Baseline:** `make check` passes — 419 tests green, ruff check + format clean
- **Method:** Four independent domain reviews (security / performance / UI-UX / general quality), every finding cross-checked against the code

---

## Executive Summary

InfraMP is a well-structured, unusually well-tested codebase. The security baseline is solid for a self-hosted tool (Argon2id, hashed tokens, capability-based RBAC with a single enforcement point, full Jinja2 autoescape, ORM-only queries, CSV formula-injection guards). The main weaknesses concentrate in four areas:

1. **One guaranteed runtime crash** in the MCP server (`w.span` on `DashboardWidget`, which only has `width`).
2. **No CSRF protection** — the single most important security gap.
3. **HTMX failure modes** — validation errors on modal forms are invisible (htmx 2.0 discards 4xx swaps), and error/login pages render full documents into fragment targets.
4. **All-in-memory data paths** — no pagination anywhere, per-request duplicate record loads (dashboard/views), and `async def` handlers running blocking SQLAlchemy work on the event loop.

Full detail below, prioritized as **P0** (fix now) → **P3** (nice-to-have).

---

## P0 — Fix immediately

### 1. MCP tool `list_dashboard_widgets` always crashes
- **Domain:** quality · **Severity:** Critical bug
- **Location:** `app/mcp_server.py:665`
- **Issue:** `"span": w.span` — `DashboardWidget` has no `span` attribute; the model defines `width` (`app/models/dashboard.py:33`). Every invocation raises `AttributeError`.
- **Why undetected:** No test actually calls this tool (only the tool list is asserted).
- **Fix:** Change to `"width": w.width`; add a test that invokes the tool via `tools/call`.

### 2. No CSRF protection on any state-changing endpoint
- **Domain:** security · **Severity:** High
- **Location:** all POST routes (`app/routes/*.py`), `app/main.py` (no middleware), `app/static/app.js:288-294` (reorder `fetch` calls)
- **Issue:** Zero CSRF tokens, no Origin/Referer validation. Only defense is `SameSite=Lax` on the session cookie (`app/routes/auth.py:56-62`), which fails against same-site subdomain attacks and older browsers.
- **Impact:** A malicious site can drive a logged-in admin's browser to create users, revoke tokens, delete records, or restore a hostile DB backup. The project's own `SECURITY.md` lists CSRF as in scope.
- **Fix:** Per-session CSRF token injected into every form (plain + HTMX) and validated on all POSTs, or an Origin-validating middleware. HTMX forms can carry the token via `hx-headers`.

---

## P1 — Fix soon

### Security

**3. No rate limiting / lockout on login** (`app/routes/auth.py:35-63`, Medium)
Argon2id gives only weak inherent throttling; the well-known `admin` username makes dictionary attacks practical. Fix: per-IP + per-username rate limiting (e.g. slowapi or a DB-backed sliding window), optional lockout.

**4. Session cookie lacks `Secure` flag** (`app/routes/auth.py:56-62`, Medium)
`httponly=True, samesite="lax"` but no `secure=True`, and no setting to enable it. Session token travels over plain HTTP behind TLS proxies. Fix: add `INFRAMP_COOKIE_SECURE` (default on when `base_url` is HTTPS).

**5. No server-side password strength on user create/update** (`app/services/user_service.py:32-84`, Medium)
`create_user`/`update_user` hash any string, including 1 character; the pydantic `UserCreate`/`UserUpdate` schemas with `min_length=8` are never used by routes. Only `change_password` enforces length. Fix: enforce minimum length in the service, or wire the schemas into the routes.

**6. Backup restore: unbounded upload + zip-bomb exposure** (`app/routes/backup.py:65-114`, Medium)
`content = await file.read()` with no size cap, then `zf.read(names[0])` fully decompresses the first `.db` entry into memory. CSV import enforces `MAX_UPLOAD_BYTES`; restore does not. Fix: upload size cap + uncompressed-size cap (streamed reads), reject before materializing.

**7. `update_user` can lock out the last active admin** (`app/services/user_service.py:58-84`, Medium)
`delete_user` guards against removing the last active admin, but `update_user` happily deactivates or demotes them. Fix: apply the same last-active-admin count check when the update would deactivate/demote one.

**8. Login timing leak for unknown usernames** (`app/routes/auth.py:43-51`, Low)
`verify_password` short-circuits when the user doesn't exist, so responses are measurably faster — username enumeration. Fix: run a dummy Argon2 verify when the user is missing/inactive.

**9. TrustedHost middleware absent** (`app/main.py`, Low) — app accepts any `Host` header. Fix: `TrustedHostMiddleware` with a configurable allowlist.

**10. API tokens never expire** (`app/models/api_token.py:19-29`, `app/services/api_token_service.py:22-37`, Low)
Tokens valid until manual revocation; a leaked token grants access forever. Fix: optional `expires_at` column, enforced in `verify_token`.

### Performance

**11. `async def` handlers run blocking SQLAlchemy work on the event loop** (Medium)
Locations: `app/routes/api_tokens.py:62,99,125`, `backup.py:66`, `records.py:107,168,214`, `users.py:54,103`, `views.py:217,265,379`, plus `entities.py`/`dashboard.py`. The CSV import — potentially minutes of sync DB work — runs directly on the loop that also serves the MCP endpoint and static files. Fix: convert these handlers to sync `def` (FastAPI runs them in the threadpool; SQLAlchemy here is fully sync). Keep `async def` only where async IO is awaited.

**12. No pagination anywhere** (High)
`record_service.list_records` (`app/services/record_service.py:38-45`) loads every record of an entity; record lists, view detail bodies, and dashboard table widgets render the full set; CSV export loads everything. Page size grows linearly with data. Fix: server-side pagination (LIMIT/OFFSET or keyset) with prev/next controls, plus a "show more" HTMX endpoint; stream CSV export.

**13. Same entity's records loaded 3-4x per request in views** (`app/services/view_service.py`, High)
Referenced entities' records are re-queried per reference column while rendering a view. Fix: cache per-entity record lists in a request-scoped dict during render.

**14. Dashboard widgets each independently reload the same entities** (`app/routes/dashboard.py:46-110`, Medium)
Count widgets load the full record set just to `len()` it. Fix: load each entity's records once per dashboard request and share across widgets; use SQL `COUNT(*)` for count widgets.

**15. CSV import is O(n²) on large files** (`app/services/csv_service.py`, Medium)
Per-row full-entity reloads for key/uniqueness checks. Fix: load entity records once before the loop; push key/uniqueness checks into SQL with expression indexes on `json_extract(record.data, '$.<slug>')` for key attributes.

**16. No SQLite `busy_timeout` / `synchronous` pragmas** (`app/db.py`, Low)
WAL is on and `entity_id`/`deleted_at` are indexed, but concurrent writers (MCP + web) can hit `database is locked`. Fix: `PRAGMA busy_timeout=5000` and `synchronous=NORMAL` on connect; add a composite index on `(entity_id, deleted_at)`.

**17. `verify_token` commits on every MCP request** (`app/services/api_token_service.py:40-58`, Info)
`last_used_at` update + commit per authenticated tool call = write transaction per read request. Fix: throttle the update (only if older than ~1 minute).

### UI / UX

**18. Modal form validation errors are invisible (400 responses never swapped)** (High)
htmx 2.0's default `responseHandling` discards 4xx/5xx responses; all modal forms POST via `hx-post` targeting `#modal-body` and the routes return 400 with the error fragment (`app/routes/entities.py:112-121`, `users.py:71-85`, `auth.py:91-100`). Result: submit appears to do nothing. Fix: global `htmx:beforeSwap` handler in `app.js` that allows swapping 4xx into `#modal-body`.

**19. HTMX error responses inject the full page into the fragment target** (High)
`app/templates/error.html:1` hardcodes `{% extends "base.html" %}`, ignoring the `base_template="fragment.html"` that `render()` sets for HTMX requests (`app/templates.py:68`). 404/403 during an HTMX request swaps the entire `<html>` (sidebar, topbar, dialogs) into `#modal-body`/`#view-detail-body`; 401 returns a 303 that htmx follows, swapping the login page in-place. Fix: make `error.html` extend `base_template`; for 401 return `HX-Redirect` instead of 303.

**20. No-JS fallback broken in four places** (High — violates the project's own AGENTS.md rule)
- **Advanced filter bar** (`app/templates/views/detail_body.html:3-44`): form has no `action`/`method`; operator select and remove buttons are HTMX-only.
- **File uploads** (`app/templates/records/import.html:6-12`, `backup.html:21-27`): inputs are `display:none`, only the JS drop-zone click opens them.
- **Enum/reference attribute config** (`app/templates/attributes/form.html:27-48`): `.conditional { display:none }` until JS flips it — impossible to configure those types without JS.
- **Multi-reference fields** (`app/templates/records/form.html:56-78`): source select has no `name`; submitted values are JS-built hidden inputs — value silently dropped without JS.
Fix: native fallbacks (visible `<input>` + `<label for>`, `action`/`method` on forms, server-rendered conditional visibility), JS as enhancement only.

**21. No loading feedback on any HTMX request** (Medium)
Zero `hx-indicator` usage; modals open instantly empty and filter bars swap silently. Fix: add `hx-indicator` + spinner styles, or a global `htmx:beforeRequest`/`afterRequest` busy class in `app.js`.

**22. Record forms lack per-field error feedback and `required`** (`app/templates/records/form.html:32-92`, Medium)
Required attributes show `*` but inputs have no `required`, `aria-invalid`, or `aria-describedby`; server errors are one joined string at the top. Fix: return slug → error dict from the service and render per-field messages.

**23. Dark-theme button text fails WCAG AA contrast** (`app/static/style.css:29-51,410-414`, Medium)
`--primary: #3b82f6` (~3.7:1 vs white), `--teal: #14b8a6` (~2.5:1), `--danger: #ef4444` (~3.8:1) all below 4.5:1 at 0.9rem. Fix: darken dark-theme button fills (e.g. `#2563eb`/`#0f766e`/`#b91c1c`).

**24. 500 errors return raw JSON to browser users** (`app/main.py:95-120`, Medium)
Only `StarletteHTTPException` gets the styled `error.html`; unhandled exceptions fall through to FastAPI's `{"detail":"Internal Server Error"}`. Fix: add a 500 handler rendering `error.html` and logging the traceback.

**25. Filter-bar validation reloads the whole page in HTMX mode** (`app/routes/views.py:287-329`, Low)
"Enter a filter value first." returns `HX-Redirect` → full navigation for a message that belongs next to the input. Fix: return the `detail_body` fragment with an inline error for HTMX requests.

---

## P2 — Should fix

**26. Unvalidated `int()` conversions → 500s on crafted form input** (`app/routes/dashboard.py:83-87`, `entities.py:54`, `views.py:223`, Medium)
`int(raw.get("entity_id"))` raises uncaught `TypeError`/`ValueError` → 500 instead of 400. Fix: try/except and raise `HTTPException(400)`, matching the pattern already used in the reorder endpoints.

**27. `INFRAMP_SECRET_KEY` is dead config with misleading docs** (`app/config.py:22`, `.env.example`, `README.md`, `SECURITY.md`, Medium)
Documented as "secret used to sign session cookies" but never read — sessions are server-side hashed tokens. Operators get false assurance and an insecure-looking default (`change-me-in-production`). Fix: actually use it (e.g. sign flash messages / derive a CSRF key) or remove it everywhere.

**28. `update_attribute` allows schema changes that invalidate existing records** (`app/services/schema_service.py:191-222`, Medium)
With records present, only slug/`is_active` are locked; `data_type`, `is_unique`, `is_key` still change, leaving stored values un-revalidated (e.g. INTEGER→BOOLEAN leaves `8` in JSON). Fix: reject those changes when `has_records`, or re-validate/re-coerce all existing values.

**29. DECIMAL values stored as `float` lose precision** (`app/services/validation.py:38-42`, Medium)
`float(Decimal(...))` round-trips through JSON with representation noise (`0.30000000000000004`). Fix: store canonical `str(Decimal(...))` and format for display.

**30. DATETIME coercion accepts tz-aware strings** (`app/services/validation.py:67-73`, Low)
Breaks the naive-UTC convention documented in AGENTS.md. Fix: strip tzinfo after parsing (or reject aware inputs).

**31. `is_unique` never detects duplicates on many-reference attributes** (`app/services/record_service.py:166-178`, Low)
Compares a list against an int — always False. Fix: membership check for list values or skip uniqueness for many-refs.

**32. `/healthz` doesn't check the database** (`app/main.py:122-124`, Low)
Docker HEALTHCHECK reports healthy on a corrupt DB. Fix: `SELECT 1` and return 503 on failure.

**33. Backup restore doesn't verify alembic version** (`app/routes/backup.py:117-136`, Low)
`_is_valid_database` checks `quick_check` + `users` table only; a stale-version backup can leave the DB at an old revision. Fix: check `alembic_version` against head, or run `alembic upgrade head` after restore.

**34. CSV import swallows programming errors** (`app/services/csv_service.py:254-256`, Low)
Bare `except Exception` → rollback + generic message, no logging. Fix: `logger.exception(...)` before rollback.

**35. `_render_table_widget` dereferences `widget.view.config` without a None check** (`app/routes/dashboard.py:51-54`, Low)
Orphaned `view_id` (manual DB edit) 500s the dashboard. Fix: `if widget.view is not None` guard.

**36. `_apply_sort` can `TypeError` on mixed-type column values** (`app/services/view_service.py:436`, Low)
`_sortable` normalizes bool/list but not int-vs-str mixes from legacy data. Fix: type-tagged sort key or `str(...).lower()` fallback.

**37. User menu `aria-expanded` stale; `role="menu"` without keyboard nav** (`app/templates/base.html:139-149`, `app/static/app.js:146-160`, Low)
Fix: sync `aria-expanded` in the click handler; implement arrow-key nav or drop the `menu` role.

**38. Sortable table headers are mouse-only** (`app/static/app.js:380-407`, Low)
Fix: `tabindex="0"` + Enter/Space handling; keep `aria-sort` in sync.

**39. Escape key deliberately blocked in modals** (`app/static/app.js:217-220`, Low)
Fix: remove the `cancel` preventDefault (or only suppress while the form is dirty).

**40. MCP docstring lists nonexistent data type "number"** (`app/mcp_server.py:465-471`, Low)
Fix: docstring should say `integer, decimal`.

**41. Expired sessions only purged at login** (`app/auth/sessions.py:40-50`, Low)
Fix: opportunistically delete the expired row in `resolve_user`.

**42. `require_admin` bypasses the capability model** (`app/auth/dependencies.py:45-48`, used in `app/routes/backup.py:34,39,66`, Low)
AGENTS.md mandates a single enforcement point. Fix: add a `MANAGE_BACKUP` capability and use `require_capability`.

**43. `UserCreate`/`UserUpdate` schemas are dead code** (`app/schemas/user.py:10-22`, Low)
Fix: use them in routes (free validation) or delete.

---

## P3 — Nice to have

**44. Drag-and-drop reordering has no keyboard/no-JS alternative** (`app/static/app.js:241-298`, `app/templates/entities/detail.html:27-42`, `dashboard/config.html:50-59`) — add up/down buttons posting to the same reorder endpoint.

**45. Reorder failure reloads the page** (`app/static/app.js:288-295`) — revert DOM order and show a toast instead of `window.location.reload()`.

**46. Unlabeled inputs: token name and filter value** (`app/templates/api_tokens.html:35`, `my_tokens.html:34`, `views/detail_body.html:14`) — add `<label>`/`aria-label`.

**47. Users table has no empty state** (`app/templates/users/list.html:8-33`) — mirror the other list templates' `.empty-state` blocks.

**48. Dashboard table widgets with zero records render headers only** (`app/templates/dashboard.html:21-36`) — check `w.data.rows` and render "No records yet".

**49. Flash messages persist in the URL, no dismiss or live-region semantics** (`app/templates.py:65-66`, `app/templates/base.html:158-160`) — add `role="status"/"alert"`, a dismiss button, and strip `?flash=` via `history.replaceState`.

**50. `flash_type` query param injected into a class attribute** (`app/templates/base.html:158-160`) — map to a fixed `{success, error}` set in `templates.py`.

**51. Modal dialog has no accessible name** (`app/templates/base.html:169-174`) — `aria-labelledby` pointing at the content heading.

**52. Mobile drawer lacks Escape/focus management and a dynamic label** (`app/static/app.js:649-666`, `app/templates/base.html:129-131`).

**53. `datetime_local` filter crashes on `datetime` objects** (`app/templates.py:15`) — handle both str and datetime.

**54. Seed admin race on first boot** (`app/auth/seed.py:22-24`) — catch `IntegrityError` / `ON CONFLICT DO NOTHING`.

**55. Admin seed prints the random password to stdout** (`app/auth/seed.py:26-40`) — document log exposure; optionally print a change-password hint instead.

**56. Docker container runs as root** (`Dockerfile`) — add non-root `USER` and make `/data` writable by it.

**57. `debug` setting never wired to FastAPI** (`app/config.py:28`, `app/main.py:60`) — pass `debug=settings.debug` or remove.

**58. `widget_type` not validated on create/update** (`app/routes/dashboard.py:144-167,187-209`) — validate against `{"table", "count"}`.

**59. MCP `list_records` sorts numeric values as strings** (`app/mcp_server.py:254-258`) — sort by coerced typed value.

**60. MCP `_user_id` depends on SDK principal JSON layout** (`app/mcp_server.py:87-96`) — add a pinned-format comment + regression test.

**61. Route tests hardcode entity/attribute IDs** (`tests/test_records_routes.py:10-24` et al.) — resolve IDs from responses instead.

**62. Record data values have no length limits** (`app/services/validation.py:27-28`) — add per-attribute max-length validation and/or a global request body size cap.

**63. `dist/` build artifacts in the working tree** — stale wheels next to 0.6.0 source; add to `make clean`.

---

## What's done well

- **Clean layering:** routes stay thin; business logic in services; consistent route/service/model/schema split.
- **Single RBAC enforcement point:** `require_capability(...)` applied consistently across web routes and MCP tools; no ad-hoc role checks (one noted exception, #42).
- **Session/token hygiene:** 256-bit session tokens and 192-bit API tokens, stored only as SHA-256 hashes; token shown exactly once; new session token per login (no fixation); indexed DB lookup (no timing leak).
- **XSS:** full Jinja2 autoescape, zero `|safe`/`Markup` usage anywhere.
- **SQL injection:** ORM-only, no raw SQL or f-string queries.
- **CSV hygiene:** formula-injection guard (`_safe_cell`), BOM-tolerant parsing, all-or-nothing import with row errors + rollback, key-based upsert.
- **Consistent soft delete** with `deleted_at` filtering in every list/count path.
- **Test suite (~5.5k lines, 419 tests):** behavior-focused HTTP tests, HTMX fragment tests, CSV round-trips, backup/restore, MCP auth/capability tests.
- **Ops hygiene:** `uv.lock` pinning, Makefile targets matching CI, Dockerfile HEALTHCHECK + pre-serve migrations, complete `.env.example`/`.gitignore`/`.dockerignore`.
- **Alembic discipline:** linear `down_revision` chain, `render_as_batch=True`, URL sourced from app settings.
- **Nice touches:** `_safe_next` open-redirect guard, `VALID_RETURN_TO` allowlist, vendored current frontend libs (htmx 2.0.4, FA 7.3.1), no external CDNs, version single-sourced.

## Verified clean (no action)

- Open redirects (relative-only `_safe_next`), path traversal (backup paths from engine URL, zip entries never used as paths), mass assignment (schema-validated writes, `_coerce_role` defaults), password hashing (Argon2id), CSV formula injection, authorization coverage on all 60+ route decorators.

---

## Suggested execution order

1. **P0-1** `w.span` → `w.width` + tool test (10-minute fix).
2. **P0-2** CSRF tokens (largest security win; touches forms + middleware).
3. **P1-11** sync `def` handlers + **P1-18/19** htmx swap fixes (small, high user-visible impact).
4. **P1-12/13/14** pagination + shared per-request record loads (biggest performance wins).
5. Remaining P1s (rate limiting, cookie `Secure`, backup limits, admin-lockout guard, no-JS fallbacks), then P2/P3 as capacity allows.

Each item above is independently actionable and can be verified with targeted tests before merging.


