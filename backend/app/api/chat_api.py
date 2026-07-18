from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..chat import NoApiKey
from .deps import require_user, require_unlocked

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/threads")
def list_threads(state=Depends(require_unlocked), user=Depends(require_user)):
    return state.db.query(
        "SELECT t.*, (SELECT count(*) FROM chat_messages m WHERE m.thread_id = t.id) "
        "AS message_count FROM chat_threads t WHERE t.user_id = ? "
        "ORDER BY t.created_at DESC", (user["id"],))


@router.post("/threads")
def create_thread(state=Depends(require_unlocked), user=Depends(require_user)):
    thread_id = state.db.execute(
        "INSERT INTO chat_threads (user_id) VALUES (?)", (user["id"],))
    return state.db.query_one("SELECT * FROM chat_threads WHERE id = ?", (thread_id,))


def _own_thread(state, user, thread_id: int) -> dict:
    t = state.db.query_one(
        "SELECT * FROM chat_threads WHERE id = ? AND user_id = ?",
        (thread_id, user["id"]))
    if t is None:
        raise HTTPException(404, "thread not found")
    return t


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, state=Depends(require_unlocked),
               user=Depends(require_user)):
    t = _own_thread(state, user, thread_id)
    messages = state.db.query(
        "SELECT id, role, content_json, created_at FROM chat_messages "
        "WHERE thread_id = ? ORDER BY id", (thread_id,))
    for m in messages:
        m["text"] = json.loads(m.pop("content_json"))
    return {**t, "messages": messages}


@router.post("/threads/{thread_id}/messages")
def send_message(thread_id: int, body: MessageBody,
                 state=Depends(require_unlocked), user=Depends(require_user)):
    _own_thread(state, user, thread_id)
    try:
        result = state.chat.send(thread_id, body.text)
    except NoApiKey as e:
        raise HTTPException(400, str(e))
    state.data_changed()
    return result


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: int, state=Depends(require_unlocked),
                  user=Depends(require_user)):
    _own_thread(state, user, thread_id)
    state.db.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
    return {"ok": True}
