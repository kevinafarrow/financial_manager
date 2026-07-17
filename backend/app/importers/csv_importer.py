"""CSV parsing with auto-detection plus optional explicit column mapping.

Handles the common shapes:
- headered files (Date/Amount/Description, or separate Debit/Credit columns)
- Wells Fargo's headerless 5-column export: "date","amount","*","","payee"
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from .types import ParsedFile, RawTxn


class CsvParseError(ValueError):
    pass


DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"]

HEADER_ALIASES = {
    "date": ["date", "posted date", "post date", "transaction date", "posting date"],
    "payee": ["description", "payee", "name", "merchant", "transaction description"],
    "amount": ["amount", "transaction amount"],
    "debit": ["debit", "withdrawals", "withdrawal", "money out"],
    "credit": ["credit", "deposits", "deposit", "money in"],
    "memo": ["memo", "notes", "note", "extended description", "category"],
    "status": ["status"],
}


def _parse_date(s: str, fmt: str | None = None) -> str:
    s = s.strip()
    formats = [fmt] if fmt else DATE_FORMATS
    for f in formats:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    raise CsvParseError(f"unrecognized date: {s!r}")


_amount_clean_re = re.compile(r"[$,\s]")


def _parse_amount_cents(s: str) -> int:
    s = _amount_clean_re.sub("", s.strip())
    if not s:
        raise CsvParseError("empty amount")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = True, s[1:]
    if s.startswith("+"):
        s = s[1:]
    try:
        cents = round(float(s) * 100)
    except ValueError:
        raise CsvParseError(f"unrecognized amount: {s!r}")
    return -cents if negative else cents


def _match_headers(headers: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    lowered = [h.strip().lower() for h in headers]
    for role, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in lowered and role not in cols:
                cols[role] = lowered.index(alias)
    return cols


def parse_csv(data: bytes, mapping: dict | None = None) -> ParsedFile:
    """`mapping` (all optional): {date, payee, amount, debit, credit, memo: column
    index or header name, date_format: strptime format, negate: bool}."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        raise CsvParseError("empty file")

    mapping = dict(mapping or {})
    date_format = mapping.pop("date_format", None)
    negate = bool(mapping.pop("negate", False))

    first, has_header = rows[0], False
    cols: dict[str, int] = {}
    try:  # a header row's date column won't parse as a date
        _parse_date(first[0], date_format)
    except (CsvParseError, IndexError):
        has_header = True

    if has_header:
        cols = _match_headers(first)
    elif len(first) >= 5:  # Wells Fargo positional format
        cols = {"date": 0, "amount": 1, "payee": 4}
    else:
        cols = {"date": 0, "amount": 1, "payee": 2}

    # explicit mapping overrides detection; accepts header names or indexes
    lowered = [h.strip().lower() for h in first] if has_header else []
    for role, ref in mapping.items():
        if isinstance(ref, int):
            cols[role] = ref
        elif isinstance(ref, str) and ref.strip().lower() in lowered:
            cols[role] = lowered.index(ref.strip().lower())
        else:
            raise CsvParseError(f"mapping for {role!r} not found: {ref!r}")

    if "date" not in cols or "payee" not in cols or not (
            "amount" in cols or "debit" in cols or "credit" in cols):
        raise CsvParseError(
            "could not detect columns; provide a mapping for date/payee/amount")

    out = ParsedFile(format="csv")
    for lineno, row in enumerate(rows[1:] if has_header else rows, start=2):
        try:
            def cell(role: str) -> str:
                i = cols.get(role)
                return row[i].strip() if i is not None and i < len(row) else ""

            if cell("status").lower() == "pending":
                continue
            if "amount" in cols and cell("amount"):
                amount = _parse_amount_cents(cell("amount"))
            else:
                debit, credit = cell("debit"), cell("credit")
                if debit:
                    amount = -abs(_parse_amount_cents(debit))
                elif credit:
                    amount = abs(_parse_amount_cents(credit))
                else:
                    continue  # no money movement on this row
            if negate:
                amount = -amount
            out.transactions.append(RawTxn(
                posted_at=_parse_date(cell("date"), date_format),
                amount_cents=amount,
                payee_raw=cell("payee"),
                memo=cell("memo"),
            ))
        except CsvParseError as e:
            raise CsvParseError(f"line {lineno}: {e}") from None
    return out
