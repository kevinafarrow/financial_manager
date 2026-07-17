import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database  # noqa: E402
from app.vault import Vault  # noqa: E402

TEST_KEY_HEX = "aa" * 32


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
