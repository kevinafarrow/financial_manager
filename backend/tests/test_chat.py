"""Chat service: tool execution against the DB and the tool-use loop (fake client)."""

import json
from types import SimpleNamespace

import pytest

from app.chat import ChatService, NoApiKey
from tests.conftest import CSRF
from tests.test_api_accounts import make_account
from tests.test_api_imports import upload


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, input_, id_="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id_)


class FakeClient:
    """Yields scripted responses; records every request payload."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


@pytest.fixture
def world(db):
    acct = db.execute("INSERT INTO accounts (name, type) VALUES ('Joint Checking', 'checking')")
    cat = db.execute("INSERT INTO categories (name, kind) VALUES ('Eating Out', 'expense')")
    for d, amt in [("2026-03-05", -4500), ("2026-03-12", -6200)]:
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
            "payee_raw, payee_norm, memo, category_id, cat_source) "
            "VALUES (?, 'h', ?, ?, 'THAI TOM', 'THAI TOM', '', ?, 'user')",
            (acct, d, amt, cat))
    db.execute("INSERT INTO balance_snapshots (account_id, as_of, balance_cents) "
               "VALUES (?, '2026-03-15', 500000)", (acct,))
    return {"acct": acct, "cat": cat}


def make_service(db, client=None):
    return ChatService(db, lambda: client, "claude-opus-4-8")


# -- tool execution ----------------------------------------------------------

def test_tool_spending_by_category(db, world):
    svc = make_service(db)
    out = svc.execute_tool("spending_by_category", {"month": "2026-03"})
    assert out == {"Eating Out": 10700}


def test_tool_search_with_category_name(db, world):
    svc = make_service(db)
    out = svc.execute_tool("search_transactions", {"category": "Eating Out"})
    assert out["total"] == 2
    assert out["transactions"][0]["payee_raw"] == "THAI TOM"


def test_tool_account_balances(db, world):
    svc = make_service(db)
    out = svc.execute_tool("account_balances", {})
    assert out[0]["account"] == "Joint Checking"
    assert out[0]["balance_cents"] == 500000


def test_tool_fuzzy_account_resolution(db, world):
    svc = make_service(db)
    out = svc.execute_tool("search_transactions", {"account": "joint"})
    assert out["total"] == 2


def test_tool_unknown(db):
    assert "error" in make_service(db).execute_tool("nope", {})


# -- the loop ----------------------------------------------------------------

def make_thread(db, user_id=None):
    if user_id is None:
        user_id = db.execute(
            "INSERT INTO users (username, display_name, password_hash) "
            "VALUES ('u', 'U', 'x')")
    return db.execute("INSERT INTO chat_threads (user_id) VALUES (?)", (user_id,))


def test_send_runs_tool_loop_and_persists(db, world):
    client = FakeClient([
        SimpleNamespace(stop_reason="tool_use", content=[
            text_block("Let me check."),
            tool_block("spending_by_category", {"month": "2026-03"}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[
            text_block("You spent $107.00 eating out in March."),
        ]),
    ])
    svc = make_service(db, client)
    tid = make_thread(db)
    result = svc.send(tid, "How much did we spend eating out in March?")
    assert result["reply"] == "You spent $107.00 eating out in March."
    assert result["tool_rounds"] == 1

    # the tool result was fed back to the model
    second_request = client.requests[1]
    tool_result_msg = second_request["messages"][-1]
    assert tool_result_msg["role"] == "user"
    payload = json.loads(tool_result_msg["content"][0]["content"])
    assert payload == {"Eating Out": 10700}

    # persisted as plain text turns; thread got titled
    msgs = db.query("SELECT * FROM chat_messages WHERE thread_id = ?", (tid,))
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert db.query_one("SELECT title FROM chat_threads WHERE id = ?",
                        (tid,))["title"].startswith("How much")


def test_tool_error_reported_not_raised(db, world):
    client = FakeClient([
        SimpleNamespace(stop_reason="tool_use", content=[
            tool_block("search_transactions", {"q": "(bad", "regex": True}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[text_block("Bad regex.")]),
    ])
    svc = make_service(db, client)
    tid = make_thread(db)
    svc.send(tid, "search ( for me")
    result_block = client.requests[1]["messages"][-1]["content"][0]
    assert result_block["is_error"] is True


def test_refusal_handled(db, world):
    client = FakeClient([SimpleNamespace(stop_reason="refusal", content=[])])
    svc = make_service(db, client)
    tid = make_thread(db)
    assert "can't help" in svc.send(tid, "hi")["reply"]


def test_no_api_key_raises(db):
    svc = make_service(db, client=None)
    with pytest.raises(NoApiKey):
        svc.send(make_thread(db), "hello")


def test_history_replayed_on_next_turn(db, world):
    client = FakeClient([
        SimpleNamespace(stop_reason="end_turn", content=[text_block("Hi Kevin!")]),
        SimpleNamespace(stop_reason="end_turn", content=[text_block("Sure.")]),
    ])
    svc = make_service(db, client)
    tid = make_thread(db)
    svc.send(tid, "Hello")
    svc.send(tid, "Thanks")
    msgs = client.requests[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"] == "Hi Kevin!"


# -- API ---------------------------------------------------------------------

def test_chat_api_flow(authed, appstate):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")

    r = authed.post("/api/chat/threads", headers=CSRF)
    tid = r.json()["id"]

    # no API key configured → clean 400
    r = authed.post(f"/api/chat/threads/{tid}/messages", headers=CSRF,
                    json={"text": "hi"})
    assert r.status_code == 400

    # swap in a fake client and try again
    appstate.chat.client_factory = lambda: FakeClient([
        SimpleNamespace(stop_reason="end_turn", content=[text_block("Hello!")]),
    ])
    r = authed.post(f"/api/chat/threads/{tid}/messages", headers=CSRF,
                    json={"text": "hi"})
    assert r.json()["reply"] == "Hello!"

    thread = authed.get(f"/api/chat/threads/{tid}").json()
    assert [m["text"] for m in thread["messages"]] == ["hi", "Hello!"]
    assert authed.get("/api/chat/threads").json()[0]["message_count"] == 2

    r = authed.delete(f"/api/chat/threads/{tid}", headers=CSRF)
    assert r.status_code == 200
    assert authed.get(f"/api/chat/threads/{tid}").status_code == 404


def test_thread_ownership_enforced(authed, appstate, client):
    other = appstate.db.execute(
        "INSERT INTO users (username, display_name, password_hash) "
        "VALUES ('mary', 'Mary', 'x')")
    foreign = appstate.db.execute(
        "INSERT INTO chat_threads (user_id) VALUES (?)", (other,))
    assert authed.get(f"/api/chat/threads/{foreign}").status_code == 404
