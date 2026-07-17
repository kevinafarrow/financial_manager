from app.seed import EXPENSE_CATEGORIES, INCOME_CATEGORIES, SYSTEM_CATEGORIES
from tests.conftest import CSRF


def test_seeded_categories_present(authed):
    r = authed.get("/api/categories")
    names = {c["name"] for c in r.json()}
    for n in EXPENSE_CATEGORIES + INCOME_CATEGORIES + SYSTEM_CATEGORIES:
        assert n in names


def test_seed_runs_once(appstate):
    from app.seed import seed_categories
    before = appstate.db.query_one("SELECT count(*) c FROM categories")["c"]
    seed_categories(appstate.db)
    assert appstate.db.query_one("SELECT count(*) c FROM categories")["c"] == before


def test_create_rename_archive_category(authed):
    r = authed.post("/api/categories", headers=CSRF, json={"name": "Lawn Care"})
    assert r.status_code == 200
    cid = r.json()["id"]
    r = authed.patch(f"/api/categories/{cid}", headers=CSRF,
                     json={"name": "Yard & Garden", "archived": True})
    assert r.json()["name"] == "Yard & Garden" and r.json()["archived"] == 1


def test_duplicate_category_rejected(authed):
    r = authed.post("/api/categories", headers=CSRF, json={"name": "Groceries"})
    assert r.status_code == 409


def test_system_category_immutable(authed):
    r = authed.get("/api/categories")
    unc = next(c for c in r.json() if c["name"] == "Uncategorized")
    r = authed.patch(f"/api/categories/{unc['id']}", headers=CSRF, json={"name": "Nope"})
    assert r.status_code == 400


def test_invalid_kind_rejected(authed):
    r = authed.post("/api/categories", headers=CSRF, json={"name": "X", "kind": "system"})
    assert r.status_code == 400
