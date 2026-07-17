"""First-run seed data."""

from __future__ import annotations

EXPENSE_CATEGORIES = [
    "Groceries", "Eating Out", "Mortgage", "Home Improvement", "Clothes",
    "Art Supplies", "Business", "Kevin Unnecessary Spending",
    "Mary Unnecessary Spending", "Dates", "Health Care", "Medical Expenses",
    "Subscriptions", "Gas", "Travel", "Utilities", "Insurance",
    "Childcare & Kids", "Pets", "Taxes & Government Fees",
    "Bank Fees & Interest", "Gifts & Donations", "Entertainment",
]
INCOME_CATEGORIES = ["Income"]
SYSTEM_CATEGORIES = ["Uncategorized"]


def seed_categories(db) -> None:
    if db.query_one("SELECT count(*) c FROM categories")["c"] > 0:
        return
    rows = (
        [(n, "expense", i) for i, n in enumerate(EXPENSE_CATEGORIES)]
        + [(n, "income", 100 + i) for i, n in enumerate(INCOME_CATEGORIES)]
        + [(n, "system", 200 + i) for i, n in enumerate(SYSTEM_CATEGORIES)]
    )
    db.executemany(
        "INSERT INTO categories (name, kind, sort_order) VALUES (?, ?, ?)", rows
    )
