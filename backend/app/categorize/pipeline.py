"""The full categorization pipeline: history → rules → bayes → claude → queue."""

from __future__ import annotations

import logging

from . import bayes, history, rules
from .claude_cat import ClaudeCategorizer

log = logging.getLogger(__name__)


class Categorizer:
    def __init__(self, db, claude: ClaudeCategorizer | None = None):
        self.db = db
        self.claude = claude
        self.nb = bayes.NaiveBayes()

    def retrain(self) -> None:
        self.nb = bayes.train_from_db(self.db)

    # -- pipeline ------------------------------------------------------------

    def categorize_transactions(self, tx_ids: list[int]) -> dict:
        """Runs the local tiers, then a single Claude batch for leftovers.
        Anything still unresolved stays cat_source='none' (the manual queue)."""
        stats = {"history": 0, "rule": 0, "bayes": 0, "claude": 0, "queued": 0}
        unknown: list[dict] = []
        for tx_id in tx_ids:
            tx = self.db.query_one("SELECT * FROM transactions WHERE id = ?", (tx_id,))
            if tx is None or tx["category_id"] is not None or tx["transfer_id"]:
                continue

            cat = history.match(self.db, tx["payee_norm"])
            if cat is not None:
                self._assign(tx_id, cat, "history", 1.0)
                stats["history"] += 1
                continue

            rule_hit = rules.match(self.db, tx["payee_raw"], tx["memo"])
            if rule_hit is not None:
                self._assign(tx_id, rule_hit[0], "rule", 1.0)
                stats["rule"] += 1
                continue

            guess = self.nb.confident_prediction(
                bayes.features(tx["payee_norm"], tx["amount_cents"]))
            if guess is not None:
                self._assign(tx_id, guess[0], "bayes", guess[1])
                stats["bayes"] += 1
                continue

            unknown.append(tx)

        if unknown and self.claude is not None:
            stats["claude"] = self._claude_tier(unknown)
            stats["queued"] = len(unknown) - stats["claude"]
        else:
            stats["queued"] = len(unknown)
        return stats

    def _claude_tier(self, txs: list[dict]) -> int:
        categories = {c["name"]: c["id"] for c in self.db.query(
            "SELECT id, name FROM categories WHERE archived = 0 AND kind != 'system'")}
        examples = self.db.query(
            "SELECT ch.payee_norm AS payee, c.name AS category FROM category_history ch "
            "JOIN categories c ON c.id = ch.category_id "
            "ORDER BY ch.id DESC LIMIT 10")
        payload = [{"index": i, "payee": t["payee_raw"], "memo": t["memo"],
                    "amount": f"${abs(t['amount_cents']) / 100:.2f}"
                              + (" charge" if t["amount_cents"] < 0 else " credit")}
                   for i, t in enumerate(txs)]
        results = self.claude.categorize(payload, sorted(categories))
        assigned = 0
        for i, (cat_name, confidence) in results.items():
            if 0 <= i < len(txs):
                tx = txs[i]
                conf = 0.9 if confidence == "high" else 0.7
                self._assign(tx["id"], categories[cat_name], "claude", conf)
                # Claude answers feed the history tier so this merchant is free next time
                history.record(self.db, tx["payee_norm"], categories[cat_name], "claude")
                assigned += 1
        return assigned

    def _assign(self, tx_id: int, category_id: int, source: str, confidence: float) -> None:
        self.db.execute(
            "UPDATE transactions SET category_id = ?, cat_source = ?, "
            "cat_confidence = ?, updated_at = datetime('now') WHERE id = ?",
            (category_id, source, confidence, tx_id),
        )

    # -- user decisions ------------------------------------------------------

    def user_categorize(self, tx_id: int, category_id: int, user_id: int) -> None:
        """A user assignment or correction: applies it and feeds the history tier."""
        tx = self.db.query_one("SELECT payee_norm FROM transactions WHERE id = ?", (tx_id,))
        if tx is None:
            raise ValueError("transaction not found")
        self.db.execute(
            "UPDATE transactions SET category_id = ?, cat_source = 'user', "
            "cat_confidence = 1.0, updated_at = datetime('now'), updated_by = ? "
            "WHERE id = ?",
            (category_id, user_id, tx_id),
        )
        history.record(self.db, tx["payee_norm"], category_id, "user", user_id)
