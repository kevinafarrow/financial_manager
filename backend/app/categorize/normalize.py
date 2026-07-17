"""Payee normalization: collapse bank noise so the same merchant always maps to
the same string. This key drives history matching and bayes features, so it must
be stable across statements."""

from __future__ import annotations

import re

# Processor/bank boilerplate that carries no merchant signal.
NOISE_TOKENS = {
    "POS", "DEBIT", "CREDIT", "PURCHASE", "CHECKCARD", "CHECK", "CARD", "VISA",
    "MASTERCARD", "ACH", "WEB", "PPD", "CCD", "AUTH", "AUTHORIZED", "PAYMENT",
    "PMT", "PMNT", "RECURRING", "RECUR", "AUTOPAY", "ONLINE", "TERMINAL",
    "WITHDRAWAL", "DEPOSIT", "PENDING", "TST", "SQ", "SP", "PY", "PAYPAL",
}
# Tokens like TST* / SQ* prefix the real merchant on payment processors —
# keep the merchant, drop the prefix (handled by NOISE after splitting on *).

_split_re = re.compile(r"[^A-Z0-9&']+")
_digits_re = re.compile(r"\d")


def normalize_payee(raw: str) -> str:
    s = raw.upper()
    s = s.replace("*", " ").replace("#", " ")
    tokens = [t for t in _split_re.split(s) if t]
    keep: list[str] = []
    for t in tokens:
        digits = len(_digits_re.findall(t))
        if digits >= 3 or (digits > 0 and digits == len(t)):
            continue  # store numbers, dates, phone fragments, card suffixes
        if t in NOISE_TOKENS:
            continue
        if t.startswith("X") and set(t) <= {"X"}:
            continue  # masked digits
        if len(t) == 1:
            continue  # dangling store-number prefixes like the T in "T-1234"
        keep.append(t)
    norm = " ".join(keep).strip()
    return norm[:80] if norm else raw.upper().strip()[:80]
