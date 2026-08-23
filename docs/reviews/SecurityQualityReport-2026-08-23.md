# InfraMP Security & Quality Review Report

**Project:** `infra-mp` (reviewed at v0.7.0; findings fixed in v0.7.1)  
**Review Date:** 2026-08-23  
**Scope:** Full codebase review including security, correctness, performance, and code quality.

---

## Executive Summary

InfraMP is a well-architected self-hosted infrastructure manager with solid fundamentals: RBAC, CSRF, rate limiting, encrypted session tokens, and a dynamic schema engine stored as JSON. Recent reviews (Claude, OpenCode, 2026-08-22) documented many improvements that are now implemented in v0.7.0. This review confirms those fixes and surfaces **five critical bugs** that block safe deployment or cause data corruption:

| Priority | Issue | Impact | Status |
|---|---|---|---|
| 🔴 P0 | Delete user who authored records → 500 | Integrity failure; operator must manually clean up DB | **Fixed in v0.7.1** |
| 🔴 P0 | Decimal "NaN"/"Infinity" accepted → 500 on view sort | View crash; operator data loss risk if uncaught | **Fixed in v0.7.1** |
| 🟠 P1 | Reference attribute target repointed while records exist | Silent foreign-key semantic breakage | **Fixed in v0.7.1** |
| 🟠 P1 | Dashboard table widget bound to view renders empty headers | UX bug; data visible but column titles blank | **Fixed in v0.7.1** |
| 🟡 P2 | Open redirect via backslash in `?next=` bypasses `_safe_next` | Minor attack surface; mitigated by same-site cookies | **Fixed in v0.7.1** |

All other findings from prior reviews (CSRF, MCP auth, backup caps, cookie Secure flag, etc.) are implemented and verified. Below is the full analysis.

---

## Confirmed Bugs (Action Required)

### 1. 🔴 P0 — User deletion crashes when user authored records (`IntegrityError`)

**Location:** `app/services/user_service.py::delete_user`, models (FK on `Record.created_by`, `Record.updated_by`).

**Evidence:**
```bash
$ .venv/bin/python /tmp/repro2c.py
record created_by author id 2 admin id 1
delete_user RAISES: IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
[SQL: DELETE FROM users WHERE users.id = ?]
[parameters: (2,)]
(Background on the error at https://sqlalche.me/e/20/gkpz)
```

**Root cause:** The `User` FKs in `Record` are defined without `ondelete`:
```python
# app/models/record.py
created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
```
When a user who authored records is deleted, SQLite rejects the delete.

**Impact:** Admin cannot remove stale accounts; DB state becomes inconsistent. Requires manual intervention (either `SET NULL` on FK or pre-delete validation).

**Fix options:**
- **Preferred:** Add `ondelete="SET NULL"` to both FKs so record attribution persists cleanly.
- Alternative: Reject deletion of users with records and show a clear message.

> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.1 — both FKs now carry `ondelete="SET NULL"`; migration `9d1c4e7f2b3a` rebuilds the records table (verified upgrade/downgrade/upgrade on a scratch DB, FK actions confirmed via `PRAGMA foreign_key_list`). Regression test: `test_delete_user_with_authored_records_nulls_attribution`.

---

### 2. 🔴 P0 — Decimal "NaN"/"Infinity" accepted at write → 500 on sorted view

**Locations:** `app/services/validation.py::coerce_value` accepts `Decimal("NaN")`; `app/services/view_service.py::sort_value` compares NaN values; `/views/{id}` route.

**Evidence:**
```python
from decimal import Decimal

Decimal("NaN") < Decimal("1")  # Raises InvalidOperation
(1, Decimal("NaN"), "") < (1, Decimal("1"), "")  # Raises InvalidOperation
```

Repro output:
```
decimal.InvalidOperation: [<class 'decimal.InvalidOperation'>]
at app/services/view_service.py:443 in _apply_sort
  with_value.sort(key=lambda r: sort_value(r.data[column.attr.slug]), reverse=reverse)
GET /views/1 -> 500
```

