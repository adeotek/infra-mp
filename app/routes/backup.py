"""Backup and restore routes (admin-only)."""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from app.auth.dependencies import require_admin
from app.config import get_settings
from app.flash import redirect_with_flash
from app.models.user import User
from app.templates import render

router = APIRouter()

DB_FILENAME = "infra-mp.db"


def _db_path(request: Request) -> Path:
    """Absolute path to the live SQLite file, derived from the engine URL."""
    return Path(request.app.state.engine.url.database)


@router.get("/settings/backup")
def backup_page(request: Request, user: User = Depends(require_admin)):
    return render(request, "backup.html")


@router.get("/settings/backup/download")
def download_backup(request: Request, user: User = Depends(require_admin)):
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


@router.post("/settings/backup/restore")
async def restore_backup(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    user: User = Depends(require_admin),
):
    """Replace the live database with the uploaded backup archive."""
    content = await file.read()
    db_bytes = _extract_database(content)
    if db_bytes is None:
        return redirect_with_flash(
            "/settings/backup",
            "Invalid archive: no SQLite database file found inside.",
            category="error",
            request=request,
        )
    if not _is_valid_database(db_bytes):
        return redirect_with_flash(
            "/settings/backup",
            "The uploaded file is not a valid InfraMP SQLite database.",
            category="error",
            request=request,
        )

    _swap_database(request, db_bytes)

    response = redirect_with_flash(
        "/login", "Database restored. Please log in again.", request=request
    )
    response.delete_cookie(get_settings().session_cookie_name)
    return response


def _extract_database(content: bytes) -> bytes | None:
    """Return the bytes of the first ``*.db`` entry in a zip archive, or None."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".db")]
            if not names:
                return None
            return zf.read(names[0])
    except (zipfile.BadZipFile, KeyError):
        return None


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
