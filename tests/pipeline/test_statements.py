from datetime import date

from test_rules_fixtures import FAROVON_STIR, LENDER_STIR, farovon_statement_doc

from app.pipeline.statements import Categoriser, normalise_statement, statement_summary
from app.pipeline.statements.categorise import rule_category
from app.pipeline.statements.normalise import detect_header
from app.pipeline.statements.text import find_contract, parse_amount, parse_date, strip_vat_mentions
from app.pipeline.types import ParsedDoc, XlsxSheet


def _rules_only():
    return Categoriser(use_model=False)


def test_header_single_row():
    doc = farovon_statement_doc()
    h = detect_header(doc.sheets[0])
    assert h is not None and h.rows_used == 1
    assert {"date", "debit", "credit", "purpose", "counterparty", "stir"} <= set(h.columns)


def test_header_two_rows():
    doc = farovon_statement_doc(two_row_header=True)
    h = detect_header(doc.sheets[0])
    assert h is not None and h.rows_used == 2
    assert h.columns["debit"] == 5 and h.columns["credit"] == 6 and h.columns["stir"] == 3


def test_transactions_and_categories():
    doc = farovon_statement_doc()
    txns, facts, recurring = normalise_statement(doc, FAROVON_STIR, _rules_only())
    assert len(txns) == 8 * 12
    cats = {t.category for t in txns}
    assert {"sales_receipt", "supplier_payment", "salary", "payroll_tax", "tax", "loan_repayment",
            "rent_utilities", "bank_fee"} <= cats
    assert all(t.category != "other" for t in txns)
    loan = [t for t in txns if t.category == "loan_repayment"]
    assert len(loan) == 8 and all(t.amount == -18_500_000.0 for t in loan)
    assert all(t.counterparty_stir == LENDER_STIR for t in loan)
    assert doc.period_start == date(2026, 1, 1) and doc.period_end == date(2026, 8, 28)
    assert doc.stir == FAROVON_STIR


def test_two_row_header_parses_same_transactions():
    a = normalise_statement(farovon_statement_doc(), FAROVON_STIR, _rules_only())[0]
    b = normalise_statement(farovon_statement_doc(two_row_header=True), FAROVON_STIR, _rules_only())[0]
    assert [(t.booked_on, t.amount, t.category) for t in a] == [(t.booked_on, t.amount, t.category) for t in b]


def test_recurring_loan_detected_with_contract():
    txns, facts, recurring = normalise_statement(farovon_statement_doc(), FAROVON_STIR, _rules_only())
    loans = [g for g in recurring if g["category"] == "loan_repayment"]
    assert len(loans) == 1
    g = loans[0]
    assert g["group"] == "loan:2024-1177" and g["contract_no"] == "2024-1177"
    assert g["contract_date"] == "14.11.2024"
    assert g["count"] == 8 and g["day_of_month"] == 20 and g["amount"] == 18_500.0
    assert g["next_due"] == date(2026, 9, 20)
    assert all(t.recurring_group == "loan:2024-1177" for t in txns if t.category == "loan_repayment")
    by_field = {f.field: f for f in facts}
    m = by_field["statement.loan_repayment.monthly.loan:2024-1177"]
    assert m.value == 18_500.0 and m.unit == "kUZS" and "day 20" in m.label
    assert by_field["statement.loan_repayment.count.loan:2024-1177"].value == 8
    assert by_field["statement.loan_repayment.total.loan:2024-1177"].value == 148_000.0
    assert m.key == g["fact_keys"]["monthly"]
    groups = {g["group"] for g in recurring}
    assert {"salary", "payroll:social", "tax:vat", "rent"} <= groups


def test_aggregates_monthly_and_average():
    txns, facts, _ = normalise_statement(farovon_statement_doc(), FAROVON_STIR, _rules_only())
    by_field = {f.field: f for f in facts}
    assert by_field["statement.inflow.sales_receipt.2026-03"].value == 912_600.0
    avg = by_field["statement.avg_monthly_inflow"]
    assert avg.value == 912_600.0 and avg.period_label == "2026-01..2026-08"
    assert avg.page_n is None and avg.passage.startswith("rows ")
    assert by_field["statement.outflow.salary.2026-02"].value == 120_000.0
    assert all(f.key and f.key.startswith("f_") for f in facts)


