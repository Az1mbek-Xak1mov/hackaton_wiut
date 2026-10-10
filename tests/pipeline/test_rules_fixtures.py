"""Builders shared by the pipeline-logic tests (no tests here).

Figures follow design/demo-data.json for Farovon Savdo (APP-2026-0931) and Zilola Mebel (L-2025-0417);
line codes follow app/pipeline/dictionary/forms.yaml (finance costs = Form 2 line 170).
"""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.pipeline.compute import new_fact_key  # noqa: E402,F401
from app.pipeline.rules.context import AppContext  # noqa: E402
from app.pipeline.statements.normalise import normalise_statement  # noqa: E402
from app.pipeline.types import FactDraft, ParsedDoc, XlsxSheet  # noqa: E402

FAROVON_STIR = "302447118"
LENDER_STIR = "201234567"


def fact(field: str, value: float, period: str, unit: str = "kUZS", label: str | None = None,
         conf: float = 0.98) -> FactDraft:
    parts = field.split(".")
    code = parts[1] if len(parts) > 1 and parts[1].isdigit() else None
    return FactDraft(field=field, label=label or field, value=float(value), unit=unit, period_label=period,
                     line_code=code, printed=f"{value:,.0f}".replace(",", " "), page_n=1, confidence=conf,
                     key=new_fact_key())


F2 = {
    "FY2025": {"010": 9_842_316, "020": 8_614_900, "030": 1_227_416, "040": 548_600, "170": 140_000, "270": 612_100},
    "H1-2026": {"010": 5_316_400, "020": 4_672_100, "030": 644_300, "040": 296_300, "170": 71_000, "270": 318_000},
}
F1 = {
    "2025-12-31": {"400": 3_988_200, "390": 2_702_500, "140": 1_298_000, "210": 850_000, "600": 1_866_000,
                   "490": 0, "480": 2_122_200, "770": 1_866_000, "780": 3_988_200},
    "2026-06-30": {"400": 4_210_600, "390": 2_870_400, "140": 1_412_800, "210": 910_500, "600": 1_940_200,
                   "490": 0, "480": 2_270_400, "770": 1_940_200, "780": 4_210_600},
}
SLUG = {"010": "net_revenue", "020": "cost_of_sales", "030": "gross_profit", "040": "period_expenses_total",
        "170": "finance_costs_total", "270": "net_profit", "400": "total_assets", "390": "current_assets_total",
        "140": "inventory_total", "210": "receivables_total", "600": "current_liabilities_total",
        "490": "long_term_liabilities_total", "480": "equity_total", "770": "liabilities_total",
        "780": "total_liabilities_equity", "450": "retained_earnings", "610": "trade_payables", "320": "cash_total"}


def stat_facts(f1: dict | None = None, f2: dict | None = None) -> list[FactDraft]:
    out = []
    for p, lines in (f2 if f2 is not None else F2).items():
        for code, v in lines.items():
            out.append(fact(f"form2.{code}.{SLUG.get(code, 'x')}", v, p, label=SLUG.get(code, code).replace("_", " ")))
    for p, lines in (f1 if f1 is not None else F1).items():
        for code, v in lines.items():
            out.append(fact(f"form1.{code}.{SLUG.get(code, 'x')}", v, p, label=SLUG.get(code, code).replace("_", " ")))
    return out


MONTHS_2026 = ["January", "February", "March", "April", "May", "June", "July", "August"]


