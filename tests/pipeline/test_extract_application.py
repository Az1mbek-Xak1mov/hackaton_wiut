import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.pipeline.extract_application import extract_application  # noqa: E402
from app.pipeline.parse import parse_document  # noqa: E402

from test_extract_fixtures import FONT  # noqa: E402


def _app_pdf(path: Path, lines: list[str]) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 12)
    c.drawString(40, 800, "ЗАЯВКА НА ПОЛУЧЕНИЕ КРЕДИТА / KREDIT OLISH UCHUN ARIZA")
    c.setFont(FONT, 9.5)
    y = 770
    for ln in lines:
        c.drawString(40, y, ln)
        y -= 16
    c.save()
    return path


def test_application_fields(tmp_path):
    pdf = _app_pdf(tmp_path / "a.pdf", [
        "Заявитель / Arizachi / Applicant:   Farovon Savdo MChJ",
        "ИНН / STIR:   302447118",
        "Запрашиваемая сумма / So'ralayotgan summa / Requested amount:   850 000 000 сум",
        "Срок кредита / Kredit muddati / Loan term:   24 мес.",
        "Процентная ставка / Foiz stavkasi / Interest rate:   24,0%",
        "Цель кредита / Kredit maqsadi / Purpose:   Пополнение оборотных средств",
        "Годовая выручка за 2025 г., млн сум / Yillik tushum 2025, mln so'm:   10 400",
        "Действующие кредиты и займы / Mavjud kreditlar va qarzlar / Existing loans and debts:   нет / yo'q",
    ])
    doc = parse_document(str(pdf), "", tmp_path / "out")
    assert doc.doc_type == "loan_application"
    by = {f.field: f for f in extract_application(doc)}
    assert by["application.requested_amount"].value == pytest.approx(850_000)
    assert by["application.term_months"].value == 24
    assert by["application.rate_pct"].value == pytest.approx(24.0)
    rev = by["application.declared_revenue_fy"]
    assert rev.value == pytest.approx(10_400_000) and rev.period_label == "FY2025"
    assert by["application.declared_debts_total"].value == 0 and "none" in by["application.declared_debts_total"].note
    assert by["application.purpose"].note == "Пополнение оборотных средств"
    assert by["application.stir"].note == "302447118"
    assert all(f.page_n == 1 and f.bbox for f in by.values())


def test_declared_debts_amount_in_thousands(tmp_path):
    pdf = _app_pdf(tmp_path / "a.pdf", [
        "Mavjud kreditlar va qarzlar / Действующие кредиты и займы:   148 000 ming so'm",
        "So'ralayotgan summa / Запрашиваемая сумма:   850,0 mln so'm",
    ])
    by = {f.field: f for f in extract_application(parse_document(str(pdf), "", tmp_path / "out"))}
    assert by["application.declared_debts_total"].value == pytest.approx(148_000)
    assert by["application.requested_amount"].value == pytest.approx(850_000)
