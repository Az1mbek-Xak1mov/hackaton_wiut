import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.pipeline.parse import parse_document, sniff_kind  # noqa: E402
from app.pipeline.readable import readable_summary  # noqa: E402

from test_extract_fixtures import FONT, form2_values, make_form_pdf  # noqa: E402


def test_text_pdf_pages_and_png(tmp_path):
    pdf = make_form_pdf(tmp_path / "f2.pdf", "form2", form2_values(2), {}, lang="ru", period_text="за 2025 год")
    doc = parse_document(str(pdf), "application/pdf", tmp_path / "out")
    assert doc.kind == "pdf_text" and doc.text_layer and not doc.failure_cause
    p = doc.pages[0]
    assert Path(p.image_path).exists()
    with Image.open(p.image_path) as im:
        assert abs(im.width - p.width * p.image_scale) < 2  # bbox * image_scale = PNG px
    assert doc.stir == "302447118"


def test_xlsx_statement_classified(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ВЫПИСКА ПО РАСЧЕТНОМУ СЧЕТУ за период с 01.01.2026 по 31.08.2026"])
    ws.append(["Дата", "№ док", "Дебет", "Кредит", "Контрагент", "ИНН", "Назначение платежа"])
    ws.append(["05.01.2026", "1", None, 1500000, "Dilshod Trade MChJ", "305112233", "Оплата за товар"])
    f = tmp_path / "s.xlsx"
    wb.save(f)
    doc = parse_document(str(f), "", tmp_path / "out")
    assert doc.kind == "xlsx" and doc.doc_type == "bank_statement" and doc.sheets[0].rows[1][0] == "Дата"
    assert (doc.period_start.isoformat(), doc.period_end.isoformat()) == ("2026-01-01", "2026-08-31")
    assert readable_summary(doc)["numbers"][0]["value"] == 1500000


def test_unsupported_and_encrypted(tmp_path):
    docx = tmp_path / "letter.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    d = parse_document(str(docx), "", tmp_path / "o1")
    assert d.kind == "unsupported" and "Word" in d.failure_cause
    junk = tmp_path / "x.bin"
    junk.write_bytes(b"\x00\x01garbage")
    assert sniff_kind(str(junk)) == "unsupported"
    enc = tmp_path / "enc.pdf"
    c = canvas.Canvas(str(enc), encrypt="secret")
    c.setFont(FONT, 10)
    c.drawString(40, 800, "Бухгалтерский баланс")
    c.save()
    d = parse_document(str(enc), "", tmp_path / "o2")
    assert "encrypted" in d.failure_cause


def test_unknown_pdf_still_returns_what_was_read(tmp_path):
    pdf = tmp_path / "letter.pdf"
    c = canvas.Canvas(str(pdf))
    c.setFont(FONT, 11)
    for i, line in enumerate(["Dear partner,", "Our turnover in 2025 reached 12 450 000 so'm.",
                              "Contract dated 14.11.2024, STIR 305112233.", "Kind regards"]):
        c.drawString(40, 800 - 18 * i, line)
    c.save()
    doc = parse_document(str(pdf), "", tmp_path / "out")
    assert doc.doc_type == "unknown" and doc.type_reason.startswith("Not a recognised")
    r = readable_summary(doc)
    assert r["numbers"][0]["value"] == 12_450_000 and r["numbers"][0]["page_n"] == 1
    assert "2024-11-14" in r["dates"] and r["stirs"] == ["305112233"] and "Dear partner" in r["text_excerpt"]


def test_statement_with_invoice_purposes_is_still_a_statement(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ҲИСОБ РАҚАМИДАН КЎЧИРМА"])
    ws.append(["Давр: 01.01.2026 - 31.08.2026"])
    ws.append(["Сана", "Ҳужжат №", "Айланма", None, "Контрагент"])
    ws.append([None, None, "Дебет", "Кредит", "Номи", "СТИР", "Тўлов мақсади"])
    for i in range(30):
        ws.append(["05.01.2026", str(i), 1000, None, "X MChJ", "305112233", f"Счет-фактура № {i} hisob-faktura invoice"])
    f = tmp_path / "s.xlsx"
    wb.save(f)
    assert parse_document(str(f), "", tmp_path / "o").doc_type == "bank_statement"
