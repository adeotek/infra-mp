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
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `w.span` → `w.width`; regression test invokes the tool via tools/call (tests/test_review_fixes.py).
- **Domain:** quality · **Severity:** Critical bug
- **Location:** `app/mcp_server.py:665`
- **Issue:** `"span": w.span` — `DashboardWidget` has no `span` attribute; the model defines `width` (`app/models/dashboard.py:33`). Every invocation raises `AttributeError`.
- **Why undetected:** No test actually calls this tool (only the tool list is asserted).
- **Fix:** Change to `"width": w.width`; add a test that invokes the tool via `tools/call`.

### 2. No CSRF protection on any state-changing endpoint
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — session-bound HMAC CSRF middleware; every form embeds a `csrf_token` hidden input (plain-HTML and no-JS paths) and HTMX/fetch requests send `X-CSRF-Token` via htmx:configRequest. `/mcp` and `/login` exempt.
- **Domain:** security · **Severity:** High
- **Location:** all POST routes (`app/routes/*.py`), `app/main.py` (no middleware), `app/static/app.js:288-294` (reorder `fetch` calls)
- **Issue:** Zero CSRF tokens, no Origin/Referer validation. Only defense is `SameSite=Lax` on the session cookie (`app/routes/auth.py:56-62`), which fails against same-site subdomain attacks and older browsers.
- **Impact:** A malicious site can drive a logged-in admin's browser to create users, revoke tokens, delete records, or restore a hostile DB backup. The project's own `SECURITY.md` lists CSRF as in scope.
- **Fix:** Per-session CSRF token injected into every form (plain + HTMX) and validated on all POSTs, or an Origin-validating middleware. HTMX forms can carry the token via `hx-headers`.

---

## P1 — Fix soon

### Security

