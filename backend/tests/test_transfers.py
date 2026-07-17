"""Transfer matcher unit tests + API integration."""

import pytest

from app import transfers
from tests.conftest import CSRF
from tests.test_api_accounts import make_account
from tests.test_api_imports import upload


@pytest.fixture
def two_accounts(db):
    a = db.execute("INSERT INTO accounts (name, type) VALUES ('Checking', 'checking')")
    b = db.execute("INSERT INTO accounts (name, type) VALUES ('Citi Card', 'credit')")
    return a, b


def tx(db, account, amount, posted="2026-06-10", payee="X", memo=""):
    return db.execute(
        "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
        "payee_raw, payee_norm, memo) VALUES (?, 'h', ?, ?, ?, ?, ?)",
        (account, posted, amount, payee, payee, memo))


def test_auto_link_confident_pair(db, two_accounts):
    a, b = two_accounts
    t_out = tx(db, a, -35000, payee="ONLINE PAYMENT TO CITI")
    t_in = tx(db, b, 35000, posted="2026-06-11", payee="PAYMENT THANK YOU")
    stats = transfers.find_and_link(db, [t_out, t_in])
    assert stats["linked"] == 1
    rows = db.query("SELECT transfer_id, category_id FROM transactions")
    assert all(r["transfer_id"] for r in rows)
    assert all(r["category_id"] is None for r in rows)

    listed = transfers.list_transfers(db)
    assert listed[0]["from_account"] == "Checking"
    assert listed[0]["to_account"] == "Citi Card"
    assert listed[0]["amount_cents"] == 35000


def test_ambiguous_pair_becomes_candidate(db, two_accounts):
    a, b = two_accounts
    # small round amount, no transfer-ish text → below auto-link threshold
    t_out = tx(db, a, -10000, payee="MISC DEBIT")
    t_in = tx(db, b, 10000, posted="2026-06-13", payee="DEPOSIT RECEIVED")
    stats = transfers.find_and_link(db, [t_out])
    assert stats == {"linked": 0, "candidates": 1}
    c = db.query_one("SELECT * FROM transfer_candidates")
    assert c["status"] == "pending" and c["tx_a"] == t_out and c["tx_b"] == t_in


def test_outside_window_not_matched(db, two_accounts):
    a, b = two_accounts
    t_out = tx(db, a, -35000, payee="TRANSFER OUT")
    tx(db, b, 35000, posted="2026-06-20", payee="TRANSFER IN")  # 10 days later
    stats = transfers.find_and_link(db, [t_out])
    assert stats == {"linked": 0, "candidates": 0}


def test_same_account_not_matched(db, two_accounts):
    a, _ = two_accounts
    t1 = tx(db, a, -35000, payee="TRANSFER")
    tx(db, a, 35000, payee="TRANSFER")
    assert transfers.find_and_link(db, [t1]) == {"linked": 0, "candidates": 0}


def test_competing_counterparts_demoted_to_candidate(db, two_accounts):
    a, b = two_accounts
    t_out = tx(db, a, -35000, payee="ONLINE PAYMENT")
    tx(db, b, 35000, posted="2026-06-10", payee="PAYMENT THANK YOU")
    tx(db, b, 35000, posted="2026-06-11", payee="PAYMENT THANK YOU")
    stats = transfers.find_and_link(db, [t_out])
    assert stats["linked"] == 0 and stats["candidates"] == 1


def test_link_validation(db, two_accounts):
    a, b = two_accounts
    t_out = tx(db, a, -100)
    t_in = tx(db, b, 100)
    t_other = tx(db, b, 999)
    with pytest.raises(ValueError):
        transfers.link(db, t_out, t_other)  # amounts differ
    with pytest.raises(ValueError):
        transfers.link(db, t_in, t_out)  # wrong direction
    tid = transfers.link(db, t_out, t_in)
    with pytest.raises(ValueError):
        transfers.link(db, t_out, t_in)  # already linked

    transfers.unlink(db, tid)
    assert db.query_one("SELECT count(*) c FROM transfers")["c"] == 0
    assert db.query_one(
        "SELECT count(*) c FROM transactions WHERE transfer_id IS NOT NULL")["c"] == 0


def test_linking_resolves_competing_candidates(db, two_accounts):
    a, b = two_accounts
    t_out = tx(db, a, -10000, payee="MISC")
    t_in1 = tx(db, b, 10000, payee="MISC")
    transfers._add_candidate(db, t_out, t_in1, 0.5)
    transfers.link(db, t_out, t_in1)
    assert db.query_one("SELECT status FROM transfer_candidates")["status"] == "accepted"


# -- API ---------------------------------------------------------------------

CC_PAYOFF_CSV = (b'"06/25/2026","-350.00","*","","ONLINE PAYMENT TO CITI CARD"\n')
CC_RECEIVE_CSV = b"Status,Date,Description,Debit,Credit\n" \
                 b"Cleared,06/25/2026,PAYMENT THANK YOU,,350.00\n"


def test_credit_card_payoff_links_via_import(authed, appstate):
    checking = make_account(authed)
    card = make_account(authed, name="Citi Card", type="credit")
    upload(authed, checking["id"], "payoff.csv", content=CC_PAYOFF_CSV)
    upload(authed, card["id"], "citi.csv", content=CC_RECEIVE_CSV)

    r = authed.get("/api/transfers")
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["from_account"] == "Joint Checking"
    assert listed[0]["to_account"] == "Citi Card"
    assert listed[0]["amount_cents"] == 35000
    # neither side is in the categorization queue
    assert authed.get("/api/queue").json() == []


def test_candidate_accept_flow(authed, appstate):
    checking = make_account(authed)
    card = make_account(authed, name="Card", type="credit")
    upload(authed, checking["id"], "a.csv",
           content=b'"06/25/2026","-100.00","*","","MISC DEBIT"\n')
    upload(authed, card["id"], "b.csv",
           content=b"Status,Date,Description,Debit,Credit\n"
                   b"Cleared,06/27/2026,DEPOSIT,,100.00\n")

    cands = authed.get("/api/transfers/candidates").json()
    assert len(cands) == 1
    r = authed.post(f"/api/transfers/candidates/{cands[0]['id']}/accept", headers=CSRF)
    assert r.status_code == 200
    assert len(authed.get("/api/transfers").json()) == 1
    assert authed.get("/api/transfers/candidates").json() == []


def test_candidate_reject_and_unlink(authed):
    checking = make_account(authed)
    card = make_account(authed, name="Card", type="credit")
    upload(authed, checking["id"], "a.csv",
           content=b'"06/25/2026","-100.00","*","","MISC DEBIT"\n')
    upload(authed, card["id"], "b.csv",
           content=b"Status,Date,Description,Debit,Credit\n"
                   b"Cleared,06/27/2026,DEPOSIT,,100.00\n")
    cand = authed.get("/api/transfers/candidates").json()[0]
    r = authed.post(f"/api/transfers/candidates/{cand['id']}/reject", headers=CSRF)
    assert r.status_code == 200
    assert authed.get("/api/transfers/candidates").json() == []

    # manual link then unlink
    r = authed.post("/api/transfers/link", headers=CSRF,
                    json={"from_tx": cand["tx_a"], "to_tx": cand["tx_b"]})
    tid = r.json()["transfer_id"]
    r = authed.delete(f"/api/transfers/{tid}", headers=CSRF)
    assert r.status_code == 200
    assert authed.get("/api/transfers").json() == []