def farovon_statement_rows(months: int = 8, sales_per_receipt: float = 228_150_000.0, with_balance: bool = False,
                           two_row_header: bool = False, loan: bool = True) -> list[list]:
    rows: list[list] = [
        ["Выписка по расчётному счёту", None, None, None, None, None, None, None, None],
        [f"Клиент: Farovon Savdo MChJ, ИНН {FAROVON_STIR}", None, None, None, None, None, None, None, None],
        ["Входящий остаток на 01.01.2026", None, None, None, None, None, None, 412_300_000.0, None],
    ]
    if two_row_header:
        rows.append(["Дата", "№ док.", "Контрагент", None, None, "Обороты", None, "Назначение платежа"]
                    + (["Остаток"] if with_balance else []))
        rows.append([None, None, "Наименование", "ИНН", "Счёт", "Дебет", "Кредит", None] + ([None] if with_balance else []))
    else:
        rows.append(["Дата", "№ док.", "Наименование контрагента", "ИНН", "Счёт", "Дебет", "Кредит",
                     "Назначение платежа"] + (["Остаток"] if with_balance else []))
    bal = 412_300_000.0
    doc = 100
    for mi in range(months):
        m = mi + 1
        mname = MONTHS_2026[mi]
        events = []
        events.append((date(2026, m, 1), "Toshkent Ombor MChJ", "305000111", 16_000_000.0, 0.0,
                       f"Аренда склада за {mname.lower()} 2026 г., в т.ч. НДС"))
        events.append((date(2026, m, 5), "Farovon Savdo MChJ xodimlari", None, 120_000_000.0, 0.0,
                       f"Перечисление заработной платы за {mname.lower()} 2026 на пластиковые карты сотрудников"))
        for i, (cp, stir) in enumerate([("Korzinka Retail MChJ", "303111222"), ("Makro Savdo MChJ", "304222333"),
                                        ("Havas Food MChJ", "305333444"), ("Baraka Market MChJ", "306444555")]):
            events.append((date(2026, m, 3 + i * 6), cp, stir, 0.0, sales_per_receipt,
                           f"Оплата за товар по договору №{40 + i}/26 от 10.01.2026, в т.ч. НДС 12%"))
        events.append((date(2026, m, 12), "Nestle Uzbekistan MChJ", "207555666", 500_000_000.0, 0.0,
                       "Оплата за продукцию по договору №77/26, в т.ч. НДС 12%"))
        events.append((date(2026, m, 18), "Lactalis Dairy MChJ", "207666777", 230_000_000.0 + mi * 5_000_000, 0.0,
                       "Предоплата за молочную продукцию по счет-фактуре"))
        if loan:
            events.append((date(2026, m, 20), "ATB Hamkorbank", LENDER_STIR, 18_500_000.0, 0.0,
                           "Погашение основного долга и процентов по кредитному договору № 2024-1177 от 14.11.2024"))
        events.append((date(2026, m, 21), "Davlat budjeti", "200000000", 30_000_000.0, 0.0,
                       f"ИНПС и социальный налог за {mname.lower()} 2026"))
        events.append((date(2026, m, 25), "G'aznachilik", "201122919", 45_000_000.0, 0.0,
                       f"Уплата НДС за {mname.lower()} 2026 г."))
        events.append((date(2026, m, 28), "ATB Hamkorbank", LENDER_STIR, 300_000.0, 0.0,
                       "Комиссия банка за обслуживание счета"))
        for d, cp, stir, debit, credit, purpose in sorted(events, key=lambda e: e[0]):
            doc += 1
            bal += credit - debit
            row = [d.strftime("%d.%m.%Y"), str(doc), cp, stir, "20208000" + "0" * 11 + str(doc % 10),
                   debit or None, credit or None, purpose]
            if two_row_header:
                row = [d.strftime("%d.%m.%Y"), str(doc), cp, stir, "20208000" + "0" * 11 + str(doc % 10),
                       debit or None, credit or None, purpose]
            if with_balance:
                row.append(bal)
            rows.append(row)
    rows.append(["Итого обороты", None, None, None, None, None, None, None])
    rows.append(["Исходящий остаток", None, None, None, None, None, None, bal])
    return rows


def farovon_statement_doc(**kw) -> ParsedDoc:
    return ParsedDoc(kind="xlsx", doc_type="bank_statement",
                     sheets=[XlsxSheet(name="Выписка", rows=farovon_statement_rows(**kw))])


FAROVON_DOCS = [
    {"uuid": "d1", "filename": "Ariza_FarovonSavdo.pdf", "doc_type": "loan_application", "stir": FAROVON_STIR,
     "sha256": "a1"},
    {"uuid": "d2", "filename": "Balans_2025.pdf", "doc_type": "form1", "period_start": "2025-01-01",
     "period_end": "2025-12-31", "stir": FAROVON_STIR, "sha256": "a2"},
    {"uuid": "d3", "filename": "Balans_1H2026.pdf", "doc_type": "form1", "period_start": "2026-01-01",
     "period_end": "2026-06-30", "stir": FAROVON_STIR, "sha256": "a3"},
    {"uuid": "d4", "filename": "Forma2_2025.pdf", "doc_type": "form2", "period_start": "2025-01-01",
     "period_end": "2025-12-31", "stir": FAROVON_STIR, "sha256": "a4"},
    {"uuid": "d5", "filename": "Forma2_1H2026.pdf", "doc_type": "form2", "period_start": "2026-01-01",
     "period_end": "2026-06-30", "stir": FAROVON_STIR, "sha256": "a5"},
    {"uuid": "d6", "filename": "vypiska_2026.xlsx", "doc_type": "bank_statement", "period_start": "2026-01-01",
     "period_end": "2026-08-31", "stir": FAROVON_STIR, "sha256": "a6"},
]

FAROVON_APP = {
    "requested_amount": 850_000.0, "term_months": 24, "rate_pct": 22.0, "received_on": "2026-10-06",
    "borrower_stir": FAROVON_STIR, "declared_revenue_fy": 10_400_000.0, "declared_revenue_year": 2025,
    "declared_debts": [], "declared_debts_total": 0.0,
}


def farovon_ctx(*, f1=None, f2=None, docs=None, app=None, statement_kw=None, extra_facts=None) -> AppContext:
    sdoc = farovon_statement_doc(**(statement_kw or {}))
    txns, sfacts, recurring = normalise_statement(sdoc, FAROVON_STIR)
    facts = stat_facts(f1, f2) + sfacts + list(extra_facts or [])
    return AppContext(facts=facts, transactions=txns, documents=list(docs if docs is not None else FAROVON_DOCS),
                      application=dict(app if app is not None else FAROVON_APP), recurring=recurring)
