"""Application state and lifecycle: locked → unlocked wiring of all services."""

from __future__ import annotations

import logging
import threading

from .alerts import AlertService
from .auth import AuthService
from .config import Config
from .db import Database
from .secrets_store import SecretsStore
from .seed import seed_categories
from .vault import Vault

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, config: Config | None = None, http_client=None):
        self.config = config or Config()
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.vault = Vault(self.config.vault_meta_path)
        self.http_client = http_client  # injectable for tests (alerts)
        self.db: Database | None = None
        self.secrets: SecretsStore | None = None
        self.alerts: AlertService | None = None
        self.auth: AuthService | None = None
        self.categorizer = None
        self.receipts = None  # ReceiptService once unlocked
        self.chat = None  # ChatService once unlocked
        self.backups = None  # BackupService once unlocked
        self.scheduler = None  # set by scheduler.start() once unlocked
        self._unlock_lock = threading.Lock()
        # Hooks other modules register; called with no args.
        self.on_unlocked_hooks: list = []
        self.on_data_changed_hooks: list = []
        # Called with the list of newly inserted transaction ids after an import.
        self.post_import_hooks: list = []

    # -- state queries -------------------------------------------------------

    @property
    def unlocked(self) -> bool:
        return self.db is not None

    def status(self) -> dict:
        setup_needed = not self.vault.initialized
        return {
            "initialized": self.vault.initialized,
            "unlocked": self.unlocked,
            "setup_needed": setup_needed,
        }

    # -- lifecycle -----------------------------------------------------------

    def setup(self, passphrase: str, username: str, display_name: str, password: str) -> None:
        """First run: create vault, encrypted DB, and the first (admin) user."""
        with self._unlock_lock:
            if self.vault.initialized:
                raise ValueError("already initialized")
            self.vault.initialize(passphrase)
            self._wire()
            self.auth.create_user(username, display_name, password, is_admin=True)

    def unlock(self, passphrase: str) -> None:
        with self._unlock_lock:
            if self.unlocked:
                return
            self.vault.unlock(passphrase)  # raises WrongPassphrase
            self._wire()

    def lock(self) -> None:
        with self._unlock_lock:
            if self.scheduler is not None:
                try:
                    self.scheduler.shutdown(wait=False)
                except Exception:
                    pass
                self.scheduler = None
            if self.backups is not None:
                self.backups.stop()
            self.on_data_changed_hooks.clear()
            if self.db is not None:
                self.db.close()
            self.db = None
            self.secrets = None
            self.alerts = None
            self.auth = None
            self.categorizer = None
            self.receipts = None
            self.chat = None
            self.backups = None
            self.vault.lock()

    def _wire(self) -> None:
        self.db = Database(self.config.db_path, self.vault.key_hex)
        self.db.migrate()
        seed_categories(self.db)
        self.secrets = SecretsStore(self.db, self.vault)
        self.alerts = AlertService(self.db, self.secrets.get, http_client=self.http_client)
        self.auth = AuthService(self.db, alert_service=self.alerts)
        self._wire_categorizer()
        for hook in self.on_unlocked_hooks:
            try:
                hook()
            except Exception:
                log.exception("on_unlocked hook failed")
        if self.config.enable_scheduler:
            from . import scheduler

            self.scheduler = scheduler.start(self)

    def anthropic_client(self):
        """Returns an anthropic client using the stored API key, or None."""
        if self.secrets is None:
            return None
        api_key = self.secrets.get("anthropic_api_key")
        if not api_key:
            return None
        import anthropic

        return anthropic.Anthropic(api_key=api_key)

    def _wire_categorizer(self) -> None:
        from .categorize.claude_cat import ClaudeCategorizer
        from .categorize.pipeline import Categorizer

        from . import transfers

        claude = ClaudeCategorizer(self.anthropic_client, self.config.model_categorize)
        self.categorizer = Categorizer(self.db, claude)
        self.categorizer.retrain()

        def on_import(tx_ids: list[int]) -> None:
            # transfers first: a linked pair must never reach categorization
            try:
                transfers.find_and_link(self.db, tx_ids)
            except Exception:
                log.exception("transfer matching failed")
            try:
                self.categorizer.categorize_transactions(tx_ids)
            except Exception:
                log.exception("categorization pipeline failed")

        self.post_import_hooks.append(on_import)
        self._wire_receipts()
        from .chat import ChatService

        self.chat = ChatService(self.db, self.anthropic_client, self.config.model_chat)

        from .backups import BackupService

        self.backups = BackupService(self.db, self.config.backup_dir,
                                     self.config.backup_debounce_seconds)
        if self.config.backup_debounce_seconds > 0:
            self.on_data_changed_hooks.append(self.backups.notify_data_changed)

    def _wire_receipts(self) -> None:
        from . import settings_store
        from .receipts.imap_client import ImapFetcher
        from .receipts.parse import ClaudeReceiptParser
        from .receipts.service import ReceiptService

        parser = ClaudeReceiptParser(self.anthropic_client, self.config.model_categorize)
        fetcher = None
        imap = settings_store.get(self.db, "imap", {})
        if imap.get("host") and imap.get("username"):
            fetcher = ImapFetcher(
                imap["host"], int(imap.get("port", 993)), imap["username"],
                lambda: self.secrets.get("imap_password") if self.secrets else None)
        self.receipts = ReceiptService(self.db, parser, fetcher, self.categorizer)

    def data_changed(self) -> None:
        """Called after any data-mutating operation; drives backup debounce."""
        for hook in self.on_data_changed_hooks:
            try:
                hook()
            except Exception:
                log.exception("on_data_changed hook failed")
