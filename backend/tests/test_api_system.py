"""API tests: setup / unlock / lock / login flows, CSRF, locked-state behavior."""

from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app
from app.state import AppState
from tests.conftest import ADMIN, CSRF, PASSPHRASE


def fresh_client(tmp_path) -> tuple[TestClient, AppState]:
    cfg = Config(data_dir=tmp_path / "data", backup_dir=tmp_path / "backups")
    state = AppState(cfg)
    return TestClient(create_app(state)), state


def test_first_run_setup_flow(tmp_path):
    client, state = fresh_client(tmp_path)
    r = client.get("/api/system/status")
    assert r.json() == {"initialized": False, "unlocked": False, "setup_needed": True}

    r = client.post("/api/system/setup", headers=CSRF, json={
        "passphrase": PASSPHRASE, **ADMIN,
    })
    assert r.status_code == 200
    assert r.json()["unlocked"] is True

    # second setup attempt rejected
    r = client.post("/api/system/setup", headers=CSRF, json={
        "passphrase": PASSPHRASE, **ADMIN,
    })
    assert r.status_code == 409
    state.lock()


def test_unlock_wrong_and_right_passphrase(tmp_path):
    client, state = fresh_client(tmp_path)
    client.post("/api/system/setup", headers=CSRF, json={"passphrase": PASSPHRASE, **ADMIN})
    state.lock()

    r = client.post("/api/system/unlock", headers=CSRF, json={"passphrase": "wrong wrong wrong"})
    assert r.status_code == 403

    r = client.post("/api/system/unlock", headers=CSRF, json={"passphrase": PASSPHRASE})
    assert r.status_code == 200 and r.json()["unlocked"] is True

    # user created during setup survives lock/unlock (data really persisted)
    r = client.post("/api/auth/login", headers=CSRF,
                    json={"username": ADMIN["username"], "password": ADMIN["password"]})
    assert r.status_code == 200
    state.lock()


def test_api_locked_returns_423(client, appstate):
    appstate.lock()
    r = client.post("/api/auth/login", headers=CSRF,
                    json={"username": "kevin", "password": "x" * 8})
    assert r.status_code == 423


def test_csrf_header_required(client):
    r = client.post("/api/auth/login", json={"username": "kevin", "password": "12345678"})
    assert r.status_code == 403
    assert "X-Requested-With" in r.json()["detail"]


def test_login_me_logout_flow(authed):
    r = authed.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["username"] == ADMIN["username"]

    r = authed.post("/api/auth/logout", headers=CSRF)
    assert r.status_code == 200

    r = authed.get("/api/auth/me")
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_bad_credentials_rejected(client):
    r = client.post("/api/auth/login", headers=CSRF,
                    json={"username": ADMIN["username"], "password": "wrong-pass"})
    assert r.status_code == 401


def test_lock_endpoint_requires_auth_then_locks(authed, appstate):
    r = authed.post("/api/system/lock", headers=CSRF)
    assert r.status_code == 200 and r.json()["unlocked"] is False
    assert not appstate.unlocked


def test_change_password(authed, client):
    r = authed.post("/api/auth/password", headers=CSRF, json={"new_password": "new-pass-123"})
    assert r.status_code == 200
    client.post("/api/auth/logout", headers=CSRF)
    r = client.post("/api/auth/login", headers=CSRF,
                    json={"username": ADMIN["username"], "password": "new-pass-123"})
    assert r.status_code == 200
