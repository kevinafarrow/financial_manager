"""Import service + API integration tests."""

from pathlib import Path

from tests.conftest import CSRF
from tests.test_api_accounts import make_account

FIXTURES = Path(__file__).parent / "fixtures"


def upload(authed, account_id, filename, content=None, mapping=None):
    data = content if content is not None else (FIXTURES / filename).read_bytes()
    form = {"account_id": str(account_id)}
    if mapping:
        form["mapping"] = mapping
    return authed.post("/api/imports/upload", headers=CSRF, data=form,
                       files={"file": (filename, data)})


def test_ofx_upload_inserts_transactions_and_balance(authed, appstate):
    a = make_account(authed)
    r = upload(authed, a["id"], "wellsfargo.ofx")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 3 and body["duplicates"] == 0
    assert body["balance_recorded"] is True

    txs = appstate.db.query("SELECT * FROM transactions ORDER BY posted_at")
    assert len(txs) == 3
    assert txs[0]["payee_norm"] == "WHOLEFDS SEATTLE WA"
    assert txs[0]["cat_source"] == "none"

    snaps = appstate.db.query("SELECT * FROM balance_snapshots")
    assert snaps[0]["balance_cents"] == 532145 and snaps[0]["source"] == "import"


def test_reupload_is_fully_deduped_by_fitid(authed):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    r = upload(authed, a["id"], "wellsfargo.ofx")
    assert r.json()["imported"] == 0 and r.json()["duplicates"] == 3


def test_csv_dedupe_preserves_true_same_day_duplicates(authed, appstate):
    """Two identical $5.50 donuts are both real; re-upload must not double them."""
    a = make_account(authed)
    r = upload(authed, a["id"], "wellsfargo.csv")
    assert r.json()["imported"] == 5

    r = upload(authed, a["id"], "wellsfargo.csv")
    assert r.json()["imported"] == 0 and r.json()["duplicates"] == 5

    donuts = appstate.db.query(
        "SELECT * FROM transactions WHERE payee_raw LIKE 'BLUE STAR%'")
    assert len(donuts) == 2


def test_csv_overlapping_window_partial_dedupe(authed):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.csv")
    # a later export overlaps one old row and adds one new one
    overlap = (b'"06/15/2026","-5.50","*","","BLUE STAR DONUTS PORTLAND OR"\n'
               b'"07/01/2026","-12.00","*","","NEW MERCHANT"\n')
    r = upload(authed, a["id"], "july.csv", content=overlap)
    assert r.json()["imported"] == 1 and r.json()["duplicates"] == 1


def test_citi_csv_with_mapping_negate_not_needed(authed):
    a = make_account(authed, name="Costco Card", type="credit")
    r = upload(authed, a["id"], "citi.csv")
    assert r.json()["imported"] == 3


def test_upload_to_missing_account_400(authed):
    r = upload(authed, 9999, "wellsfargo.ofx")
    assert r.status_code == 400


def test_garbage_file_400(authed):
    a = make_account(authed)
    r = upload(authed, a["id"], "junk.csv", content=b"complete nonsense with no commas")
    assert r.status_code == 400


def test_import_history_and_staleness(authed):
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    r = authed.get("/api/imports")
    assert r.json()[0]["tx_count"] == 3 and r.json()[0]["account_name"] == "Joint Checking"

    r = authed.get("/api/imports/staleness")
    row = next(x for x in r.json() if x["id"] == a["id"])
    # fixture data is from June 2026; "today" is well past staleness_days=10
    assert row["stale"] is True


def test_post_import_hook_receives_ids(authed, appstate):
    seen = []
    appstate.post_import_hooks.append(lambda ids: seen.extend(ids))
    a = make_account(authed)
    upload(authed, a["id"], "wellsfargo.ofx")
    assert len(seen) == 3
