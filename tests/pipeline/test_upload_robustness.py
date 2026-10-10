"""Jury-upload robustness: account numbers are not values, line codes are not numbers, statements with invoice
words in their purposes stay statements, PDF statements are read, and XLS / CSV / HTML-'xls' / HEIC are handled."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.pdfgen import canvas  # noqa: E402

from app.modules.documents.storage import SUPPORTED, detect_mime  # noqa: E402
from app.pipeline.parse import HEIC_UNSUPPORTED, PDF_STATEMENT_UNREADABLE, _filename_hint, parse_document  # noqa: E402
from app.pipeline.readable import readable_summary  # noqa: E402
from app.pipeline.statements import Categoriser, normalise_statement  # noqa: E402
from app.pipeline.types import ParsedDoc, ParsedPage, Word  # noqa: E402

from statement_pdf import ACCOUNT, OWN_STIR, ROWS, closing_balance, make_statement_pdf  # noqa: E402
from test_extract_fixtures import FONT  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"


def _row(y: float, *tokens: tuple[str, float]) -> list[Word]:
    return [Word(t, x, y, x + 6 * len(t), y + 9) for t, x in tokens]


# ------------------------------------------------------------------ 1. identifiers never become values

def test_statement_pdf_account_number_is_not_a_readable_number(tmp_path):
    pdf = make_statement_pdf(tmp_path / "st.pdf")
    doc = parse_document(str(pdf), "application/pdf", tmp_path / "out")
    nums = readable_summary(doc)["numbers"]
    texts = [n["text"].replace(" ", "") for n in nums]
    assert ACCOUNT not in texts and OWN_STIR not in texts          # identifiers, not amounts
    assert all(abs(n["value"]) < 1e15 for n in nums)                 # every value fits facts.value Numeric(20, 4)
    assert "13273000.00" in texts


def test_long_digit_runs_are_identifiers_on_any_row():
    page = ParsedPage(n=1, width=600, height=800, words=(
        _row(100, ("Hisob", 40), ("raqami:", 80), ("20208000500882571001", 140))
        + _row(120, ("Karta", 40), ("8600123456789012", 140))
        + _row(140, ("Summa", 40), ("1 250 000", 140))))
    nums = readable_summary(ParsedDoc(kind="pdf_text", pages=[page]))["numbers"]
    assert [n["value"] for n in nums] == [1_250_000.0]


def test_register_readable_numbers_skips_unstorable_values(db):
    """Summaries stored before the fix may still hold a 20-digit number: it is never written as a fact."""
    from app.modules.documents.models import Document
    from app.modules.llm.describe import register_readable_numbers
    doc = Document(filename="st.pdf", sha256="x" * 64, mime="application/pdf", size_bytes=1, owner_kind="public",
                   status="processing", summary={"readable": {"numbers": [
                       {"text": ACCOUNT, "value": float(ACCOUNT), "label": "Hisob raqami", "page_n": 1},
                       {"text": "1 250 000", "value": 1_250_000.0, "label": "Summa", "page_n": 1}]}})
    db.add(doc)
    db.flush()
    facts = register_readable_numbers(db, doc)
    assert [float(f.value) for f in facts.values()] == [1_250_000.0]


# ------------------------------------------------------------------ 2. line codes are not readable numbers

def test_line_codes_are_not_readable_numbers():
    page = ParsedPage(n=1, width=600, height=800, words=(
        _row(100, ("Sof", 40), ("tushum", 70), ("010", 300), ("9 842 316", 400), ("8 100 000", 500))
        + _row(120, ("Foyda", 40), ("solig'i", 80), ("040", 300), ("548 600", 400))
        + _row(140, ("100", 20), ("Jami", 60), ("aktivlar", 100), ("12 400 000", 400))
        + _row(160, ("Xodimlar", 40), ("soni", 100), ("110", 300), ("45", 400), ("38", 500))))
    nums = readable_summary(ParsedDoc(kind="pdf_text", pages=[page]))["numbers"]
    values = [n["value"] for n in nums]
    assert values == [9_842_316.0, 8_100_000.0, 548_600.0, 12_400_000.0]
    assert 40.0 not in values and 10.0 not in values and 110.0 not in values


# ------------------------------------------------------------------ 3. classification

def test_statement_pdf_with_invoice_purposes_is_a_statement(tmp_path):
    pdf = make_statement_pdf(tmp_path / "st.pdf")       # title has no 'ko'chirma' / 'выписка'
    doc = parse_document(str(pdf), "application/pdf", tmp_path / "out")
    assert doc.doc_type == "bank_statement", doc.type_reason
    assert "transaction table header" in doc.type_reason and "20-digit account number" in doc.type_reason
    assert "hisob-faktura" not in doc.type_reason.lower()


def test_real_invoice_pdf_is_still_an_invoice(tmp_path):
    p = tmp_path / "inv.pdf"
    c = canvas.Canvas(str(p))
    c.setFont(FONT, 10)
    lines = ["HISOB-FAKTURA № 2612", "Sana: 02.07.2026", "Yetkazib beruvchi: Zilola Mebel MChJ, STIR 304882571",
             "Xaridor: Angren Mehmonxona MChJ", "№  Tovar nomi            Miqdori   Narxi      Summa",
             "1  Stol                   4         450 000    1 800 000", "2  Stul                   10        103 300    1 033 000",
             "Jami: 2 833 000, shu jumladan QQS 12%"]
    for i, t in enumerate(lines):
        c.drawString(40, 800 - 16 * i, t)
    c.save()
    doc = parse_document(str(p), "application/pdf", tmp_path / "out")
    assert doc.doc_type == "invoice" and not doc.sheets


def test_filename_hint_uses_the_right_article():
    doc = ParsedDoc(kind="image", failure_cause="unclear")
    _filename_hint(doc, "faktura_2612.jpg")
    assert doc.type_reason.startswith("Probably an invoice")
    doc = ParsedDoc(kind="image", failure_cause="unclear")
    _filename_hint(doc, "vypiska_iyul.jpg")
    assert doc.type_reason.startswith("Probably a bank statement")


# ------------------------------------------------------------------ 4. PDF bank statements are read

def test_pdf_statement_transactions_feed_the_categoriser(tmp_path):
    for ruled in (True, False):
        pdf = make_statement_pdf(tmp_path / f"st{ruled}.pdf", ruled=ruled)
        doc = parse_document(str(pdf), "application/pdf", tmp_path / f"out{ruled}")
        assert not doc.failure_cause and doc.sheets and doc.pages      # pages stay for the evidence pane
        txns, facts, _ = normalise_statement(doc, None, Categoriser(use_model=False))
        assert [t.amount for t in txns] == [float((r[3] or 0) - (r[2] or 0)) for r in ROWS]
        assert txns[0].counterparty == "Shodlik Sut MChJ" and txns[0].counterparty_stir == "349955847"
        assert "tovar uchun to'lov" in txns[0].purpose                  # wrapped purpose line joined
        cats = {t.counterparty: t.category for t in txns}
        assert cats["Ipoteka Bank"] == "loan_repayment" and cats["Shodlik Sut MChJ"] == "sales_receipt"
        end = {f.field: f.value for f in facts if f.field.startswith("statement.balance_end")}
        assert end["statement.balance_end.2026-08"] == closing_balance() / 1000
        assert (doc.period_start.isoformat(), doc.stir) == ("2026-07-01", OWN_STIR)


def test_pdf_statement_without_a_readable_table_says_so_plainly(tmp_path):
    p = tmp_path / "v.pdf"
    c = canvas.Canvas(str(p))
    c.setFont(FONT, 10)
    for i, t in enumerate(["ВЫПИСКА ПО РАСЧЕТНОМУ СЧЕТУ", f"Счет {ACCOUNT}", "Входящий остаток на 01.07.2026: 150 100 000",
                           "Исходящий остаток на 31.07.2026: 161 236 000"]):
        c.drawString(40, 800 - 16 * i, t)
    c.save()
    doc = parse_document(str(p), "application/pdf", tmp_path / "out")
    assert doc.doc_type == "bank_statement" and doc.failure_cause == PDF_STATEMENT_UNREADABLE
    assert "XLSX" in doc.failure_cause


# ------------------------------------------------------------------ 5. formats

def test_xls_statement_takes_the_xlsx_path(tmp_path):
    content = (DATA / "statement_small.xls").read_bytes()
    assert detect_mime(content, "vypiska.xls")[0] in SUPPORTED
    doc = parse_document(str(DATA / "statement_small.xls"), "", tmp_path / "out")
    assert doc.kind == "xlsx" and doc.doc_type == "bank_statement" and not doc.failure_cause
    txns, _, _ = normalise_statement(doc, None, Categoriser(use_model=False))
    assert len(txns) >= 20 and txns[0].amount == 13_273_000.0 and txns[0].account == "20208000381842795001"


STATEMENT_CSV = (
    "ВЫПИСКА ПО РАСЧЕТНОМУ СЧЕТУ № 20208000500882571001\n"
    "Входящий остаток;;150 100 000,00\n"
    "Дата;№ док.;Дебет;Кредит;Наименование контрагента;ИНН контрагента;Счет контрагента;МФО банка;Назначение платежа\n"
    "01.07.2026;100;;13 273 000,00;Shodlik Sut MChJ;349955847;20208000381842795001;01089;Оплата по счет-фактуре №7063\n"
    "02.07.2026;101;2 137 000,00;;Navro'z Non XK;261298117;20208000382064321001;01153;Оплата за упаковку, с/ф №3085\n"
    "25.07.2026;102;18 500 000,00;;Ipoteka Bank;201055108;20208000900000000001;00873;Погашение кредита по договору 2024-1177\n"
)


def test_csv_statement(tmp_path):
    f = tmp_path / "original.csv"
    f.write_bytes(STATEMENT_CSV.encode("cp1251"))
    assert detect_mime(f.read_bytes(), "vypiska.csv") == ("text/csv", "csv")
    doc = parse_document(str(f), "text/csv", tmp_path / "out")
    assert doc.kind == "xlsx" and doc.doc_type == "bank_statement"
    txns, _, _ = normalise_statement(doc, None, Categoriser(use_model=False))
    assert [t.amount for t in txns] == [13_273_000.0, -2_137_000.0, -18_500_000.0]
    assert txns[0].account == "20208000381842795001"                   # identifiers stay text
    assert all(n["value"] < 1e15 for n in readable_summary(doc)["numbers"])


def test_html_table_saved_as_xls(tmp_path):
    rows = [line.split(";") for line in STATEMENT_CSV.strip().splitlines()]
    html = "<html><body><table>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table></body></html>"
    content = html.encode("utf-8")
    mime, ext = detect_mime(content, "vypiska.xls")
    assert mime in SUPPORTED and ext == "xls"
    f = tmp_path / "original.xls"
    f.write_bytes(content)
    doc = parse_document(str(f), mime, tmp_path / "out")
    assert doc.doc_type == "bank_statement"
    txns, _, _ = normalise_statement(doc, None, Categoriser(use_model=False))
    assert len(txns) == 3


def test_heic_photo_gets_a_plain_message(tmp_path):
    content = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 200
    mime, ext = detect_mime(content, "IMG_0042.HEIC")
    assert (mime, ext) == ("image/heic", "heic")
    f = tmp_path / "original.heic"
    f.write_bytes(content)
    doc = parse_document(str(f), mime, tmp_path / "out")
    assert doc.failure_cause == HEIC_UNSUPPORTED and "JPG" in doc.failure_cause


def test_plain_text_and_word_stay_unsupported(tmp_path):
    assert detect_mime(b"hello world", "notes.txt")[0] not in SUPPORTED
    ole_doc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "WordDocument".encode("utf-16-le") + b"\x00" * 100
    assert detect_mime(ole_doc, "letter.doc")[0] not in SUPPORTED
    f = tmp_path / "x.csv"
    f.write_text("just one line of text")
    assert "Unsupported file format" in parse_document(str(f), "text/csv", tmp_path / "o").failure_cause
