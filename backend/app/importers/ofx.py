"""OFX/QFX parsing via ofxtools (handles both SGML v1 and XML v2)."""

from __future__ import annotations

import io
from decimal import Decimal

from ofxtools.Parser import OFXTree

from .types import ParsedFile, RawTxn


class OfxParseError(ValueError):
    pass


def _cents(d: Decimal) -> int:
    return int((d * 100).to_integral_value())


def parse_ofx(data: bytes) -> ParsedFile:
    tree = OFXTree()
    try:
        tree.parse(io.BytesIO(data))
        ofx = tree.convert()
    except Exception as e:
        raise OfxParseError(f"could not parse OFX/QFX file: {e}") from e

    out = ParsedFile(format="ofx")
    for stmt in ofx.statements:
        for t in stmt.transactions:
            name = (t.name or "").strip()
            memo = (t.memo or "").strip()
            if not name:
                name, memo = memo, ""
            out.transactions.append(RawTxn(
                posted_at=t.dtposted.date().isoformat(),
                amount_cents=_cents(t.trnamt),
                payee_raw=name,
                memo=memo if memo != name else "",
                fitid=(t.fitid or None),
            ))
        bal = getattr(stmt, "balance", None) or getattr(stmt, "ledgerbal", None)
        if bal is not None and out.balance_cents is None:
            out.balance_cents = _cents(bal.balamt)
            out.balance_as_of = bal.dtasof.date().isoformat()
    return out