**Root cause:** `coerce_value(DataType.DECIMAL)` calls `str(Decimal(str(value)))` which accepts `"NaN"`, `"Infinity"`, `"-Infinity"`. These serialize fine into JSON but cannot be compared for sorting.

**Impact:** Any DECIMAL attribute accepting invalid numeric strings causes view pages (and any server-side sorting) to crash. Potential data corruption if operators allow raw input.

**Fix:** Validate numeric string format in `coerce_value`:
```python
if data_type == DataType.DECIMAL:
    s = str(value).strip()
    if not re.fullmatch(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", s):
        raise ValidationError(f"Expected a number, got {value!r}")
    return str(Decimal(s))
```
And consider adding a form-level pattern/step validator in templates.

> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.1 — `coerce_value` now rejects non-finite decimals via `Decimal.is_finite()` (same effect as the regex, without restricting valid finite notation); `sort_value` additionally treats any non-finite value as text so legacy rows that predate the fix (or plain text attributes holding "NaN") can never crash a sorted view again. Regression tests: `test_decimal_rejects_non_finite`, `test_sort_value_treats_non_finite_as_text`.

---

### 3. 🟠 P1 — Reference target entity can be repointed while records exist

**Location:** `app/services/schema_service.py::update_attribute` refuses structural changes *only* when records exist, but it permits changing `reference_entity_id` silently.

**Evidence:**
```python
# repro5.py output
record with site=1 created
update_attribute: ACCEPTED — reference target silently repointed to Rack while records exist
```

**Root cause:** The guard at lines 195–210 checks for data presence, but only blocks:
- Data type changes
- Unique/key toggles
- Slug changes

It does **not** check for reference target/capacity changes. Existing records continue to store old entity IDs, creating mismatches between attribute config and actual referents.

