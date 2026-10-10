import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.pipeline.classify import (classify_text, detect_language, detect_period, detect_stir,  # noqa: E402
                                   period_labels)


@pytest.mark.parametrize("text,expected", [
    ("БУХГАЛТЕРСКИЙ БАЛАНС Форма №1 Всего по активу баланса", "form1"),
    ("Buxgalteriya balansi 1-son shakl Balans aktivi bo'yicha jami", "form1"),
    ("ОТЧЕТ О ФИНАНСОВЫХ РЕЗУЛЬТАТАХ Форма №2 Чистая выручка", "form2"),
    ("Moliyaviy natijalar to'g'risidagi hisobot 2-son shakl", "form2"),
    ("ВЫПИСКА по расчетному счету Назначение платежа Входящий остаток", "bank_statement"),
    ("ЗАЯВКА НА ПОЛУЧЕНИЕ КРЕДИТА Запрашиваемая сумма", "loan_application"),
    ("СЧЕТ-ФАКТУРА № 17", "invoice"),
    ("Statement of profit or loss for the year 2025 Revenue Net profit", "form2"),
])
def test_classify(text, expected):
    assert classify_text(text)[0] == expected


def test_unknown_has_reason():
    typ, conf, reason = classify_text("Dear Sir, thank you for your letter of 3 March.")
    assert typ == "unknown" and conf < 0.5 and reason.startswith("Not a recognised")


def test_codes_boost_form_detection():
    assert classify_text("1 2 3", codes_found={"010", "020", "030", "270"})[0] == "unknown"  # 2.5 < 3
    assert classify_text("Отчет о финансовых результатах", codes_found={"010", "270"})[0] == "form2"


@pytest.mark.parametrize("text,lang", [
    ("Бухгалтерский баланс на конец отчетного периода", "ru"),
    ("Ҳисобот даврининг соф фойдаси (зарари) ўтган йил", "uz_cyrl"),
    ("Hisobot davrining sof foydasi bo'yicha jami", "uz_latn"),
    ("Statement of financial position: total assets and liabilities", "en"),
])
def test_language(text, lang):
    assert detect_language(text) == lang


@pytest.mark.parametrize("text,typ,start,end", [
    ("2026 yil 1 yanvardan 30 iyungacha", "form2", date(2026, 1, 1), date(2026, 6, 30)),
    ("за 1-е полугодие 2026 года", "form2", date(2026, 1, 1), date(2026, 6, 30)),
    ("за III квартал 2026 г.", "form2", date(2026, 7, 1), date(2026, 9, 30)),
    ("за 2025 год", "form2", date(2025, 1, 1), date(2025, 12, 31)),
    ("Сформировано: 25.01.2026 10:42 БАЛАНС на 31 декабря 2025 г.", "form1", None, date(2025, 12, 31)),
    ("на 1 января 2026 г.", "form1", None, date(2025, 12, 31)),
    ("с 01.01.2026 по 31.08.2026", "bank_statement", date(2026, 1, 1), date(2026, 8, 31)),
])
def test_period(text, typ, start, end):
    assert detect_period(text, typ) == (start, end)


def test_period_labels():
    assert period_labels("form2", date(2025, 1, 1), date(2025, 12, 31)) == ("FY2025", "FY2024")
    assert period_labels("form2", date(2026, 1, 1), date(2026, 6, 30)) == ("H1-2026", "H1-2025")
    assert period_labels("form2", date(2026, 7, 1), date(2026, 9, 30)) == ("Q3-2026", "Q3-2025")
    assert period_labels("form1", None, date(2026, 6, 30)) == ("2026-06-30", "2025-12-31")


def test_stir():
    assert detect_stir("ООО «Фаровон Савдо»   ИНН 302 447 118") == "302447118"
    assert detect_stir("STIR: 304882571") == "304882571"
    assert detect_stir("phone 998901234567") is None
