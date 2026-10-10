"""Loan application and tax declaration PDFs (label: value lines, trilingual labels)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from .company import Company
from .pdf_forms import _wrap, fmt, register_fonts
from .translit import to_cyrillic

# label sets in the order uz_latn, ru, en (first labels of app/pipeline/dictionary/application.yaml)
APP_LABELS = {
    "applicant_name": ("Arizachi", "Заявитель", "Applicant"),
    "stir": ("STIR", "ИНН", "TIN"),
    "address": ("Yuridik manzil", "Юридический адрес", "Registered address"),
    "director": ("Rahbar", "Руководитель", "Director"),
    "employees": ("Xodimlar soni", "Численность работников", "Employees"),
    "since": ("Faoliyat boshlangan yil", "Год начала деятельности", "Operating since"),
    "industry": ("Faoliyat turi", "Вид деятельности", "Activity"),
    "requested_amount": ("So'ralayotgan summa", "Запрашиваемая сумма", "Requested amount"),
    "term_months": ("Kredit muddati", "Срок кредита", "Loan term"),
    "rate_pct": ("Foiz stavkasi", "Процентная ставка", "Interest rate"),
    "repayment": ("To'lov tartibi", "Порядок погашения", "Repayment"),
    "purpose": ("Kredit maqsadi", "Цель кредита", "Purpose"),
    "collateral": ("Ta'minot", "Обеспечение", "Collateral"),
    "declared_revenue_fy": ("Yillik tushum", "Годовая выручка", "Annual revenue"),
    "declared_net_profit": ("Sof foyda", "Чистая прибыль", "Net profit"),
    "declared_debts_total": ("Mavjud kreditlar va qarzlar", "Действующие кредиты и займы", "Existing loans and debts"),
}


def _label(key: str, lang: str, with_en: bool = True) -> str:
    uz, ru, en = APP_LABELS[key]
    if lang == "uz_cyrl":
        uz = to_cyrillic(uz)
    first, second = (ru, uz) if lang == "ru" else (uz, ru)
    return f"{first} / {second}" + (f" / {en}" if with_en else "")


class TextDoc:
    def __init__(self, path: Path, title: str, author: str):
        register_fonts()
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle(title)
        self.c.setAuthor(author)
        self.W, self.H = A4
        self.y = self.H - 50
        self.page = 1

    def ensure(self, h: float):
        if self.y - h < 60:
            self.c.drawRightString(555, 25, f"{self.page}")
            self.c.showPage()
            self.page += 1
            self.y = self.H - 50

    def line(self, s: str, size: float = 9.5, bold: bool = False, center: bool = False, gap: float = 4,
             font: str | None = None) -> int:
        f = font or ("Sans-Bold" if bold else "Sans")
        for part in _wrap(s, f, size, 515):
            self.ensure(size + gap)
            self.y -= size + gap
            self.c.setFont(f, size)
            if center:
                self.c.drawCentredString(self.W / 2, self.y, part)
            else:
                self.c.drawString(40, self.y, part)
        return self.page

    def kv(self, label: str, value: str, size: float = 9.5) -> int:
        """'label: value' on one line (value right after the colon, as the dictionary expects)."""
        s = f"{label}:   {value}"
        width = pdfmetrics.stringWidth(s, "Sans", size)
        if width > 515:
            return self.line(s, size)
        self.ensure(size + 6)
        self.y -= size + 6
        self.c.setFont("Sans", size)
        self.c.drawString(40, self.y, f"{label}:")
        lw = pdfmetrics.stringWidth(f"{label}:   ", "Sans", size)
        self.c.setFont("Sans-Bold", size)
        self.c.drawString(40 + lw, self.y, value)
        return self.page

    def rule(self):
        self.y -= 6
        self.c.setLineWidth(0.5)
        self.c.line(40, self.y, 555, self.y)

    def save(self):
        self.c.setFont("Sans", 7)
        self.c.drawRightString(555, 25, f"{self.page}")
        self.c.save()


def money_text(kuzs: int, style: str, lang: str) -> str:
    som = {"ru": "сум", "uz_latn": "so'm", "uz_cyrl": "сўм"}[lang]
    if style == "uzs":
        return f"{fmt(kuzs * 1000, dash=False)} {som}"
    if style == "kuzs":
        return f"{fmt(kuzs, dash=False)} {'тыс. сум' if lang == 'ru' else ('ming so' + chr(39) + 'm' if lang == 'uz_latn' else 'минг сўм')}"
    v = kuzs / 1000
    s = f"{v:,.1f}".replace(",", " ").replace(".", ",")
    return f"{s} {'млн сум' if lang == 'ru' else ('mln so' + chr(39) + 'm' if lang == 'uz_latn' else 'млн сўм')}"


def render_application(path: Path, company: Company, lang: str, *, requested_kuzs: int, term_months: int,
                       rate_pct: float, purpose: str, collateral: str, declared_revenue_kuzs: int,
                       declared_np_kuzs: int, fy: int, debts: list[dict], received: date,
                       amount_style: str = "uzs", revenue_in_mln_label: bool = True,
                       stir_override: str | None = None) -> dict:
    """debts: [{"lender", "contract", "balance_kuzs", "monthly_kuzs"}]; empty list -> 'none'."""
    t = TextDoc(path, "Loan application", company.name)
    L = (lambda s: to_cyrillic(s)) if lang == "uz_cyrl" else (lambda s: s)
    pages: dict[str, int] = {}
    t.line(L("KREDIT OLISH UCHUN ARIZA") + " / ЗАЯВКА НА ПОЛУЧЕНИЕ КРЕДИТА / LOAN APPLICATION", 13, bold=True, center=True)
    t.line(f"№ {received:%Y}-{int(received.toordinal()) % 9000 + 1000}   {received:%d.%m.%Y}", 9, center=True)
    t.line(L("Kichik biznesni kreditlash bo'limiga") + " / В отдел кредитования малого бизнеса", 9, center=True)
    t.rule()
    t.line(L("1-bo'lim. Arizachi haqida ma'lumot") + " / Раздел 1. Сведения о заявителе", 10.5, bold=True, gap=10)
    name = to_cyrillic(company.name) if lang == "uz_cyrl" else company.name
    stir = stir_override or company.stir
    pages["applicant_name"] = t.kv(_label("applicant_name", lang), name)
    pages["stir"] = t.kv(_label("stir", lang, False), stir)
    t.kv(_label("address", lang, False), L(company.address))
    t.kv(_label("director", lang, False), company.director)
    t.kv(_label("industry", lang, False), company.industry)
    t.kv(_label("employees", lang, False), str(company.employees))
    t.kv(_label("since", lang, False), str(company.since))
    t.line(L("2-bo'lim. So'ralayotgan kredit") + " / Раздел 2. Параметры запрашиваемого кредита", 10.5, bold=True, gap=10)
    pages["requested_amount"] = t.kv(_label("requested_amount", lang), money_text(requested_kuzs, amount_style, lang))
    oy = {"ru": "мес.", "uz_latn": "oy", "uz_cyrl": "ой"}[lang]
    pages["term_months"] = t.kv(_label("term_months", lang), f"{term_months} {oy}")
    pages["rate_pct"] = t.kv(_label("rate_pct", lang), f"{rate_pct:.1f}%".replace(".", ","))
    t.kv(_label("repayment", lang, False), L("annuitet") + " / аннуитет")
    pages["purpose"] = t.kv(_label("purpose", lang), purpose)
    pages["collateral"] = t.kv(_label("collateral", lang), collateral)
    t.line(L("5-bo'lim. Arizachining moliyaviy ko'rsatkichlari") + " / Раздел 5. Финансовые показатели заявителя", 10.5, bold=True, gap=10)
    if revenue_in_mln_label:
        uz, ru, _en = APP_LABELS["declared_revenue_fy"]
        lab = f"{ru} за {fy} г., млн сум / {L(uz)} {fy}, {L('mln so' + chr(39) + 'm')}"
        pages["declared_revenue_fy"] = t.kv(lab, fmt(round(declared_revenue_kuzs / 1000), dash=False))
        uz, ru, _en = APP_LABELS["declared_net_profit"]
        t.kv(f"{ru} за {fy} г., млн сум / {L(uz)} {fy}, {L('mln so' + chr(39) + 'm')}", fmt(round(declared_np_kuzs / 1000), dash=False))
    else:
        pages["declared_revenue_fy"] = t.kv(_label("declared_revenue_fy", lang) + f" ({fy})", money_text(declared_revenue_kuzs, "uzs", lang))
    if debts:
        total = sum(d["balance_kuzs"] for d in debts)
        pages["declared_debts_total"] = t.kv(_label("declared_debts_total", lang), money_text(total, "uzs", lang))
        for d in debts:
            t.line(f"    — {d['lender']}, " + L("shartnoma") + f" / договор № {d['contract']}: "
                   + L("qoldiq") + f" / остаток {money_text(d['balance_kuzs'], 'uzs', lang)}, "
                   + L("oylik to'lov") + f" / ежемесячный платеж {money_text(d['monthly_kuzs'], 'uzs', lang)}", 9)
    else:
        pages["declared_debts_total"] = t.kv(_label("declared_debts_total", lang), {"ru": "нет / yo'q", "uz_latn": "yo'q / нет", "uz_cyrl": "йўқ / нет"}[lang])
    t.rule()
    t.line(L("Ushbu arizada keltirilgan ma'lumotlarning to'g'riligini tasdiqlayman.") + " / Достоверность сведений подтверждаю.", 9, gap=12)
    t.line(f"{L('Rahbar')} / Руководитель ____________ {company.director}        {received:%d.%m.%Y}", 9.5, gap=14)
    t.save()
    return {
        "fields": {
            "applicant_name": {"value": company.name, "page": pages["applicant_name"]},
            "stir": {"value": stir, "page": pages["stir"]},
            "requested_amount": {"value": requested_kuzs, "unit": "kUZS", "page": pages["requested_amount"]},
            "term_months": {"value": term_months, "page": pages["term_months"]},
            "rate_pct": {"value": rate_pct, "page": pages["rate_pct"]},
            "purpose": {"value": purpose, "page": pages["purpose"]},
            "collateral": {"value": collateral, "page": pages["collateral"]},
            "declared_revenue_fy": {"value": int(round(declared_revenue_kuzs / 1000) * 1000) if revenue_in_mln_label else declared_revenue_kuzs,
                                    "unit": "kUZS", "fy": fy, "page": pages["declared_revenue_fy"]},
            "declared_debts_total": {"value": sum(d["balance_kuzs"] for d in debts), "unit": "kUZS",
                                     "contracts": [d["contract"] for d in debts], "page": pages["declared_debts_total"]},
        },
        "language": lang, "amount_style": amount_style, "pages": t.page,
    }


def render_tax_declaration(path: Path, company: Company, lang: str, *, period_label: str, year: int, quarter: int,
                           income_kuzs: int, expenses_kuzs: int, submitted: date) -> dict:
    t = TextDoc(path, "Tax declaration", company.name)
    L = (lambda s: to_cyrillic(s)) if lang == "uz_cyrl" else (lambda s: s)
    t.line(L("FOYDA SOLIG'I BO'YICHA SOLIQ HISOBOTI") + " / НАЛОГОВАЯ ДЕКЛАРАЦИЯ ПО НАЛОГУ НА ПРИБЫЛЬ", 12, bold=True, center=True)
    t.line(L(f"{year} yil {quarter}-chorak") + f" / за {quarter} квартал {year} г. (нарастающим итогом)", 10, center=True)
    t.rule()
    t.kv(L("Soliq to'lovchi") + " / Налогоплательщик", to_cyrillic(company.name) if lang == "uz_cyrl" else company.name)
    t.kv("STIR / ИНН", company.stir)
    t.kv(L("Hisobot turi") + " / Тип отчета", L("dastlabki") + " / первичный")
    t.line(L("Ko'rsatkichlar (ming so'm)") + " / Показатели (тыс. сум)", 10.5, bold=True, gap=10)
    profit = income_kuzs - expenses_kuzs
    tax = int(round(max(profit, 0) * 0.15))
    rows = [("010", L("Jami daromad") + " / Совокупный доход", income_kuzs),
            ("020", L("Chegiriladigan xarajatlar") + " / Вычитаемые расходы", expenses_kuzs),
            ("030", L("Soliq solinadigan foyda") + " / Налогооблагаемая прибыль", profit),
            ("040", L("Soliq stavkasi, %") + " / Ставка налога, %", 15),
            ("050", L("Hisoblangan soliq summasi") + " / Исчисленная сумма налога", tax)]
    for code, lab, v in rows:
        t.kv(f"{code}  {lab}", fmt(v, dash=False))
    t.rule()
    t.line(f"{L('Rahbar')} / Руководитель ____________ {company.director}", 9.5, gap=14)
    t.line(f"{L('Topshirilgan sana')} / Дата представления: {submitted:%d.%m.%Y}", 9.5)
    t.save()
    return {"period": period_label, "income": income_kuzs, "expenses": expenses_kuzs, "tax": tax, "language": lang,
            "pages": t.page}
