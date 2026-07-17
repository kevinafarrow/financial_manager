"""Parser + normalization + dedupe unit tests."""

from pathlib import Path

import pytest

from app.categorize.normalize import normalize_payee
from app.importers.csv_importer import CsvParseError, parse_csv
from app.importers.ofx import parse_ofx
from app.importers.service import content_hash

FIXTURES = Path(__file__).parent / "fixtures"


# -- normalization -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("WHOLEFDS #105 SEATTLE WA", "WHOLEFDS SEATTLE WA"),
    ("TARGET T-1234 TUKWILA WA", "TARGET TUKWILA WA"),
    ("SQ *BLUE BOTTLE COFFEE", "BLUE BOTTLE COFFEE"),
    ("TST* THAI TOM - SEATTLE", "THAI TOM SEATTLE"),
    ("CHECKCARD 0612 SHELL OIL 57444573", "SHELL OIL"),
    ("AMAZON.COM*RT4Y67 AMZN.COM/BILL", "AMAZON COM AMZN COM BILL"),
    ("POS DEBIT VISA 4124 XXXXXX1234 SAFEWAY", "SAFEWAY"),
])
def test_normalize_payee(raw, expected):
    assert normalize_payee(raw) == expected


def test_normalize_stable_across_stores():
    a = normalize_payee("WHOLEFDS #105 SEATTLE WA")
    b = normalize_payee("WHOLEFDS #0105 SEATTLE WA")
    assert a == b


def test_normalize_never_empty():
    assert normalize_payee("1234 5678") != ""


# -- OFX ---------------------------------------------------------------------

def test_parse_ofx_fixture():
    parsed = parse_ofx((FIXTURES / "wellsfargo.ofx").read_bytes())
    assert len(parsed.transactions) == 3
    t = parsed.transactions[0]
    assert (t.posted_at, t.amount_cents, t.fitid) == ("2026-06-10", -8412, "20260610001")
    assert t.payee_raw == "WHOLEFDS 105 SEATTLE WA"
    assert parsed.transactions[2].amount_cents == 250000
    assert parsed.balance_cents == 532145
    assert parsed.balance_as_of == "2026-06-30"


def test_parse_ofx_garbage_raises():
    from app.importers.ofx import OfxParseError
    with pytest.raises(OfxParseError):
        parse_ofx(b"OFXHEADER:100\n\n<OFX><BROKEN")


# -- CSV ---------------------------------------------------------------------

def test_parse_wells_fargo_headerless_csv():
    parsed = parse_csv((FIXTURES / "wellsfargo.csv").read_bytes())
    assert len(parsed.transactions) == 5
    assert parsed.transactions[0].posted_at == "2026-06-10"
    assert parsed.transactions[0].amount_cents == -8412
    assert parsed.transactions[0].payee_raw == "WHOLEFDS #105 SEATTLE WA"


def test_parse_citi_debit_credit_csv():
    parsed = parse_csv((FIXTURES / "citi.csv").read_bytes())
    amounts = [t.amount_cents for t in parsed.transactions]
    # debits negative, credits positive, pending skipped
    assert amounts == [-14287, -1549, 35000]


def test_csv_negate_flag():
    # some card exports use positive numbers for charges
    parsed = parse_csv(b"Date,Description,Amount\n06/01/2026,STORE,25.00\n",
                       {"negate": True})
    assert parsed.transactions[0].amount_cents == -2500


def test_csv_parenthetical_negative_and_dollar_signs():
    parsed = parse_csv(b"Date,Description,Amount\n06/01/2026,STORE,\"($1,234.56)\"\n")
    assert parsed.transactions[0].amount_cents == -123456


def test_csv_explicit_mapping_by_header_name():
    data = b"When,What,Total\n06/01/2026,STORE X,-9.99\n"
    parsed = parse_csv(data, {"date": "When", "payee": "What", "amount": "Total"})
    assert parsed.transactions[0].payee_raw == "STORE X"


def test_csv_undetectable_raises():
    with pytest.raises(CsvParseError):
        parse_csv(b"a,b\nnot-a-date,xyz\n")


def test_csv_bad_date_reports_line():
    data = b"Date,Description,Amount\n06/01/2026,OK,-1.00\nJunuary 5,BAD,-2.00\n"
    with pytest.raises(CsvParseError, match="line 3"):
        parse_csv(data)


# -- content hash ------------------------------------------------------------

def test_content_hash_stability():
    from app.importers.types import RawTxn
    a = RawTxn("2026-06-01", -500, "COFFEE", "")
    b = RawTxn("2026-06-01", -500, "COFFEE", "")
    c = RawTxn("2026-06-01", -501, "COFFEE", "")
    assert content_hash(a) == content_hash(b) != content_hash(c)
