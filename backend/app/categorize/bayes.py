"""Tier 3: multinomial naive-Bayes classifier over payee tokens + amount features.

Hand-rolled (no sklearn): the feature space is tiny (merchant tokens), training
data is at most a few tens of thousands of rows, and pure Python retrains in
milliseconds. Predictions are only trusted above a confidence threshold.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

MIN_PROBABILITY = 0.85
MIN_RATIO = 3.0
MIN_TRAINING_EXAMPLES = 20

AMOUNT_BUCKETS = [(1000, "AMT_LT_10"), (5000, "AMT_10_50"), (10000, "AMT_50_100"),
                  (50000, "AMT_100_500"), (200000, "AMT_500_2K")]


def features(payee_norm: str, amount_cents: int) -> list[str]:
    tokens = payee_norm.split()
    tokens.append("SIGN_NEG" if amount_cents < 0 else "SIGN_POS")
    mag = abs(amount_cents)
    for limit, name in AMOUNT_BUCKETS:
        if mag < limit:
            tokens.append(name)
            break
    else:
        tokens.append("AMT_GT_2K")
    return tokens


class NaiveBayes:
    def __init__(self):
        self.class_counts: Counter[int] = Counter()
        self.token_counts: dict[int, Counter[str]] = defaultdict(Counter)
        self.class_totals: Counter[int] = Counter()
        self.vocab: set[str] = set()
        self.n_examples = 0

    def train(self, examples: list[tuple[list[str], int]]) -> None:
        """examples: [(feature_tokens, category_id), ...]"""
        self.__init__()
        for tokens, label in examples:
            self.class_counts[label] += 1
            self.n_examples += 1
            for t in tokens:
                self.token_counts[label][t] += 1
                self.class_totals[label] += 1
                self.vocab.add(t)

    @property
    def trained(self) -> bool:
        return self.n_examples >= MIN_TRAINING_EXAMPLES and len(self.class_counts) >= 2

    def predict(self, tokens: list[str]) -> tuple[int, float, float] | None:
        """Returns (category_id, probability, top1/top2 ratio) or None if untrained."""
        if not self.trained:
            return None
        v = len(self.vocab) or 1
        log_scores: dict[int, float] = {}
        for label, count in self.class_counts.items():
            score = math.log(count / self.n_examples)
            denom = self.class_totals[label] + v
            for t in tokens:
                score += math.log((self.token_counts[label][t] + 1) / denom)
            log_scores[label] = score
        ranked = sorted(log_scores.items(), key=lambda kv: kv[1], reverse=True)
        # normalize via log-sum-exp for a real probability
        max_log = ranked[0][1]
        total = sum(math.exp(s - max_log) for _, s in ranked)
        prob = 1.0 / total
        ratio = (math.exp(ranked[0][1] - ranked[1][1]) if len(ranked) > 1
                 else float("inf"))
        return ranked[0][0], prob, ratio

    def confident_prediction(self, tokens: list[str]) -> tuple[int, float] | None:
        result = self.predict(tokens)
        if result is None:
            return None
        label, prob, ratio = result
        if prob >= MIN_PROBABILITY and ratio >= MIN_RATIO:
            return label, prob
        return None


def train_from_db(db) -> NaiveBayes:
    """Train on every transaction whose category came from a trusted source
    (everything except bayes itself, to avoid a feedback loop)."""
    rows = db.query(
        "SELECT t.payee_norm, t.amount_cents, t.category_id FROM transactions t "
        "JOIN categories c ON c.id = t.category_id AND c.archived = 0 "
        "WHERE t.category_id IS NOT NULL AND t.transfer_id IS NULL "
        "AND t.cat_source IN ('user', 'receipt', 'claude', 'rule', 'history')")
    nb = NaiveBayes()
    nb.train([(features(r["payee_norm"], r["amount_cents"]), r["category_id"])
              for r in rows])
    return nb
