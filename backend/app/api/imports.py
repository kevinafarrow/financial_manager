from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import audit
from ..importers.csv_importer import CsvParseError
from ..importers.ofx import OfxParseError
from ..importers.service import ImportError_, import_file
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/upload")
async def upload(account_id: int = Form(...), file: UploadFile = File(...),
                 mapping: str | None = Form(None),
                 state=Depends(require_unlocked), user=Depends(require_user)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large")
    mapping_dict = None
    if mapping:
        try:
            mapping_dict = json.loads(mapping)
        except json.JSONDecodeError:
            raise HTTPException(400, "mapping must be valid JSON")
    try:
        result = import_file(state, account_id, file.filename or "upload",
                             data, mapping_dict, user["id"])
    except (ImportError_, CsvParseError, OfxParseError) as e:
        raise HTTPException(400, str(e))
    audit.record(state.db, user["id"], "import", "import", result["import_id"],
                 {"filename": file.filename, "imported": result["imported"],
                  "duplicates": result["duplicates"]})
    return result


@router.get("")
def history(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT i.*, a.name AS account_name FROM imports i "
        "JOIN accounts a ON a.id = i.account_id "
        "ORDER BY i.imported_at DESC LIMIT 100")


@router.get("/staleness")
def staleness(state=Depends(require_unlocked), user=Depends(require_user)):
    """Per-account data freshness, driving UI badges and the nag job."""
    rows = state.db.query(
        "SELECT a.id, a.name, a.staleness_days, a.kind, "
        "  max(coalesce((SELECT max(t.posted_at) FROM transactions t WHERE t.account_id = a.id), ''), "
        "      coalesce((SELECT max(b.as_of) FROM balance_snapshots b WHERE b.account_id = a.id), '')) AS freshest, "
        "  cast(julianday('now') - julianday(nullif(max(coalesce((SELECT max(t.posted_at) FROM transactions t WHERE t.account_id = a.id), ''), "
        "      coalesce((SELECT max(b.as_of) FROM balance_snapshots b WHERE b.account_id = a.id), '')), '')) AS integer) AS age_days "
        "FROM accounts a WHERE a.archived = 0 GROUP BY a.id ORDER BY a.name")
    for r in rows:
        r["stale"] = r["age_days"] is None or r["age_days"] > r["staleness_days"]
    return rows