def test_month_end_balance_from_opening_and_from_column():
    _, f_open, _ = normalise_statement(farovon_statement_doc(), FAROVON_STIR, _rules_only())
    _, f_col, _ = normalise_statement(farovon_statement_doc(with_balance=True), FAROVON_STIR, _rules_only())
    a = {f.field: f for f in f_open}["statement.balance_end.2026-03"]
    b = {f.field: f for f in f_col}["statement.balance_end.2026-03"]
    assert abs(a.value - b.value) < 0.01
    assert a.period_label == "2026-03-31"


def test_uncategorised_and_summary():
    rows = [["Дата", "Дебет", "Кредит", "Назначение платежа", "Контрагент"],
            ["05.01.2026", None, 1000000, "xyz 123", "Alpha"],
            ["06.01.2026", 50000, None, "Погашение кредита по договору № 55", "Bank"]]
    doc = ParsedDoc(kind="xlsx", sheets=[XlsxSheet("s", rows)])
    txns, facts, rec = normalise_statement(doc, None, _rules_only())
    assert [t.category for t in txns] == ["other", "loan_repayment"]
    s = statement_summary(txns, rec)
    assert s["transactions"] == 2 and s["uncategorised"] == 1


def test_foreign_currency_rows_excluded():
    rows = [["Дата", "Валюта", "Дебет", "Кредит", "Назначение платежа"],
            ["05.01.2026", "UZS", None, 1000000, "Оплата за товар"],
            ["06.01.2026", "USD", None, 500, "Оплата за товар"]]
    doc = ParsedDoc(kind="xlsx", sheets=[XlsxSheet("s", rows)])
    txns, _, _ = normalise_statement(doc, None, _rules_only())
    assert len(txns) == 1


def test_rule_categories_uzbek_and_salary_cards():
    assert rule_category("2024-1177-sonli kredit shartnomasi bo'yicha asosiy qarzni to'lash", "", -1) == "loan_repayment"
    assert rule_category("Kredit foizlarini to'lash", "", -1) == "loan_repayment"
    assert rule_category("МФО 'Ishonch' погаш. займа по дог. 77/24", "", -1) == "loan_repayment"
    assert rule_category("Перечисление на пластиковые карточки сотрудников за сентябрь", "", -1) == "salary"
    assert rule_category("Oylik ish haqi sentyabr", "", -1) == "salary"
    assert rule_category("Foyda solig'i to'lovi", "", -1) == "tax"
    assert rule_category("Оплата за товар, в т.ч. НДС 12% 107 142,86", "", 1) == "sales_receipt"
    assert rule_category("Оплата за товар, в т.ч. НДС 12% 107 142,86", "", -1) == "supplier_payment"
    assert rule_category("Elektron hisob-faktura bo'yicha to'lov", "", -1) == "supplier_payment"
    assert rule_category("Hududiy elektr tarmoqlari: elektr energiya uchun", "", -1) == "rent_utilities"
    assert rule_category("Kredit mablag'lari ajratildi", "", 1) == "loan_disbursement"


def test_own_transfer_by_stir():
    cat = Categoriser(use_model=False)
    assert cat.categorise("Перевод", "Farovon", -100, FAROVON_STIR, FAROVON_STIR)[0] == "own_transfer"


def test_text_helpers():
    assert find_contract("по кредитному договору № 2024-1177 от 14.11.2024") == ("2024-1177", "14.11.2024")
    assert find_contract("Оплата по договору от 14.11.2024") == (None, None)
    assert parse_amount("1 234 567,89") == 1234567.89
    assert parse_amount("(1 234)") == -1234.0
    assert parse_amount("—") is None
    assert parse_date(46027) == date(2026, 1, 5)
    assert "ндс" not in strip_vat_mentions("оплата за товар, в т.ч. ндс 12% 100,00")
