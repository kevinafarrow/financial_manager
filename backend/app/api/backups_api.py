from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from .. import audit
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("")
def list_backups(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.backups.list_backups()


@router.post("/snapshot")
def snapshot(state=Depends(require_unlocked), user=Depends(require_user)):
    path = state.backups.snapshot()
    audit.record(state.db, user["id"], "snapshot", "backup", None,
                 {"filename": path.name})
    return {"filename": path.name}


@router.get("/export")
def export(state=Depends(require_unlocked), user=Depends(require_user)):
    """Download a fresh encrypted snapshot (useless without the passphrase)."""
    path = state.backups.snapshot()
    audit.record(state.db, user["id"], "export", "backup", None,
                 {"filename": path.name})
    return FileResponse(path, media_type="application/octet-stream",
                        filename=path.name)