**Impact:** Silent data corruption. The web UI displays broken references (#n vs real records), filters/sorts misbehave, CSV upserts fail.

**Fix:** Extend `update_attribute` to also reject `reference_entity_id` and `cardinality` changes when `entity_has_records(db, attribute.entity_id)` is true. Display a locked field in the form: `<select disabled>User has records; change target by adding a new attribute and migrating data.`

> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.1 — `update_attribute` rejects `reference_entity_id` and `cardinality` changes while the entity has records (clear `SchemaError` message, form re-renders with the error — same UX as the existing data-type/unique/key locks). Changes remain allowed on empty entities. Regression tests: `test_reference_target_change_rejected_with_records`, `test_reference_target_change_allowed_without_records`.

---

### 4. 🟠 P1 — Dashboard table widgets bound to views render empty column headers

**Location:** `app/templates/dashboard.html` lines 27, 30 use `c.name` on `columns`, but columns are `ViewColumn` objects (no `name` attribute).

**Evidence:**
```bash
widget table headers: ['']
widget table cells: ['srv1']
```
The header row exists but contains no text because `c.name` evaluates to an empty string for `ViewColumn`.

**Root cause:** Template inconsistency. In other places (views/detail_body.html) the correct `.label` is used.

**Fix:** Change `dashboard.html` line 27 from:
```jinja
<th for c in w.data.columns>{{ c.name }}</th>
```
to:
```jinja
{% for c in w.data.columns %}{% set label = c.name if hasattr(c, 'name') else c.label %}...{% endfor %}
```
Or better: ensure `_render_table_widget` returns columns as dicts with `.name`, not `ViewColumn` instances. Simpler fix: pass `.label` consistently by converting to dict or exposing `.name` fallback in the template.

> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.1 — `_render_table_widget` now normalises view columns to `{"name": label, "slug": key}` dicts (entity-only widgets get the same shape), and view-bound widgets render via `build_view_rows`, so related-entity columns also show their values like the view's detail page. Regression test: `test_table_widget_with_view_renders_column_headers_and_cells`.

---

### 5. 🟡 P2 — Open redirect bypass via backslash in `?next=`

**Location:** `app/routes/auth.py::_safe_next`:
```python
def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"
```

**Evidence:**
```python
_safe_next("/\\evil.com")  # Returns '/\\evil.com' (unchanged)
```
The browser resolves `/evil.com` and `/\evil.com` identically (path segment after the first slash). While SameSite=Lax cookies prevent most attacks, it remains a minor open redirect vector.

**Impact:** Low. Cookies are HTTP-only + SameSite; no credential leakage. Could be used for phishing redirects.

**Mitigation:** Already partial via `SameSite=Lax`, HTTP-only, strict HSTS. Recommended hardening:
- Replace startswith check with regex `re.match(r'^/[/?\-_a-zA-Z0-9]*$', value)`.
- Or validate against allowed paths whitelist.

> **Status (hermes-agent, 2026-08-23):** Fixed in v0.7.1 — `_safe_next` now rejects `/\host` (backslash) alongside `//host` (browsers normalise backslashes in URL paths, so both are protocol-relative). Regression tests: `test_safe_next_rejects_open_redirect_payloads`, `test_safe_next_accepts_relative_paths`.

---

## Correctness & Code Quality (Minor Issues)

### A. Sort key uses `.name` on columns where only `.label` exists

**Locations:** `app/templates/dashboard.html:27`, `app/templates/views/detail_body.html:70` uses `.label` correctly; dashboard mismatch found above. Also potential similar issues in entity list pages. No runtime crash, just blank headers.

**Fix:** Audit all Jinja2 `{% for c in columns %}` loops for consistent accessor; enforce `.label` on non-entity attributes.

### B. Missing `autoescape` guards for `{{ }}` outputs

No occurrences of `|safe` or autoescape overrides were found. All user content flows through filter pipelines (`datetime_display`, `icon_class`) and rendered safely. No XSS vectors identified.

### C. Form fields missing HTML5 validation hints

Decimal inputs don't use `pattern` or `min`/`max` constraints. Not required by design (canonical form enforced server-side), but improves UX. Consider adding:
```html
<input type="number" step="any" ... title="Enter a valid number">
```

### D. Test coverage completeness

Current count: **~461 tests** across 31 files (pytest `collect-only` confirms). Coverage is strong for business logic (validation, services) and weaker for edge cases around errors and internationalization. Consider:
- Tests for NaN/infinity rejection
- Tests for reference-target lock-out
- Tests for FK violation prevention on user deletion

---

## Security Review

All major security areas addressed per prior reviews:

| Area | Status | Notes |
|---|---|---|
| **CSRF** | ✅ Fixed in v0.7.0 | Pure ASGI middleware; exempt `/mcp`, `/login`, `/static`. Forms submit `X-CSRF-Token` header. |
| **Rate limiting** | ✅ Fixed | Per-(IP, username) window/cooldown; dummy hash on unknown usernames. |
| **Password storage** | ✅ Good | Argon2id; 8–128 char enforced client + server side. |
| **Session management** | ✅ Good | Hashed tokens in DB; expires; no plaintext exposure. |
| **API tokens** | ✅ Fixed in v0.7.0 | Expiry support; revoked-deletion workflow; hashed storage. |
| **MCP auth** | ✅ Fixed | Uses same API token verifier; capability enforcement mirrors web. |
| **Backup upload limits** | ✅ Fixed | Max 50MB upload + 250MB decompressed DB; zip-bomb protection via entry header check. |
| **Cookie Secure flag** | ✅ Fixed | Empty env fixed; `cookie_secure_resolved` property handles default detection. |
| **Response headers** | ✅ Fixed | CSP (unsafe-inline needed for inline scripts), X-Frame-Options, X-Content-Type-Options, Referrer-Policy; opt-in HSTS. |
| **TrustedHostMiddleware** | ✅ Added | Configurable allowlist; defaults to `*` for backward compatibility. |
| **Non-root container** | ✅ Fixed | uid 10001; documented volume chown for upgrades. |

**No SQL injection**, **no command injection**, **no SSRF**. Input validated via Pydantic schemas and custom validators. Parameterized queries throughout SQLAlchemy usage.

---

## Performance Review

- **DB indexing:** `(entity_id, deleted_at)` on records covers hot path. Session expiry index on `expires_at`. Attribute uniqueness keyed by slug.
- **Query sharing:** Dashboard shares entity loads across widgets; plain count uses SQL COUNT(*). Record validation preloads existing records once per import.
- **Async offloading:** Heavy sync work (CSV import, record CRUD, backup) runs in threadpool. MCP SDK wraps tool handlers with `anyio.to_thread.run_sync`.

**Recommendation:** Monitor `busy_timeout=5000` pragmas under high concurrent MCP load; consider bumping to 10s if contention observed.

---

## UI/UX Findings

- **Confirm dialogs:** Properly implemented with `data-confirm` interceptors. Escape closes; focus returns.
- **Busy indicators:** Global progress hairline on HTMX requests; toast on async failures.
- **Mobile drawer:** Off-canvas menu with backdrop; keyboard navigation included.
- **Accessibility:** Basic ARIA roles present; some tables lack `aria-sort` updates during drag-reorder (client-side only). Column headers use `role="button"` with Enter/Space toggle — good.
- **Color scheme:** Teal/edit/import, blue/create/export, red/delete — consistent.
- **Empty states:** Present for all collection lists; helpful prompts for first-time users.

---

## Dependencies & Supply Chain

- Python 3.12+ required (CI runs on 3.14).
- Core deps: FastAPI, SQLAlchemy 2.x, Jinja2, Argon2-cffi, alembic, mcp≥2.0.
- Dev: pytest, httpx, ruff.
- CI weekly dependabot PRs on pip and GitHub Actions.

**Note:** `mcp>=2.0,<3` pinned — compatible with current SDK features (`anyio.to_thread` for sync tool functions).

---

## Recommendations

### Immediate (P0/P1)
1. ~~Add `ondelete="SET NULL"` to `Record.created_by` and `Record.updated_by` FKs.~~ ✅ Done in v0.7.1 (migration `9d1c4e7f2b3a`).
2. ~~Reject NaN/Infinity decimals.~~ ✅ Done in v0.7.1 (`Decimal.is_finite()` check in `coerce_value`).
3. ~~Lock reference target/capacity changes on entities with records.~~ ✅ Done in v0.7.1 (guard in `update_attribute`).
4. ~~Fix dashboard column labels.~~ ✅ Done in v0.7.1 (normalised dict columns + `build_view_rows`).

### Short-term (P2)
5. ~~Harden open redirect check in `_safe_next`.~~ ✅ Done in v0.7.1 (rejects `/\` alongside `//`).
6. ~~Improve sort robustness.~~ ✅ Done in v0.7.1 (`sort_value` treats non-finite values as text).
7. **Add migration to drop existing users with orphaned FK violations** (future cleanup).

### Long-term
8. **Consider database engine flexibility** — currently hardcoded SQLite; pg would help scaling.
9. **Add API versioning** — future breaking changes safer via `/api/v2/`.
10. **Audit third-party JS vendored libs** — FontAwesome, HTMX versions tracked in repo.

---

## Conclusion

InfraMP v0.7.0 is a mature, production-ready application with excellent architecture and recent security hardening. All five findings in this review were fixed in v0.7.1 (see status annotations above); the full suite (469 tests) passes and the fixes are covered by regression tests.

All remaining findings are minor UI polish or UX enhancements that do not impact security or data integrity.

---

**Generated by:** Hermes Agent  
**Methodology:** Manual code audit + targeted reproductions  
**Date:** 2026-08-23
