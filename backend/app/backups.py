"""Encrypted backups: debounced snapshot after data changes, tiered retention.

Snapshot files are SQLCipher-encrypted copies (VACUUM INTO), safe to sync
anywhere. Retention: every per-update snapshot from the last 7 days, one per
ISO week for the last ~5 weeks, one per month for the last 12 months.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

FILENAME_RE = re.compile(r"^fm-(\d{8})-(\d{6})\.db$")
KEEP_ALL_DAYS = 7
KEEP_WEEKLY_DAYS = 35
KEEP_MONTHLY_DAYS = 366


class BackupService:
    def __init__(self, db, backup_dir: Path, debounce_seconds: float = 300):
        self.db = db
        self.backup_dir = Path(backup_dir)
        self.debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # -- snapshots -----------------------------------------------------------

    def snapshot(self, now: datetime | None = None) -> Path:
        now = now or datetime.now()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dest = self.backup_dir / f"fm-{now:%Y%m%d}-{now:%H%M%S}.db"
        if dest.exists():
            return dest
        self.db.vacuum_into(str(dest))
        log.info("backup snapshot written: %s", dest.name)
        return dest

    def notify_data_changed(self) -> None:
        """Debounced: a burst of edits yields one snapshot, not fifty."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        try:
            self.snapshot()
        except Exception:
            log.exception("debounced backup failed")

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    # -- retention -----------------------------------------------------------

    def list_backups(self) -> list[dict]:
        out = []
        if not self.backup_dir.exists():
            return out
        for p in sorted(self.backup_dir.iterdir(), reverse=True):
            ts = self._parse(p.name)
            if ts is None:
                continue
            out.append({"filename": p.name, "created_at": ts.isoformat(),
                        "size_bytes": p.stat().st_size})
        return out

    @staticmethod
    def _parse(name: str) -> datetime | None:
        m = FILENAME_RE.match(name)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None

    def prune(self, now: datetime | None = None) -> list[str]:
        """Deletes snapshots outside the retention tiers; returns deleted names."""
        now = now or datetime.now()
        entries = []  # (ts, path), newest first
        if self.backup_dir.exists():
            for p in self.backup_dir.iterdir():
                ts = self._parse(p.name)
                if ts is not None:
                    entries.append((ts, p))
        entries.sort(reverse=True)

        keep: set[Path] = set()
        weekly_seen: set[tuple[int, int]] = set()
        monthly_seen: set[tuple[int, int]] = set()
        for ts, p in entries:  # newest first → first in each bucket is kept
            age = now - ts
            if age <= timedelta(days=KEEP_ALL_DAYS):
                keep.add(p)
            elif age <= timedelta(days=KEEP_WEEKLY_DAYS):
                week = ts.isocalendar()[:2]
                if week not in weekly_seen:
                    weekly_seen.add(week)
                    keep.add(p)
            elif age <= timedelta(days=KEEP_MONTHLY_DAYS):
                month = (ts.year, ts.month)
                if month not in monthly_seen:
                    monthly_seen.add(month)
                    keep.add(p)
        deleted = []
        for ts, p in entries:
            if p not in keep:
                p.unlink()
                deleted.append(p.name)
        return deleted
