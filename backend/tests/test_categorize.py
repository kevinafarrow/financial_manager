"""Unit tests for the categorization tiers."""

import pytest

from app.categorize import bayes, history, rules
from app.categorize.pipeline import Categorizer


@pytest.fixture
def cats(db):
    ids = {}
    for name in ["Groceries", "Gas", "Eating Out"]:
        ids[name] = db.execute(
            "INSERT INTO categories (name, kind) VALUES (?, 'expense')", (name,))
    return ids


def make_tx(db, account_id=None, payee="WHOLEFDS SEATTLE WA", amount=-5000,
            payee_raw=None, memo=""):
    if account_id is None:
        account_id = db.query_one("SELECT id FROM accounts LIMIT 1")["id"] if \
            db.query_one("SELECT id FROM accounts LIMIT 1") else db.execute(
            "INSERT INTO accounts (name, type) VALUES ('T', 'checking')")
    return db.execute(
        "INSERT INTO transactions (account_id, content_hash, posted_at, amount_cents, "
        "payee_raw, payee_norm, memo) VALUES (?, 'h', '2026-06-01', ?, ?, ?, ?)",
        (account_id, amount, payee_raw or payee, payee, memo))


# -- history -----------------------------------------------------------------

def test_history_most_recent_wins(db, cats):
    history.record(db, "WHOLEFDS", cats["Gas"], "claude")
    history.record(db, "WHOLEFDS", cats["Groceries"], "claude")
    assert history.match(db, "WHOLEFDS") == cats["Groceries"]


def test_history_user_outranks_claude(db, cats):
    history.record(db, "WHOLEFDS", cats["Groceries"], "user", user_id=None)
    history.record(db, "WHOLEFDS", cats["Gas"], "claude")
    assert history.match(db, "WHOLEFDS") == cats["Groceries"]


def test_history_no_match(db, cats):
    assert history.match(db, "NEVER SEEN") is None


def test_history_ignores_archived_category(db, cats):
    history.record(db, "WHOLEFDS", cats["Groceries"], "user")
    db.execute("UPDATE categories SET archived = 1 WHERE id = ?", (cats["Groceries"],))
    assert history.match(db, "WHOLEFDS") is None


# -- rules -------------------------------------------------------------------

def test_rule_matches_by_priority(db, cats):
    db.execute("INSERT INTO rules (field, pattern, category_id, priority) "
               "VALUES ('payee', 'SHELL|CHEVRON', ?, 10)", (cats["Gas"],))
    db.execute("INSERT INTO rules (field, pattern, category_id, priority) "
               "VALUES ('payee', 'SHELL', ?, 20)", (cats["Groceries"],))
    hit = rules.match(db, "SHELL OIL 1234", "")
    assert hit[0] == cats["Gas"]


def test_rule_memo_field_and_disabled(db, cats):
    db.execute("INSERT INTO rules (field, pattern, category_id, enabled) "
               "VALUES ('memo', 'lunch', ?, 0)", (cats["Eating Out"],))
    assert rules.match(db, "X", "team lunch") is None
    db.execute("UPDATE rules SET enabled = 1")
    assert rules.match(db, "X", "team lunch")[0] == cats["Eating Out"]


def test_rule_validate_pattern():
    assert rules.validate_pattern("TARGET.*") is None
    assert rules.validate_pattern("(unclosed") is not None


# -- bayes -------------------------------------------------------------------

def _train_grocery_gas(nb, n=15):
    examples = []
    for i in range(n):
        examples.append((bayes.features("WHOLEFDS SEATTLE", -5000), 1))
        examples.append((bayes.features("SHELL OIL STATION", -4000), 2))
    nb.train(examples)


def test_bayes_untrained_returns_none():
    nb = bayes.NaiveBayes()
    nb.train([(["A"], 1)] * 5)  # below MIN_TRAINING_EXAMPLES / single class
    assert nb.predict(["A"]) is None


def test_bayes_confident_on_seen_merchant():
    nb = bayes.NaiveBayes()
    _train_grocery_gas(nb)
    result = nb.confident_prediction(bayes.features("WHOLEFDS SEATTLE", -6000))
    assert result is not None and result[0] == 1


def test_bayes_not_confident_on_unseen_merchant():
    nb = bayes.NaiveBayes()
    _train_grocery_gas(nb)
    assert nb.confident_prediction(bayes.features("TOTALLY NEW MERCHANT", -100)) is None


