"""Search (text + regex + filters) and transaction edit/split API."""

import pytest

from app.search import BadPattern, search_transactions
from tests.conftest import CSRF
from tests.test_api_accounts import make_account
from tests.test_api_imports import upload
from tests.test_api_queue_rules import get_category_id


@pytest.fixture
def seeded(db):
    a = db.execute("INSERT INTO accounts (name, type) VALUES ('Chk', 'checking')")
    b = db.execute("INSERT INTO accounts (name, type) VALUES ('Card', 'credit')")
    cat = db.execute("INSERT INTO categories (name) VALUES ('Groceries')")
    rows = [
        (a, "2026-06-01", -8412, "WHOLEFDS #105", "WHOLEFDS", "weekly shop", cat),
        (a, "2026-06-05", -4500, "SHELL OIL 57444", "SHELL OIL", "", None),
        (b, "2026-06-07", -14287, "COSTCO WHSE #0110", "COSTCO WHSE", "", cat),
        (a, "2026-06-15", 250000, "ACME CORP PAYROLL", "ACME CORP PAYROLL", "", None),
    ]
    for acct, d, amt, praw, pnorm, memo, c in rows:
        db.execute(
            "INSERT INTO transactions (account_id, content_hash, posted_at, "
            "amount_cents, payee_raw, payee_norm, memo, category_id) "
            "VALUES (?, 'h', ?, ?, ?, ?, ?, ?)", (acct, d, amt, praw, pnorm, memo, c))
    return {"a": a, "b": b, "cat": cat}


def test_text_search_hits_payee_and_memo(db, seeded):
    assert search_transactions(db, q="wholefds")["total"] == 1
    assert search_transactions(db, q="weekly shop")["total"] == 1


def test_regex_search(db, seeded):
    # only COSTCO's #0110 has four digits after the hash; WHOLEFDS #105 has three
    assert search_transactions(db, q=r"#\d{4}", use_regex=True)["total"] == 1
    assert search_transactions(db, q=r"#\d{3}", use_regex=True)["total"] == 2


def test_regex_search_anchored(db, seeded):
    assert search_transactions(db, q=r"^SHELL", use_regex=True)["total"] == 1
    assert search_transactions(db, q=r"(WHOLE|COSTCO)", use_regex=True)["total"] == 2


def test_bad_regex_raises(db, seeded):
    with pytest.raises(BadPattern):
        search_transactions(db, q="(broken", use_regex=True)


def test_filters(db, seeded):
    assert search_transactions(db, account_id=seeded["b"])["total"] == 1
    assert search_transactions(db, category_id=seeded["cat"])["total"] == 2
    assert search_transactions(db, date_from="2026-06-06")["total"] == 2
    assert search_transactions(db, amount_min_cents=10000)["total"] == 2
    assert search_transactions(db, uncategorized=True)["total"] == 2


def test_pagination(db, seeded):
    r = search_transactions(db, limit=2, offset=0)
    assert r["total"] == 4 and len(r["transactions"]) == 2
    r2 = search_transactions(db, limit=2, offset=2)
    assert len(r2["transactions"]) == 2
    assert {t["id"] for t in r["transactions"]}.isdisjoint(
        {t["id"] for t in r2["transactions"]})


# -- API ---------------------------------------------------------------------

def test_transactions_api_search_and_regex(authed):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    r = authed.get("/api/transactions", params={"q": "SHELL"})
    assert r.json()["total"] == 1
    r = authed.get("/api/transactions", params={"q": r"PAYROLL$", "regex": "true"})
    assert r.json()["total"] == 1
    r = authed.get("/api/transactions", params={"q": "(bad", "regex": "true"})
    assert r.status_code == 400


def test_set_category_via_transactions_api(authed, appstate):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    tx = authed.get("/api/transactions", params={"q": "WHOLEFDS"}).json()["transactions"][0]
    groceries = get_category_id(authed, "Groceries")
    r = authed.post(f"/api/transactions/{tx['id']}/category", headers=CSRF,
                    json={"category_id": groceries})
    assert r.status_code == 200
    assert r.json()["category_id"] == groceries and r.json()["cat_source"] == "user"


def test_split_transaction(authed):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    tx = authed.get("/api/transactions", params={"q": "WHOLEFDS"}).json()["transactions"][0]
    groceries = get_category_id(authed, "Groceries")
    clothes = get_category_id(authed, "Clothes")

    # sums must match
    r = authed.put(f"/api/transactions/{tx['id']}/splits", headers=CSRF, json={
        "splits": [{"category_id": groceries, "amount_cents": -5000},
                   {"category_id": clothes, "amount_cents": -1000}]})
    assert r.status_code == 400

    r = authed.put(f"/api/transactions/{tx['id']}/splits", headers=CSRF, json={
        "splits": [{"category_id": groceries, "amount_cents": -6000},
                   {"category_id": clothes, "amount_cents": -2412}]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["splits"]) == 2
    assert {s["category_name"] for s in body["splits"]} == {"Groceries", "Clothes"}

    # category filter finds the split transaction
    r = authed.get("/api/transactions", params={"category_id": clothes})
    assert r.json()["total"] == 1

    r = authed.delete(f"/api/transactions/{tx['id']}/splits", headers=CSRF)
    assert r.status_code == 200
    r = authed.get("/api/transactions", params={"category_id": clothes})
    assert r.json()["total"] == 0


def test_transfer_leg_annotated_in_search(authed):
    checking = make_account(authed)
    card = make_account(authed, name="Citi Card", type="credit")
    upload(authed, checking["id"], "payoff.csv",
           content=b'"06/25/2026","-350.00","*","","ONLINE PAYMENT TO CITI CARD"\n')
    upload(authed, card["id"], "citi_in.csv",
           content=b"Status,Date,Description,Debit,Credit\n"
                   b"Cleared,06/25/2026,PAYMENT THANK YOU,,350.00\n")
    r = authed.get("/api/transactions").json()
    legs = [t for t in r["transactions"] if t["transfer_id"]]
    assert len(legs) == 2
    out_leg = next(t for t in legs if t["amount_cents"] < 0)
    assert out_leg["transfer_peer_account"] == "Citi Card"
    assert not out_leg["is_transfer_in"]
    # excluding transfers hides both legs
    r = authed.get("/api/transactions", params={"include_transfers": "false"}).json()
    assert all(not t["transfer_id"] for t in r["transactions"])


def test_categorizing_transfer_leg_rejected(authed):
    checking = make_account(authed)
    card = make_account(authed, name="Card", type="credit")
    upload(authed, checking["id"], "p.csv",
           content=b'"06/25/2026","-350.00","*","","ONLINE PAYMENT TO CARD"\n')
    upload(authed, card["id"], "c.csv",
           content=b"Status,Date,Description,Debit,Credit\n"
                   b"Cleared,06/25/2026,PAYMENT THANK YOU,,350.00\n")
    leg = next(t for t in authed.get("/api/transactions").json()["transactions"]
               if t["transfer_id"])
    groceries = get_category_id(authed, "Groceries")
    r = authed.post(f"/api/transactions/{leg['id']}/category", headers=CSRF,
                    json={"category_id": groceries})
    assert r.status_code == 400