**3. No rate limiting / lockout on login** (`app/routes/auth.py:35-63`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — in-memory per-IP + per-username backoff (default 5 failures / 10 min window / 10 min cooldown, configurable).
Argon2id gives only weak inherent throttling; the well-known `admin` username makes dictionary attacks practical. Fix: per-IP + per-username rate limiting (e.g. slowapi or a DB-backed sliding window), optional lockout.

**4. Session cookie lacks `Secure` flag** (`app/routes/auth.py:56-62`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — cookie is now `secure=True` when `INFRAMP_BASE_URL` is https, with `INFRAMP_COOKIE_SECURE` to force either way.
`httponly=True, samesite="lax"` but no `secure=True`, and no setting to enable it. Session token travels over plain HTTP behind TLS proxies. Fix: add `INFRAMP_COOKIE_SECURE` (default on when `base_url` is HTTPS).

**5. No server-side password strength on user create/update** (`app/services/user_service.py:32-84`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `user_service` enforces 8..128 chars on create, admin update, and own password change; the dead pydantic schemas were removed (#43).
`create_user`/`update_user` hash any string, including 1 character; the pydantic `UserCreate`/`UserUpdate` schemas with `min_length=8` are never used by routes. Only `change_password` enforces length. Fix: enforce minimum length in the service, or wire the schemas into the routes.

**6. Backup restore: unbounded upload + zip-bomb exposure** (`app/routes/backup.py:65-114`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — upload cap + decompressed-size cap read from the zip entry header before extraction (see ClaudeReview item).
`content = await file.read()` with no size cap, then `zf.read(names[0])` fully decompresses the first `.db` entry into memory. CSV import enforces `MAX_UPLOAD_BYTES`; restore does not. Fix: upload size cap + uncompressed-size cap (streamed reads), reject before materializing.

**7. `update_user` can lock out the last active admin** (`app/services/user_service.py:58-84`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — demotion/deactivation of the last active admin is rejected with a clear error.
`delete_user` guards against removing the last active admin, but `update_user` happily deactivates or demotes them. Fix: apply the same last-active-admin count check when the update would deactivate/demote one.

**8. Login timing leak for unknown usernames** (`app/routes/auth.py:43-51`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — unknown/inactive usernames verify a dummy Argon2 hash so the response time matches real attempts.
`verify_password` short-circuits when the user doesn't exist, so responses are measurably faster — username enumeration. Fix: run a dummy Argon2 verify when the user is missing/inactive.

**9. TrustedHost middleware absent** (`app/main.py`, Low) — app accepts any `Host` header. Fix: `TrustedHostMiddleware` with a configurable allowlist.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `TrustedHostMiddleware` wired to a configurable allowlist (`INFRAMP_ALLOWED_HOSTS`); defaults to `*` for backwards compatibility, documented for proxy setups.

**10. API tokens never expire** (`app/models/api_token.py:19-29`, `app/services/api_token_service.py:22-37`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — optional `expires_at` on tokens (migration 7f7c07383cf9), enforced in `verify_token`, with a lifetime select (never/30/90/365 days) and an Expires column in both token UIs.
Tokens valid until manual revocation; a leaked token grants access forever. Fix: optional `expires_at` column, enforced in `verify_token`.

### Performance

**11. `async def` handlers run blocking SQLAlchemy work on the event loop** (Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — pure-DB handlers converted to sync `def` (api tokens, users); heavy sync work in async handlers (CSV import, backup, record create/update) moved to the threadpool via `run_in_threadpool`.
Locations: `app/routes/api_tokens.py:62,99,125`, `backup.py:66`, `records.py:107,168,214`, `users.py:54,103`, `views.py:217,265,379`, plus `entities.py`/`dashboard.py`. The CSV import — potentially minutes of sync DB work — runs directly on the loop that also serves the MCP endpoint and static files. Fix: convert these handlers to sync `def` (FastAPI runs them in the threadpool; SQLAlchemy here is fully sync). Keep `async def` only where async IO is awaited.

**12. No pagination anywhere** (High)
> **Status (hermes-agent, 2026-08-23):** Deferred as a conscious tradeoff: both reviews agree the in-memory design is sized for homelab scale; README now documents the ceiling and the json_extract/pagination upgrade path. All other P1 perf items were fixed.
`record_service.list_records` (`app/services/record_service.py:38-45`) loads every record of an entity; record lists, view detail bodies, and dashboard table widgets render the full set; CSV export loads everything. Page size grows linearly with data. Fix: server-side pagination (LIMIT/OFFSET or keyset) with prev/next controls, plus a "show more" HTMX endpoint; stream CSV export.

**13. Same entity's records loaded 3-4x per request in views** (`app/services/view_service.py`, High)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — per-request cache dict shared across `apply_config`/`build_view_rows`/title resolution; referenced entities' records load once per request.
Referenced entities' records are re-queried per reference column while rendering a view. Fix: cache per-entity record lists in a request-scoped dict during render.

**14. Dashboard widgets each independently reload the same entities** (`app/routes/dashboard.py:46-110`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — hoisted `list_entities` + shared record cache per dashboard request; count widgets use SQL `COUNT(*)`.
Count widgets load the full record set just to `len()` it. Fix: load each entity's records once per dashboard request and share across widgets; use SQL `COUNT(*)` for count widgets.

**15. CSV import is O(n²) on large files** (`app/services/csv_service.py`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — entity records loaded once per import and reused for key/uniqueness validation (was a full reload per row). json_extract indexes deferred with #12.
Per-row full-entity reloads for key/uniqueness checks. Fix: load entity records once before the loop; push key/uniqueness checks into SQL with expression indexes on `json_extract(record.data, '$.<slug>')` for key attributes.

**16. No SQLite `busy_timeout` / `synchronous` pragmas** (`app/db.py`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `busy_timeout=5000`, `synchronous=NORMAL` on connect; composite `(entity_id, deleted_at)` index added (model + migration).
WAL is on and `entity_id`/`deleted_at` are indexed, but concurrent writers (MCP + web) can hit `database is locked`. Fix: `PRAGMA busy_timeout=5000` and `synchronous=NORMAL` on connect; add a composite index on `(entity_id, deleted_at)`.

**17. `verify_token` commits on every MCP request** (`app/services/api_token_service.py:40-58`, Info)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `last_used_at` written at most once per 60s; no commit at all on the throttled path.
`last_used_at` update + commit per authenticated tool call = write transaction per read request. Fix: throttle the update (only if older than ~1 minute).

### UI / UX

**18. Modal form validation errors are invisible (400 responses never swapped)** (High)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — global `htmx:beforeSwap` handler re-enables swapping of 4xx responses into fragment targets; 5xx surfaces a toast instead.
htmx 2.0's default `responseHandling` discards 4xx/5xx responses; all modal forms POST via `hx-post` targeting `#modal-body` and the routes return 400 with the error fragment (`app/routes/entities.py:112-121`, `users.py:71-85`, `auth.py:91-100`). Result: submit appears to do nothing. Fix: global `htmx:beforeSwap` handler in `app.js` that allows swapping 4xx into `#modal-body`.

**19. HTMX error responses inject the full page into the fragment target** (High)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `error.html` now extends `base_template` (fragments stay fragments); 401 returns `HX-Redirect` instead of a 303 the client would inline.
`app/templates/error.html:1` hardcodes `{% extends "base.html" %}`, ignoring the `base_template="fragment.html"` that `render()` sets for HTMX requests (`app/templates.py:68`). 404/403 during an HTMX request swaps the entire `<html>` (sidebar, topbar, dialogs) into `#modal-body`/`#view-detail-body`; 401 returns a 303 that htmx follows, swapping the login page in-place. Fix: make `error.html` extend `base_template`; for 401 return `HX-Redirect` instead of 303.

**20. No-JS fallback broken in four places** (High — violates the project's own AGENTS.md rule)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — filter bar posts a real form (action/method, server-rendered op options, remove buttons as forms); drop zones are `<label for>` (native picker without JS); attribute-form conditional groups only hide under `html.js`; multi-ref source select carries the field name (JS resets it after Add).
- **Advanced filter bar** (`app/templates/views/detail_body.html:3-44`): form has no `action`/`method`; operator select and remove buttons are HTMX-only.
- **File uploads** (`app/templates/records/import.html:6-12`, `backup.html:21-27`): inputs are `display:none`, only the JS drop-zone click opens them.
- **Enum/reference attribute config** (`app/templates/attributes/form.html:27-48`): `.conditional { display:none }` until JS flips it — impossible to configure those types without JS.
- **Multi-reference fields** (`app/templates/records/form.html:56-78`): source select has no `name`; submitted values are JS-built hidden inputs — value silently dropped without JS.
Fix: native fallbacks (visible `<input>` + `<label for>`, `action`/`method` on forms, server-rendered conditional visibility), JS as enhancement only.

**21. No loading feedback on any HTMX request** (Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — global busy indicator via htmx beforeRequest/afterRequest + CSS progress hairline.
Zero `hx-indicator` usage; modals open instantly empty and filter bars swap silently. Fix: add `hx-indicator` + spinner styles, or a global `htmx:beforeRequest`/`afterRequest` busy class in `app.js`.

**22. Record forms lack per-field error feedback and `required`** (`app/templates/records/form.html:32-92`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `validate_record_data` returns slug→message errors, the form renders per-field messages with `aria-invalid`, and required inputs carry `required`.
Required attributes show `*` but inputs have no `required`, `aria-invalid`, or `aria-describedby`; server errors are one joined string at the top. Fix: return slug → error dict from the service and render per-field messages.

**23. Dark-theme button text fails WCAG AA contrast** (`app/static/style.css:29-51,410-414`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — dedicated button-fill tokens: dark-theme `#2563eb` (5.2:1), `#0f766e` (5.5:1), `#dc2626` (5.9:1) against white text.
`--primary: #3b82f6` (~3.7:1 vs white), `--teal: #14b8a6` (~2.5:1), `--danger: #ef4444` (~3.8:1) all below 4.5:1 at 0.9rem. Fix: darken dark-theme button fills (e.g. `#2563eb`/`#0f766e`/`#b91c1c`).

**24. 500 errors return raw JSON to browser users** (`app/main.py:95-120`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — unhandled exceptions log the traceback and render the styled error page (fragment-aware).
Only `StarletteHTTPException` gets the styled `error.html`; unhandled exceptions fall through to FastAPI's `{"detail":"Internal Server Error"}`. Fix: add a 500 handler rendering `error.html` and logging the traceback.

**25. Filter-bar validation reloads the whole page in HTMX mode** (`app/routes/views.py:287-329`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — validation failures re-render the `detail_body` fragment with an inline `filter_error` message.
"Enter a filter value first." returns `HX-Redirect` → full navigation for a message that belongs next to the input. Fix: return the `detail_body` fragment with an inline error for HTMX requests.

---

## P2 — Should fix

**26. Unvalidated `int()` conversions → 500s on crafted form input** (`app/routes/dashboard.py:83-87`, `entities.py:54`, `views.py:223`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — entity/view id parsing raises HTTPException(400); attribute reference target guarded; widget `_parse_ids` guarded.
`int(raw.get("entity_id"))` raises uncaught `TypeError`/`ValueError` → 500 instead of 400. Fix: try/except and raise `HTTPException(400)`, matching the pattern already used in the reorder endpoints.

**27. `INFRAMP_SECRET_KEY` is dead config with misleading docs** (`app/config.py:22`, `.env.example`, `README.md`, `SECURITY.md`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — now signs CSRF tokens; all docs updated to describe its real purpose.
Documented as "secret used to sign session cookies" but never read — sessions are server-side hashed tokens. Operators get false assurance and an insecure-looking default (`change-me-in-production`). Fix: actually use it (e.g. sign flash messages / derive a CSRF key) or remove it everywhere.

**28. `update_attribute` allows schema changes that invalidate existing records** (`app/services/schema_service.py:191-222`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — with records present, `data_type`/`is_unique`/`is_key` changes are rejected (display-only edits still allowed).
With records present, only slug/`is_active` are locked; `data_type`, `is_unique`, `is_key` still change, leaving stored values un-revalidated (e.g. INTEGER→BOOLEAN leaves `8` in JSON). Fix: reject those changes when `has_records`, or re-validate/re-coerce all existing values.

**29. DECIMAL values stored as `float` lose precision** (`app/services/validation.py:38-42`, Medium)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — canonical storage is `str(Decimal(...))`; display, filters, uniqueness, keys, and sorting compare via `Decimal` so legacy float rows keep working.
`float(Decimal(...))` round-trips through JSON with representation noise (`0.30000000000000004`). Fix: store canonical `str(Decimal(...))` and format for display.

**30. DATETIME coercion accepts tz-aware strings** (`app/services/validation.py:67-73`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — aware input is normalized to naive (wall-clock) UTC per the app convention.
Breaks the naive-UTC convention documented in AGENTS.md. Fix: strip tzinfo after parsing (or reject aware inputs).

**31. `is_unique` never detects duplicates on many-reference attributes** (`app/services/record_service.py:166-178`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — many-reference (list) values are excluded from uniqueness comparison (set-of-ids uniqueness is meaningless).
Compares a list against an int — always False. Fix: membership check for list values or skip uniqueness for many-refs.

**32. `/healthz` doesn't check the database** (`app/main.py:122-124`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — runs `SELECT 1`; returns 503 with a logged traceback on failure.
Docker HEALTHCHECK reports healthy on a corrupt DB. Fix: `SELECT 1` and return 503 on failure.

**33. Backup restore doesn't verify alembic version** (`app/routes/backup.py:117-136`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — post-restore the DB is migrated to head (`alembic upgrade head`, or `stamp head` for pre-Alembic backups).
`_is_valid_database` checks `quick_check` + `users` table only; a stale-version backup can leave the DB at an old revision. Fix: check `alembic_version` against head, or run `alembic upgrade head` after restore.

**34. CSV import swallows programming errors** (`app/services/csv_service.py:254-256`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `logger.exception` before the rollback; the user-facing message is unchanged.
Bare `except Exception` → rollback + generic message, no logging. Fix: `logger.exception(...)` before rollback.

**35. `_render_table_widget` dereferences `widget.view.config` without a None check** (`app/routes/dashboard.py:51-54`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — null-checked (`widget.view is not None`); orphaned view ids render as entity-only widgets (test added).
Orphaned `view_id` (manual DB edit) 500s the dashboard. Fix: `if widget.view is not None` guard.

**36. `_apply_sort` can `TypeError` on mixed-type column values** (`app/services/view_service.py:436`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — type-tagged `sort_value` keys (bool < number < text; numeric strings compare numerically).
`_sortable` normalizes bool/list but not int-vs-str mixes from legacy data. Fix: type-tagged sort key or `str(...).lower()` fallback.

**37. User menu `aria-expanded` stale; `role="menu"` without keyboard nav** (`app/templates/base.html:139-149`, `app/static/app.js:146-160`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `aria-expanded` synced on every open/close; ArrowUp/Down/Home/End keyboard navigation.
Fix: sync `aria-expanded` in the click handler; implement arrow-key nav or drop the `menu` role.

**38. Sortable table headers are mouse-only** (`app/static/app.js:380-407`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — headers are `tabindex=0` with Enter/Space toggling, `aria-sort` kept in sync.
Fix: `tabindex="0"` + Enter/Space handling; keep `aria-sort` in sync.

**39. Escape key deliberately blocked in modals** (`app/static/app.js:217-220`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — the cancel preventDefault is removed; Escape closes the dialog natively.
Fix: remove the `cancel` preventDefault (or only suppress while the form is dirty).

**40. MCP docstring lists nonexistent data type "number"** (`app/mcp_server.py:465-471`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — docstring now lists `integer, decimal`.
Fix: docstring should say `integer, decimal`.

**41. Expired sessions only purged at login** (`app/auth/sessions.py:40-50`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `resolve_user` deletes the expired row opportunistically.
Fix: opportunistically delete the expired row in `resolve_user`.

**42. `require_admin` bypasses the capability model** (`app/auth/dependencies.py:45-48`, used in `app/routes/backup.py:34,39,66`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — new `MANAGE_BACKUP` capability (admin-only) used via `require_capability`; `require_admin` removed from the codebase.
AGENTS.md mandates a single enforcement point. Fix: add a `MANAGE_BACKUP` capability and use `require_capability`.

**43. `UserCreate`/`UserUpdate` schemas are dead code** (`app/schemas/user.py:10-22`, Low)
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — schemas deleted; validation lives in `user_service` (see #5) with service-level tests.
Fix: use them in routes (free validation) or delete.

---

## P3 — Nice to have

**44. Drag-and-drop reordering has no keyboard/no-JS alternative** (`app/static/app.js:241-298`, `app/templates/entities/detail.html:27-42`, `dashboard/config.html:50-59`) — add up/down buttons posting to the same reorder endpoint.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — ▲/▼ buttons in the handle column post to the same reorder endpoints.

**45. Reorder failure reloads the page** (`app/static/app.js:288-295`) — revert DOM order and show a toast instead of `window.location.reload()`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — on failure the DOM order is restored and a toast is shown.

**46. Unlabeled inputs: token name and filter value** (`app/templates/api_tokens.html:35`, `my_tokens.html:34`, `views/detail_body.html:14`) — add `<label>`/`aria-label`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — sr-only labels added for token name, expiry select, and filter value.

**47. Users table has no empty state** (`app/templates/users/list.html:8-33`) — mirror the other list templates' `.empty-state` blocks.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — empty-state block mirrors the other list templates.

**48. Dashboard table widgets with zero records render headers only** (`app/templates/dashboard.html:21-36`) — check `w.data.rows` and render "No records yet".
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — "No records yet." shown for empty table widgets.

**49. Flash messages persist in the URL, no dismiss or live-region semantics** (`app/templates.py:65-66`, `app/templates/base.html:158-160`) — add `role="status"/"alert"`, a dismiss button, and strip `?flash=` via `history.replaceState`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `role=status/alert`, dismiss button, and `history.replaceState` strips `?flash=` after display.

**50. `flash_type` query param injected into a class attribute** (`app/templates/base.html:158-160`) — map to a fixed `{success, error}` set in `templates.py`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — whitelisted to {success, error} in `templates.py`.

**51. Modal dialog has no accessible name** (`app/templates/base.html:169-174`) — `aria-labelledby` pointing at the content heading.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — modal points `aria-labelledby` at the fragment heading; confirm dialog labelled by its message.

**52. Mobile drawer lacks Escape/focus management and a dynamic label** (`app/static/app.js:649-666`, `app/templates/base.html:129-131`).
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — Escape closes, focus moves into/back to the toggle, label/aria-expanded update with state.

**53. `datetime_local` filter crashes on `datetime` objects** (`app/templates.py:15`) — handle both str and datetime.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — handles both `datetime` and str inputs.

**54. Seed admin race on first boot** (`app/auth/seed.py:22-24`) — catch `IntegrityError` / `ON CONFLICT DO NOTHING`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — unique-username `IntegrityError` from a concurrent seeder is caught and ignored.

**55. Admin seed prints the random password to stdout** (`app/auth/seed.py:26-40`) — document log exposure; optionally print a change-password hint instead.
> **Status (hermes-agent, 2026-08-23):** Addressed by documentation: kept (it is the only way to log in on first boot) but SECURITY.md + code comment now spell out the log-exposure risk.

**56. Docker container runs as root** (`Dockerfile`) — add non-root `USER` and make `/data` writable by it.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — non-root uid 10001; README documents the one-time volume chown for upgrades.

**57. `debug` setting never wired to FastAPI** (`app/config.py:28`, `app/main.py:60`) — pass `debug=settings.debug` or remove.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — `FastAPI(debug=settings.debug)`.

**58. `widget_type` not validated on create/update** (`app/routes/dashboard.py:144-167,187-209`) — validate against `{"table", "count"}`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — rejected with a flash error unless `table`/`count`.

**59. MCP `list_records` sorts numeric values as strings** (`app/mcp_server.py:254-258`) — sort by coerced typed value.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — sorts by the coerced typed value (test: [2, 10] orders numerically).

**60. MCP `_user_id` depends on SDK principal JSON layout** (`app/mcp_server.py:87-96`) — add a pinned-format comment + regression test.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — pinned-format comment + regression test cover the subject-at-index-2 layout.

**61. Route tests hardcode entity/attribute IDs** (`tests/test_records_routes.py:10-24` et al.) — resolve IDs from responses instead.
> **Status (hermes-agent, 2026-08-23):** Deferred: valid maintainability point, but refactoring every route test is high-churn with no user-visible benefit; noted for a future test-quality pass.

**62. Record data values have no length limits** (`app/services/validation.py:27-28`) — add per-attribute max-length validation and/or a global request body size cap.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — global 64k-character cap on text-ish values (text, textarea, enum) in `coerce_value`.

**63. `dist/` build artifacts in the working tree** — stale wheels next to 0.6.0 source; add to `make clean`.
> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.0 — stale wheels removed; `make clean` now deletes `dist/` and `build/`.

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


