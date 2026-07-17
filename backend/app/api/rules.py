from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit
from ..categorize.rules import validate_pattern
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleBody(BaseModel):
    field: str = "payee"
    pattern: str = Field(min_length=1)
    category_id: int
    priority: int = 100


class RulePatch(BaseModel):
    field: str | None = None
    pattern: str | None = None
    category_id: int | None = None
    priority: int | None = None
    enabled: bool | None = None


@router.get("")
def list_rules(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT r.*, c.name AS category_name FROM rules r "
        "JOIN categories c ON c.id = r.category_id "
        "ORDER BY r.priority, r.id")


@router.post("")
def create_rule(body: RuleBody, state=Depends(require_unlocked),
                user=Depends(require_user)):
    if body.field not in ("payee", "memo"):
        raise HTTPException(400, "field must be 'payee' or 'memo'")
    err = validate_pattern(body.pattern)
    if err:
        raise HTTPException(400, f"invalid regex: {err}")
    if not state.db.query_one("SELECT id FROM categories WHERE id = ?", (body.category_id,)):
        raise HTTPException(400, "unknown category")
    rule_id = state.db.execute(
        "INSERT INTO rules (field, pattern, category_id, priority) VALUES (?, ?, ?, ?)",
        (body.field, body.pattern, body.category_id, body.priority),
    )
    audit.record(state.db, user["id"], "create", "rule", rule_id, {"pattern": body.pattern})
    state.data_changed()
    return state.db.query_one("SELECT * FROM rules WHERE id = ?", (rule_id,))


@router.patch("/{rule_id}")
def update_rule(rule_id: int, body: RulePatch, state=Depends(require_unlocked),
                user=Depends(require_user)):
    if not state.db.query_one("SELECT id FROM rules WHERE id = ?", (rule_id,)):
        raise HTTPException(404, "rule not found")
    updates = body.model_dump(exclude_none=True)
    if "field" in updates and updates["field"] not in ("payee", "memo"):
        raise HTTPException(400, "invalid field")
    if "pattern" in updates:
        err = validate_pattern(updates["pattern"])
        if err:
            raise HTTPException(400, f"invalid regex: {err}")
    if updates:
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        sets = ", ".join(f"{k} = ?" for k in updates)
        state.db.execute(f"UPDATE rules SET {sets} WHERE id = ?",
                         (*updates.values(), rule_id))
        audit.record(state.db, user["id"], "update", "rule", rule_id, updates)
        state.data_changed()
    return state.db.query_one("SELECT * FROM rules WHERE id = ?", (rule_id,))


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, state=Depends(require_unlocked),
                user=Depends(require_user)):
    state.db.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    audit.record(state.db, user["id"], "delete", "rule", rule_id)
    state.data_changed()
    return {"ok": True}
