from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryBody(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "expense"


class CategoryPatch(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    archived: bool | None = None


@router.get("")
def list_categories(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT c.*, "
        "(SELECT count(*) FROM transactions t WHERE t.category_id = c.id) AS tx_count "
        "FROM categories c ORDER BY c.archived, c.kind, c.sort_order, c.name")


@router.post("")
def create_category(body: CategoryBody, state=Depends(require_unlocked),
                    user=Depends(require_user)):
    if body.kind not in ("expense", "income"):
        raise HTTPException(400, "kind must be 'expense' or 'income'")
    try:
        cat_id = state.db.execute(
            "INSERT INTO categories (name, kind, sort_order) "
            "VALUES (?, ?, (SELECT coalesce(max(sort_order), 0) + 1 FROM categories))",
            (body.name.strip(), body.kind),
        )
    except Exception:
        raise HTTPException(409, "category name already exists")
    audit.record(state.db, user["id"], "create", "category", cat_id, {"name": body.name})
    state.data_changed()
    return state.db.query_one("SELECT * FROM categories WHERE id = ?", (cat_id,))


@router.patch("/{category_id}")
def update_category(category_id: int, body: CategoryPatch,
                    state=Depends(require_unlocked), user=Depends(require_user)):
    row = state.db.query_one("SELECT * FROM categories WHERE id = ?", (category_id,))
    if row is None:
        raise HTTPException(404, "category not found")
    if row["kind"] == "system":
        raise HTTPException(400, "system categories cannot be modified")
    updates = body.model_dump(exclude_none=True)
    if updates:
        if "archived" in updates:
            updates["archived"] = 1 if updates["archived"] else 0
        sets = ", ".join(f"{k} = ?" for k in updates)
        try:
            state.db.execute(f"UPDATE categories SET {sets} WHERE id = ?",
                             (*updates.values(), category_id))
        except Exception:
            raise HTTPException(409, "category name already exists")
        audit.record(state.db, user["id"], "update", "category", category_id, updates)
        state.data_changed()
    return state.db.query_one("SELECT * FROM categories WHERE id = ?", (category_id,))
