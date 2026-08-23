"""Backup and restore routes (admin-only)."""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import require_capability
from app.auth.permissions import MANAGE_BACKUP
from app.config import get_settings
from app.flash import redirect_with_flash
from app.models.user import User
from app.templates import render

logger = logging.getLogger(__name__)

router = APIRouter()

DB_FILENAME = "infra-mp.db"


def _db_path(request: Request) -> Path:
    """Absolute path to the live SQLite file, derived from the engine URL."""
    return Path(request.app.state.engine.url.database)


@router.get("/settings/backup")
def backup_page(request: Request, user: User = Depends(require_capability(MANAGE_BACKUP))):
    return render(request, "backup.html")


@router.get("/settings/backup/download")
def download_backup(request: Request, user: User = Depends(require_capability(MANAGE_BACKUP))):
    """Return a zip archive holding a consistent snapshot of the database."""
    db_path = _db_path(request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir) / DB_FILENAME
            source = sqlite3.connect(str(db_path))
            try:
                target = sqlite3.connect(str(snapshot))
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
            zf.write(snapshot, arcname=DB_FILENAME)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"infra-mp-backup-{stamp}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class BackupRestoreError(ValueError):
    """Raised when an uploaded archive cannot be used for a restore."""


@router.post("/settings/backup/restore")
async def restore_backup(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    user: User = Depends(require_capability(MANAGE_BACKUP)),
):
    """Replace the live database with the uploaded backup archive."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    if file is None or not (file.filename or "").strip():
        return redirect_with_flash(
            "/settings/backup",
            "Restore aborted: no file selected.",
            category="error",
            request=request,
        )
    # Bound the upload and the decompressed database (zip-bomb protection).
    content = await file.read(settings.max_backup_upload_bytes + 1)
    if len(content) > settings.max_backup_upload_bytes:
        return redirect_with_flash(
            "/settings/backup",
            (
                f"Restore aborted: the archive is larger than "
                f"{settings.max_backup_upload_bytes // (1024 * 1024)} MB."
            ),
            category="error",
            request=request,
        )
    try:
        db_bytes = await run_in_threadpool(_extract_database, content, settings.max_backup_db_bytes)
        if not await run_in_threadpool(_is_valid_database, db_bytes):
            raise BackupRestoreError("The uploaded file is not a valid InfraMP SQLite database.")
    except BackupRestoreError as exc:
        return redirect_with_flash("/settings/backup", str(exc), category="error", request=request)

    await run_in_threadpool(_swap_database, request, db_bytes)

    # A backup from an older version may be behind the current revision; bring
    # it up to head so stale schemas can't trip runtime errors later.
    try:
        await run_in_threadpool(_upgrade_database, request)
    except Exception:  # noqa: BLE001 - surfaced to the operator, DB already swapped
        logger.exception("Alembic upgrade after restore failed")
        return redirect_with_flash(
            "/settings/backup",
            "Restored, but migrating the database failed — check the logs.",
            category="error",
            request=request,
        )

    response = redirect_with_flash(
        "/login", "Database restored. Please log in again.", request=request
    )
    response.delete_cookie(settings.session_cookie_name)
    return response


def _extract_database(content: bytes, max_db_bytes: int) -> bytes:
    """Return the bytes of the first ``*.db`` entry in a zip archive.

    The entry's declared uncompressed size is checked before extraction so a
    zip bomb is rejected without ever being decompressed.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".db")]
            if not names:
                raise BackupRestoreError("Invalid archive: no SQLite database file found inside.")
            info = zf.getinfo(names[0])
            if info.file_size > max_db_bytes:
                raise BackupRestoreError(
                    "Restore aborted: the database inside the archive is too large."
                )
            return zf.read(info)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise BackupRestoreError("Invalid archive: not a readable zip file.") from exc


def _is_valid_database(db_bytes: bytes) -> bool:
    """True when the bytes form a SQLite DB containing the core ``users`` table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        probe = Path(tmpdir) / "probe.db"
        probe.write_bytes(db_bytes)
        try:
            conn = sqlite3.connect(str(probe))
            try:
                if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    return False
                return (
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                    ).fetchone()
                    is not None
                )
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False


def _swap_database(request: Request, db_bytes: bytes) -> None:
    """Atomically replace the live SQLite file and reset its connections."""
    engine = request.app.state.engine
    db_path = _db_path(request)

    # Close pooled connections so the file can be replaced; the engine reconnects
    # to the new file on the next request.
    engine.dispose()

    fd, tmp_name = tempfile.mkstemp(dir=db_path.parent, suffix=".db")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(db_bytes)
        os.replace(tmp_name, db_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    # Drop the old WAL/SHM sidecars so they can't clobber the restored file.
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)


def _upgrade_database(request: Request) -> None:
    """Bring the restored database to the current Alembic revision.

    Backups made before Alembic existed (or by test setups using
    ``create_all``) have no ``alembic_version`` table; those are stamped to
    head instead of migrated.
    """
    import sqlite3

    from alembic.config import Config as AlembicConfig

    from alembic import command

    cfg = AlembicConfig("alembic.ini")
    # Pin the URL through env.py's attribute hook so the app's engine (which
    # may differ from the global cached settings, e.g. in tests) is the source.
    cfg.attributes["inframp_url"] = str(request.app.state.engine.url)
    db_path = _db_path(request)
    conn = sqlite3.connect(str(db_path))
    try:
        has_version = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()
    if has_version:
        command.upgrade(cfg, "head")
    else:
        command.stamp(cfg, "head")
