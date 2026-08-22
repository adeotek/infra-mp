# InfraMP — Code Review

**Date:** 2026-08-22
**Scope:** Full repository at `main` (1a4d423, v0.6.0) — security, performance, UI/UX, and general code quality.

## How to read this

Findings are grouped by category and ranked High → Low within each group. Each
finding includes the file/line it applies to and a concrete suggested fix. A
"Note" prefix marks something worth being aware of but not necessarily worth
acting on. The **Already solid** section at the end calls out patterns worth
*keeping* — don't regress these in future changes.

---

## Security

### 🟠 Medium — No brute-force protection on `/login`
`app/routes/auth.py:35-63` has no rate limiting, lockout, or backoff. Any
client can attempt unlimited username/password combinations. Argon2id makes
offline cracking expensive, but online guessing against common/weak passwords
is unthrottled. Given the admin account is often internet-facing behind a
reverse proxy (README explicitly supports this), this is worth closing.

**Fix:** add a lightweight per-IP/per-username attempt counter (in-memory is
fine for a single-process SQLite app) with exponential backoff or a hard cap
+ cooldown after N failures.

### 🟠 Medium — `INFRAMP_SECRET_KEY` is documented but unused
`app/config.py:22` declares `secret_key`, and it's called out as **required**
in `README.md:88`, `.env.example:10-12`, `docker-compose.yml:15`, and
`SECURITY.md:44` ("Secret used to sign session cookies... **Must** be a long
random string"). It is never referenced anywhere else in the codebase —
sessions (`app/auth/sessions.py`) actually use `secrets.token_urlsafe(32)`
opaque tokens, hashed with SHA-256 and looked up server-side. That's a fine
(arguably better) design, but it means the operator-facing docs are actively
misleading: someone who "does the right thing" and sets a strong secret key
gets zero additional protection from it, and may believe they're covered by
a control that doesn't exist.

**Fix:** either remove `secret_key` entirely (and the docs referencing it),
or give it a real purpose — e.g., an HMAC pepper mixed into the token hash
so a raw DB leak plus a guessed token still isn't enough without the key.
Given the current design already stores only a token hash, removing the dead
config is the simpler, more honest fix.

### 🟡 Low — No security response headers
No CSP, `X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors`,
`Referrer-Policy`, or HSTS anywhere in `app/main.py`. For an admin panel that
manages infrastructure inventory and issues API tokens, clickjacking and
MIME-sniffing protections are cheap, high-value additions.

**Fix:** add a small middleware in `create_app()` that sets
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: same-origin`, and a baseline CSP (`default-src 'self'`,
adjusted for the vendored `htmx.min.js`/FontAwesome served from `/static`).
HSTS should be conditional/documented since TLS is expected to terminate at
a reverse proxy, not in-app.

### 🟡 Low — No CSRF token; relying solely on `SameSite=Lax`
State-changing routes are POST-only and cookies are set with
`samesite="lax"` (`app/routes/auth.py:60`), which blocks the classic
auto-submitting cross-site form attack in modern browsers. There's no
explicit CSRF token, though, so this is a single layer of defense rather
than defense-in-depth — and it silently stops protecting if a future route
ever accepts state-changing GETs or if `SameSite` handling regresses (e.g.
via a reverse-proxy quirk or an older browser).
`app/routes/auth.py:23-27` (`_safe_next`) does correctly guard against open
redirects, which is good.

**Fix:** low priority given the existing mitigation, but a standard
double-submit CSRF token on forms would remove the single-point-of-failure
nature of relying on `SameSite` alone.

### 🟡 Low — No "last active admin" guard on user *edit*, only on *delete*
`app/services/user_service.py:87-99` (`delete_user`) correctly refuses to
delete the last active admin. `update_user` (`user_service.py:58-84`) has no
equivalent check: an admin can demote their own role to Viewer or toggle
`is_active` off for themselves (or the only other admin) via
`POST /users/{id}/edit`, with no recovery path short of direct DB access.

**Fix:** apply the same "≥1 other active admin" check in `update_user` when
`role` is changing away from `ADMIN` or `is_active` is being set to `False`
for a user who is currently the last active admin.

### 🟡 Low — Unbounded upload size on backup restore
`app/routes/records.py`'s CSV import enforces `MAX_UPLOAD_BYTES` (5 MB,
`app/services/csv_service.py:24`) before reading the file. The backup
restore endpoint (`app/routes/backup.py:79`, `content = await file.read()`)
has no equivalent cap — an admin session (own mistake, or a compromised
admin cookie) can upload an arbitrarily large file that's read fully into
memory, then unzipped fully into memory again (`_extract_database`,
`backup.py:105-114`). Low severity since it's admin-gated, but easy to
bound.

**Fix:** cap the upload size the same way CSV import does, and consider
streaming the zip extraction instead of loading the whole archive into
memory.

### ⚪ Info — Container runs as root
`Dockerfile` has no `USER` directive, so the app runs as root inside the
container. Standard hardening for a single-purpose container is to add a
non-root user and `chown` `/data` (or rely on the volume's ownership) —
low urgency for a single-container homelab deployment, but a common ask in
container security scans.

---

## Performance

### 🟠 Medium — Every list/filter/sort/search operation loads the full entity into memory
`list_records()` (`app/services/record_service.py:38-45`) always fetches
**every** non-deleted record for an entity; filtering, sorting, quick-search,
and CSV export/import (`view_service.py`, `csv_service.py`) all operate on
that in-memory list rather than pushing predicates into SQL. The MCP
`list_records` tool (`app/mcp_server.py:219-263`) does the same — it loads
the whole entity, filters/sorts/searches in Python, and only paginates the
already-fully-materialized result.

This is a deliberate consequence of the schema-as-data design (`Record.data`
is an opaque JSON blob, so there's no column to push a `WHERE` into without
`json_extract`), and it's genuinely fine at "homelab" scale (hundreds to a
few thousand records per entity). It will show up as real latency and memory
pressure well before the "small private data centre" scale the README
targets, though — e.g. an entity with tens of thousands of asset records.

**Fix (if/when it matters):** either (a) switch to SQLite `json_extract` for
the common filter/sort operators so the DB does the work, or (b) accept the
current design and just document the practical row-count ceiling. Not worth
addressing preemptively — flagging so it's a conscious tradeoff rather than
a surprise.

### 🟡 Low — Uniqueness/key validation re-scans the whole entity on every write
`validate_record_data()` (`app/services/record_service.py:100-124`) loads
every existing record for the entity on **every single** create/update when
the entity has any unique or key attribute, to check duplicates in Python
(`_duplicate_value`, line 166). This is O(n) per write and compounds with
the point above — an entity with 5,000 records does a 5,000-row load for
every single record creation.

**Fix:** for key/unique attributes, this could become a targeted SQL
existence check once attribute values are queryable (same `json_extract`
path as above). Lower priority than the read-side issue since writes are
typically far less frequent than reads/list views.

### 🟡 Low — Dashboard widgets re-run redundant queries per widget
`app/routes/dashboard.py:46-69` — each table/count widget independently
calls `list_records`, `resolve_reference_titles`, and (for view-bound
widgets) `list_entities(db)` again inside the per-widget loop
(`dashboard.py:52-54`, `:68`). With N view-bound widgets on one dashboard,
`list_entities(db)` runs N extra times fetching the same data. `render()`
(`app/templates.py:73-81`) then does its own `list_entities`/`list_views`
call again for the sidebar on the same request.

**Fix:** hoist `list_entities(db)` out of the per-widget loop in
`dashboard()` and pass it in once; low-risk, mechanical change.

### ⚪ Info — Indexing is actually in good shape
Checked `app/models/record.py` and `app/models/session.py`: `Record.entity_id`
and `Record.deleted_at` are indexed, `AuthSession.token_hash` is
unique+indexed, `expires_at` is indexed. The hot-path `WHERE` clauses in
`list_records`/`resolve_user` are covered. No action needed — noting this so
it's not mistaken for an oversight given the in-memory filtering above.

---

## UI / UX

Overall this is in good shape — v0.5.0 already shipped a dedicated
mobile-responsive pass, `app.js` consistently uses `textContent` (not
`innerHTML`) for any user-controlled data so there's no obvious client-side
XSS surface, and there's a real no-JS fallback path (`is_fragment`/
`base_template` in `app/templates.py:46-68`). A few smaller items:

### 🟡 Low — Client-side quick-search/sort don't scale with the in-memory record model
`app.js`'s quick-search (`app.js:668-718`) and sortable-table (`app.js:315-421`)
features filter/sort the full rendered `<table>` in the DOM. Since
`records_index` (`app/routes/records.py:48-71`) renders **every** record for
an entity with no server-side pagination, a large entity means a large
unpaginated HTML table shipped to the browser before any client-side
filter/sort can help. This mirrors the backend performance point above —
worth solving together if/when it's addressed (server-side pagination would
fix both at once).

### ⚪ Info — No loading/pending state on HTMX-driven actions
Modal-opening and form-submit interactions (`app.js:203-236`) rely on HTMX's
default swap behavior with no visible pending indicator (`htmx-indicator` or
similar) wired up in the templates checked. On a slower connection this can
read as an unresponsive click. Minor polish item, not a defect.

### ⚪ Info — Copy-to-clipboard has a solid fallback, worth keeping as a pattern
`app.js:615-645` (API token copy button) correctly uses the async Clipboard
API with a `document.execCommand('copy')` fallback for browsers/contexts
where it's unavailable (e.g. non-HTTPS LAN access, which is a realistic
deployment mode for this app). Good defensive pattern — flagging as a
positive, not an issue.

---

## Other / code quality

### ⚪ Info — Backup restore accepts any SQLite file with a `users` table
`app/routes/backup.py:117-136` validates the uploaded archive with
`PRAGMA quick_check` and a check for a `users` table before swapping it in.
That's a reasonable sanity check, but it's not verifying schema
compatibility with the current Alembic revision — restoring a backup from a
much older/newer InfraMP version could silently succeed and then hit runtime
errors on first schema-dependent query. Given this is an explicit,
admin-only, documented feature (not a bug), this is just a note: consider
also checking `alembic_version` matches (or is upgradable) before swapping.

### ⚪ Info — Good architectural discipline overall
`app/auth/dependencies.py`'s single `require_capability()` chokepoint is
used consistently across every route file checked (`entities.py`,
`records.py`, `users.py`, `views.py`, `api_tokens.py`, `dashboard.py`) — no
ad-hoc role checks found scattered in routes, matching what `AGENTS.md`
documents as the intended pattern. The MCP server (`app/mcp_server.py`)
independently re-derives the same capability checks via `_require()`, which
is correct but means the RBAC rule set now has two enforcement call sites
(HTTP routes and MCP tools) that must be kept in sync by hand — worth a
one-line comment cross-referencing the two if either file is touched again.

---

## Already solid (keep doing this)

- **Argon2id** for password hashing, **SHA-256-hashed, server-side-verified
  opaque tokens** for both sessions and API tokens (`app/auth/sessions.py`,
  `app/services/api_token_service.py`) — the actual DB never holds anything
  usable if leaked.
- **Every DB query goes through SQLAlchemy's expression API** — no raw SQL,
  no f-string interpolation into queries, anywhere checked. No SQL injection
  surface found.
- **CSV export already guards against formula injection**
  (`app/services/csv_service.py:100-107`, `_safe_cell`) — cells starting
  with `=`, `+`, `@`, or a non-numeric `-` are quoted. This is a detail
  teams frequently miss; it's handled correctly here.
- **Open-redirect protection** on the post-login redirect
  (`app/routes/auth.py:23-27`, `_safe_next`).
- **User-facing error messages avoid enumeration** — login failure returns
  one generic message regardless of whether the username exists.
  Jinja2's default autoescaping is relied on with no `|safe` usage found
  anywhere in `app/templates/`, so there's no obvious server-rendered XSS
  vector either.
- **Test coverage is genuinely broad** — 29 test files covering permissions,
  auth, MCP tools, CSV import/export, schema/view services, and even UI
  details like mobile layout and button colors. This is well above what's
  typical for a project this size.

---

## Suggested priority order

1. Add login rate limiting/backoff (Medium, security).
2. Resolve the `INFRAMP_SECRET_KEY` doc/reality mismatch — remove or wire in
   (Medium, security — mostly a trust/documentation issue but cheap to fix).
3. Add the last-active-admin guard to `update_user` (Low, security —
   prevents an easy self-lockout).
4. Add baseline security response headers (Low, security — cheap, broad
   payoff).
5. Cap backup-restore upload size (Low, security/robustness).
6. Everything else (CSRF token, in-memory-filtering scalability, dashboard
   N+1, container non-root user) is reasonable to defer — none are urgent
   given the app's stated homelab/self-hosted target and existing
   mitigations.
