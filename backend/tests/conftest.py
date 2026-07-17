import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Config  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.state import AppState  # noqa: E402
from app.vault import Vault  # noqa: E402

TEST_KEY_HEX = "aa" * 32

PASSPHRASE = "test vault passphrase"
ADMIN = {"username": "kevin", "display_name": "Kevin", "password": "kevin-pass-1"}

# All mutating requests need the CSRF header the frontend always sends.
CSRF = {"X-Requested-With": "XMLHttpRequest"}


class FakeAlerts:
    """Stands in for AlertService; records instead of pushing."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, type_, title, message, url=None, priority=0):
        self.sent.append({"type": type_, "title": title, "message": message,
                          "url": url, "priority": priority})
        return True


@pytest.fixture
def appstate(tmp_path) -> AppState:
    cfg = Config(data_dir=tmp_path / "data", backup_dir=tmp_path / "backups",
                 enable_scheduler=False)
    state = AppState(cfg)
    state.setup(PASSPHRASE, ADMIN["username"], ADMIN["display_name"], ADMIN["password"])
    state.alerts = FakeAlerts()
    state.auth.alerts = state.alerts
    yield state
    if state.unlocked:
        state.lock()


@pytest.fixture
def client(appstate) -> TestClient:
    app = create_app(appstate)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed(client) -> TestClient:
    r = client.post("/api/auth/login",
                    json={"username": ADMIN["username"], "password": ADMIN["password"]},
                    headers=CSRF)
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def vault(tmp_path) -> Vault:
    v = Vault(tmp_path / "vault.json")
    v.initialize("correct horse battery staple")
    return v


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "test.db", TEST_KEY_HEX)
    d.migrate()
    yield d
    d.close()
