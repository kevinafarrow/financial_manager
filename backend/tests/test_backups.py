"""Backups: encrypted snapshots, debounce, tiered retention, export API."""

import sqlite3
import time
from datetime import datetime, timedelta

from app.backups import BackupService
from app.db import Database
from tests.conftest import CSRF, TEST_KEY_HEX


def test_snapshot_is_encrypted_and_restorable(db, tmp_path):
    db.execute("INSERT INTO categories (name) VALUES ('Sentinel-Cat')")
    svc = BackupService(db, tmp_path / "backups")
    path = svc.snapshot(now=datetime(2026, 7, 17, 12, 0, 0))
    assert path.name == "fm-20260717-120000.db"

    raw = path.read_bytes()
    assert b"Sentinel-Cat" not in raw  # still encrypted
    try:
        sqlite3.connect(path).execute("SELECT * FROM categories").fetchall()
        assert False, "plaintext sqlite should not open this"
    except sqlite3.DatabaseError:
        pass

    restored = Database(path, TEST_KEY_HEX)  # same key opens the snapshot
    names = [r["name"] for r in restored.query("SELECT name FROM categories")]
    restored.close()
    assert "Sentinel-Cat" in names


def test_debounce_coalesces_burst(db, tmp_path):
    svc = BackupService(db, tmp_path / "b", debounce_seconds=0.15)
    for _ in range(10):
        svc.notify_data_changed()
    time.sleep(0.4)
    assert len(svc.list_backups()) == 1
    svc.stop()


def test_prune_retention_tiers(db, tmp_path):
    svc = BackupService(db, tmp_path / "b")
    now = datetime(2026, 7, 17, 12, 0, 0)
    stamps = []
    # 3 within the last week (all kept)
    stamps += [now - timedelta(days=d) for d in (1, 3, 6)]
    # two in the same ISO week ~2 weeks back (only newest of the week kept)
    stamps += [now - timedelta(days=15), now - timedelta(days=16)]
    # two in the same month ~3 months back (only newest of the month kept)
    stamps += [now - timedelta(days=95), now - timedelta(days=97)]
    # one beyond a year (deleted)
    stamps += [now - timedelta(days=400)]
    for ts in stamps:
        svc.snapshot(now=ts)
    assert len(svc.list_backups()) == 8

    deleted = svc.prune(now=now)
    kept = {b["filename"] for b in svc.list_backups()}
    assert len(deleted) == 3
    assert len(kept) == 5
    # newest of the pair survives in each collapsed bucket
    assert f"fm-{(now - timedelta(days=15)):%Y%m%d}-120000.db" in kept
    assert f"fm-{(now - timedelta(days=16)):%Y%m%d}-120000.db" not in kept
    assert f"fm-{(now - timedelta(days=95)):%Y%m%d}-120000.db" in kept
    assert f"fm-{(now - timedelta(days=400)):%Y%m%d}-120000.db" not in kept


def test_prune_ignores_foreign_files(db, tmp_path):
    bdir = tmp_path / "b"
    bdir.mkdir()
    (bdir / "notes.txt").write_text("keep me")
    svc = BackupService(db, bdir)
    svc.prune()
    assert (bdir / "notes.txt").exists()


def test_backup_api_and_export(authed, appstate):
    r = authed.post("/api/backups/snapshot", headers=CSRF)
    assert r.status_code == 200
    assert r.json()["filename"].startswith("fm-")
    assert len(authed.get("/api/backups").json()) >= 1

    r = authed.get("/api/backups/export")
    assert r.status_code == 200
    assert not r.content.startswith(b"SQLite format 3")  # encrypted bytes


def test_data_change_hook_registered_when_enabled(tmp_path):
    from app.config import Config
    from app.state import AppState

    cfg = Config(data_dir=tmp_path / "d", backup_dir=tmp_path / "b",
                 enable_scheduler=False, backup_debounce_seconds=0.05)
    state = AppState(cfg)
    state.setup("test vault passphrase", "kevin", "Kevin", "kevin-pass-1")
    try:
        state.data_changed()
        time.sleep(0.3)
        assert len(state.backups.list_backups()) == 1
    finally:
        state.lock()
