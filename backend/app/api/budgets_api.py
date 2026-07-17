from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit, budgets
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/budgets", tags=["budgets"])
goals_router = APIRouter(prefix="/api/savings-goals", tags=["budgets"])

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class LineBody(BaseModel):
    category_id: int
    amount_cents: int


class LinesBody(BaseModel):
    lines: list[LineBody]


class GoalBody(BaseModel):
    name: str
    monthly_cents: int
    account_id: int | None = None


class GoalPatch(BaseModel):
    name: str | None = None
    monthly_cents: int | None = None
    account_id: int | None = None
    enabled: bool | None = None


def _check_month(month: str) -> None:
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month must be YYYY-MM")


@router.get("/{month}")
def get_budget(month: str, state=Depends(require_unlocked), user=Depends(require_user)):
    _check_month(month)
    p = budgets.progress(state.db, month)
    if p is None:
        raise HTTPException(404, "no budget for this month")
    return p


@router.post("/{month}/draft")
def draft(month: str, state=Depends(require_unlocked), user=Depends(require_user)):
    _check_month(month)
    try:
        budget_id = budgets.draft_budget(state.db, month)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit.record(state.db, user["id"], "draft", "budget", budget_id, {"month": month})
    state.data_changed()
    return budgets.progress(state.db, month)


@router.put("/{budget_id}/lines")
def set_lines(budget_id: int, body: LinesBody, state=Depends(require_unlocked),
              user=Depends(require_user)):
    b = state.db.query_one("SELECT * FROM budgets WHERE id = ?", (budget_id,))
    if b is None:
        raise HTTPException(404, "budget not found")
    if b["status"] == "approved":
        raise HTTPException(409, "approved budgets cannot be edited")
    for line in body.lines:
        if line.amount_cents < 0:
            raise HTTPException(400, "budget amounts must be >= 0")
        if not state.db.query_one(
                "SELECT id FROM categories WHERE id = ? AND kind = 'expense'",
                (line.category_id,)):
            raise HTTPException(400, f"invalid category {line.category_id}")
    with state.db.transaction() as conn:
        conn.execute("DELETE FROM budget_lines WHERE budget_id = ?", (budget_id,))
        for line in body.lines:
            conn.execute("INSERT INTO budget_lines (budget_id, category_id, amount_cents) "
                         "VALUES (?, ?, ?)", (budget_id, line.category_id, line.amount_cents))
    audit.record(state.db, user["id"], "edit_lines", "budget", budget_id)
    state.data_changed()
    return budgets.progress(state.db, b["month"])


@router.post("/{budget_id}/approve")
def approve(budget_id: int, state=Depends(require_unlocked), user=Depends(require_user)):
    try:
        budgets.approve(state.db, budget_id, user["id"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit.record(state.db, user["id"], "approve", "budget", budget_id)
    state.data_changed()
    b = state.db.query_one("SELECT month FROM budgets WHERE id = ?", (budget_id,))
    return budgets.progress(state.db, b["month"])


# -- savings goals -----------------------------------------------------------

@goals_router.get("")
def list_goals(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT g.*, a.name AS account_name FROM savings_goals g "
        "LEFT JOIN accounts a ON a.id = g.account_id ORDER BY g.name")


@goals_router.post("")
def create_goal(body: GoalBody, state=Depends(require_unlocked),
                user=Depends(require_user)):
    if body.monthly_cents <= 0:
        raise HTTPException(400, "monthly_cents must be positive")
    goal_id = state.db.execute(
        "INSERT INTO savings_goals (name, monthly_cents, account_id) VALUES (?, ?, ?)",
        (body.name, body.monthly_cents, body.account_id))
    audit.record(state.db, user["id"], "create", "savings_goal", goal_id)
    state.data_changed()
    return state.db.query_one("SELECT * FROM savings_goals WHERE id = ?", (goal_id,))


@goals_router.patch("/{goal_id}")
def update_goal(goal_id: int, body: GoalPatch, state=Depends(require_unlocked),
                user=Depends(require_user)):
    if not state.db.query_one("SELECT id FROM savings_goals WHERE id = ?", (goal_id,)):
        raise HTTPException(404, "goal not found")
    updates = body.model_dump(exclude_none=True)
    if updates:
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        sets = ", ".join(f"{k} = ?" for k in updates)
        state.db.execute(f"UPDATE savings_goals SET {sets} WHERE id = ?",
                         (*updates.values(), goal_id))
        audit.record(state.db, user["id"], "update", "savings_goal", goal_id, updates)
        state.data_changed()
    return state.db.query_one("SELECT * FROM savings_goals WHERE id = ?", (goal_id,))