def test_bayes_amount_features_bucketing():
    assert "AMT_LT_10" in bayes.features("X", -500)
    assert "AMT_100_500" in bayes.features("X", -20000)
    assert "AMT_GT_2K" in bayes.features("X", -500000)
    assert "SIGN_POS" in bayes.features("X", 100)


# -- pipeline ----------------------------------------------------------------

class FakeClaude:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def categorize(self, txs, category_names, examples=None):
        self.calls.append(txs)
        return {t["index"]: self.answers[t["payee"]]
                for t in txs if t["payee"] in self.answers}


def test_pipeline_tiers_and_queue(db, cats):
    # history hit
    history.record(db, "WHOLEFDS SEATTLE WA", cats["Groceries"], "user")
    t1 = make_tx(db, payee="WHOLEFDS SEATTLE WA")
    # rule hit
    db.execute("INSERT INTO rules (field, pattern, category_id) "
               "VALUES ('payee', 'SHELL', ?)", (cats["Gas"],))
    t2 = make_tx(db, payee="SHELL OIL", payee_raw="SHELL OIL 57444")
    # claude hit
    t3 = make_tx(db, payee="THAI TOM", payee_raw="TST* THAI TOM")
    # queue
    t4 = make_tx(db, payee="MYSTERY VENDOR")

    claude = FakeClaude({"TST* THAI TOM": ("Eating Out", "high")})
    c = Categorizer(db, claude)
    stats = c.categorize_transactions([t1, t2, t3, t4])

    assert stats == {"history": 1, "rule": 1, "bayes": 0, "claude": 1, "queued": 1}
    rows = {r["id"]: r for r in db.query("SELECT * FROM transactions")}
    assert rows[t1]["category_id"] == cats["Groceries"] and rows[t1]["cat_source"] == "history"
    assert rows[t2]["category_id"] == cats["Gas"] and rows[t2]["cat_source"] == "rule"
    assert rows[t3]["category_id"] == cats["Eating Out"] and rows[t3]["cat_source"] == "claude"
    assert rows[t4]["category_id"] is None and rows[t4]["cat_source"] == "none"


def test_claude_answer_feeds_history_tier(db, cats):
    claude = FakeClaude({"TST* THAI TOM": ("Eating Out", "high")})
    c = Categorizer(db, claude)
    t1 = make_tx(db, payee="THAI TOM", payee_raw="TST* THAI TOM")
    c.categorize_transactions([t1])
    assert len(claude.calls) == 1

    # same merchant again: history tier handles it, claude not called
    t2 = make_tx(db, payee="THAI TOM", payee_raw="TST* THAI TOM SEATTLE")
    c.categorize_transactions([t2])
    assert len(claude.calls) == 1
    assert db.query_one("SELECT cat_source FROM transactions WHERE id = ?",
                        (t2,))["cat_source"] == "history"


def test_claude_failure_leaves_queue(db, cats):
    class BrokenClaude:
        def categorize(self, *a, **k):
            return {}

    c = Categorizer(db, BrokenClaude())
    t = make_tx(db, payee="MYSTERY")
    stats = c.categorize_transactions([t])
    assert stats["queued"] == 1


def test_user_categorize_records_history_and_wins(db, cats):
    c = Categorizer(db, None)
    t = make_tx(db, payee="COSTCO WHSE")
    c.user_categorize(t, cats["Groceries"], user_id=None)
    row = db.query_one("SELECT * FROM transactions WHERE id = ?", (t,))
    assert row["cat_source"] == "user" and row["category_id"] == cats["Groceries"]
    assert history.match(db, "COSTCO WHSE") == cats["Groceries"]


def test_bayes_tier_in_pipeline(db, cats):
    c = Categorizer(db, None)
    # seed enough user-categorized history for training
    acct = db.execute("INSERT INTO accounts (name, type) VALUES ('A', 'checking')")
    for i in range(15):
        tid = make_tx(db, account_id=acct, payee="PCC MARKET SEATTLE", amount=-4000)
        c.user_categorize(tid, cats["Groceries"], None)
        tid = make_tx(db, account_id=acct, payee="CHEVRON STATION", amount=-3500)
        c.user_categorize(tid, cats["Gas"], None)
    c.retrain()
    # a *variant* payee norm history can't match exactly... use same norm but
    # bayes runs only if history misses; so use a token-overlapping new norm
    t = make_tx(db, account_id=acct, payee="PCC MARKET BALLARD", amount=-4200)
    stats = c.categorize_transactions([t])
    assert stats["bayes"] == 1
    assert db.query_one("SELECT category_id FROM transactions WHERE id = ?",
                        (t,))["category_id"] == cats["Groceries"]
