from tests.conftest import CSRF


def make_account(authed, **overrides):
    body = {"name": "Joint Checking", "institution": "Wells Fargo", "type": "checking"}
    body.update(overrides)
    r = authed.post("/api/accounts", headers=CSRF, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_and_list_accounts(authed):
    make_account(authed)
    make_account(authed, name="Costco Card", institution="Citi", type="credit")
    r = authed.get("/api/accounts")
    names = [a["name"] for a in r.json()]
    assert names == ["Costco Card", "Joint Checking"]


def test_duplicate_name_rejected(authed):
    make_account(authed)
    r = authed.post("/api/accounts", headers=CSRF,
                    json={"name": "Joint Checking", "type": "checking"})
    assert r.status_code == 409


def test_invalid_type_rejected(authed):
    r = authed.post("/api/accounts", headers=CSRF,
                    json={"name": "X", "type": "piggybank"})
    assert r.status_code == 400


def test_balance_only_account(authed):
    a = make_account(authed, name="Ameriprise 401k", type="investment", kind="balance_only")
    assert a["kind"] == "balance_only"


def test_patch_account(authed):
    a = make_account(authed)
    r = authed.patch(f"/api/accounts/{a['id']}", headers=CSRF,
                     json={"low_balance_threshold_cents": 50000, "archived": True})
    assert r.status_code == 200
    assert r.json()["low_balance_threshold_cents"] == 50000
    assert r.json()["archived"] == 1


def test_snapshots_roundtrip(authed):
    a = make_account(authed, name="Valon Mortgage", type="mortgage", kind="balance_only")
    r = authed.post(f"/api/accounts/{a['id']}/snapshots", headers=CSRF,
                    json={"as_of": "2026-07-01", "balance_cents": -41200000})
    assert r.status_code == 200
    r = authed.get(f"/api/accounts/{a['id']}/snapshots")
    assert r.json()[0]["balance_cents"] == -41200000
    r = authed.get("/api/accounts")
    acct = next(x for x in r.json() if x["id"] == a["id"])
    assert acct["latest_balance"]["balance_cents"] == -41200000


def test_account_404(authed):
    assert authed.patch("/api/accounts/999", headers=CSRF, json={}).status_code == 404


def test_audit_recorded(authed, appstate):
    make_account(authed)
    rows = appstate.db.query("SELECT * FROM audit_log WHERE entity='account'")
    assert len(rows) == 1 and rows[0]["action"] == "create"


def test_accounts_require_auth(client):
    assert client.get("/api/accounts").status_code == 401
