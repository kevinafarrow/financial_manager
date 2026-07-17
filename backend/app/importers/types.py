from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawTxn:
    posted_at: str  # YYYY-MM-DD
    amount_cents: int  # signed: expenses negative
    payee_raw: str
    memo: str = ""
    fitid: str | None = None


@dataclass
class ParsedFile:
    transactions: list[RawTxn] = field(default_factory=list)
    # OFX ledger balance if the file carried one
    balance_cents: int | None = None
    balance_as_of: str | None = None
    format: str = ""
