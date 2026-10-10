"""Render statutory Form 1 / Form 2 PDFs (text layer) in three layouts and three label languages."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .company import Company
from .spec import F1_SECTIONS, Line, lines, zero_as_dash
from .translit import to_cyrillic

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    for name, f in [("Sans", "IBMPlexSans-Regular.ttf"), ("Sans-Bold", "IBMPlexSans-Bold.ttf"),
                    ("Sans-Medium", "IBMPlexSans-Medium.ttf"), ("Mono", "IBMPlexMono-Regular.ttf"),
                    ("Mono-Bold", "IBMPlexMono-Bold.ttf")]:
        p = FONT_DIR / f
        if not p.exists():  # fallback
            p = Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSansMono.ttf" if "Mono" in name else "DejaVuSans.ttf")
        pdfmetrics.registerFont(TTFont(name, str(p)))
    _registered = True


MONTHS_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
                 "октября", "ноября", "декабря"]
MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr",
             "noyabr", "dekabr"]
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def tr(lang: str, ru: str, uz: str, en: str | None = None) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyrl":
        return to_cyrillic(uz)
    if lang == "en":
        return en or uz
    return uz


def fmt(v: int | float | None, sep: str = "space", neg: str = "paren", dash: bool = True, decimals: int = 0) -> str:
    """sep: space | none | dot ; neg: paren | minus."""
    if v is None:
        return ""
    if v == 0:
        return "-" if dash else "0"
    a = abs(v)
    joiner = {"space": " ", "none": "", "dot": "."}[sep]
    if decimals:
        whole, frac = f"{a:.{decimals}f}".split(".")
        s = f"{int(whole):,}".replace(",", joiner) + ("," if sep == "dot" else ".") + frac
    else:
        s = f"{int(round(a)):,}".replace(",", joiner)
    if v < 0:
        return f"-{s}" if neg == "minus" else f"({s})"
    return s


def period_phrase(lang: str, period: str) -> str:
    kind, _, year = period.partition("-")
    if period.startswith("FY"):
        y = period[2:]
        return tr(lang, f"за {y} год", f"{y} yil uchun", f"for the year {y}")
    if kind == "H1":
        return tr(lang, f"за 1-е полугодие {year} года", f"{year} yil 1 yanvardan 30 iyungacha",
                  f"for January-June {year}")
    if kind.startswith("Q"):
        q = int(kind[1])
        return tr(lang, f"за {ROMAN[q]} квартал {year} г.", f"{year} yil {ROMAN[q]} chorak uchun",
                  f"for Q{q} {year}")
    raise ValueError(period)


def date_phrase(lang: str, d: date) -> str:
    return tr(lang, f"на {d.day} {MONTHS_RU_GEN[d.month - 1]} {d.year} г.",
              f"{d.year} yil {d.day} {MONTHS_UZ[d.month - 1]} holatiga", f"as at {d.isoformat()}")


def column_headers(lang: str, form: str, quarterly: bool) -> tuple[str, str]:
    """(prev header, cur header)."""
    if form == "form1":
        return (tr(lang, "На начало отчетного периода", "Hisobot davri boshiga", "Beginning of period"),
                tr(lang, "На конец отчетного периода", "Hisobot davri oxiriga", "End of period"))
    if quarterly:
        return (tr(lang, "За предыдущий квартал", "Oldingi chorakda", "Previous quarter"),
                tr(lang, "За отчетный квартал (отчетный период)", "Hisobot choragida (hisobot davri)", "Reporting quarter"))
    return (tr(lang, "За соответствующий период прошлого года", "O'tgan yilning shu davrida", "Same period last year"),
            tr(lang, "За отчетный период", "Hisobot davrida", "Reporting period"))


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    out, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= width or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out or [""]


class FormRenderer:
    """Draws one Form 1/2 document; records the page of each line for the truth file."""

    W, H = A4

    def __init__(self, path: Path, form: str, lang: str, layout: str, company: Company, *,
                 title_when: str, quarterly: bool = False, unit: str = "kUZS", submitted: date | None = None,
                 neg_style: str | None = None):
        register_fonts()
        self.path, self.form, self.lang, self.layout = Path(path), form, lang, layout
        self.company, self.title_when, self.quarterly, self.unit = company, title_when, quarterly, unit
        self.submitted = submitted
        self.c = canvas.Canvas(str(self.path), pagesize=A4)
        self.c.setTitle(self._title())
        self.c.setAuthor(company.name)
        self.page = 1
        self.y = 0.0
        self.mono = layout == "typed"
        self.num_style = "none" if layout == "typed" else "space"
        self.neg_style = neg_style or ("minus" if layout == "software_export" else "paren")

    # ------------------------------------------------------------------ text helpers
    def _title(self) -> str:
        if self.form == "form1":
            return tr(self.lang, "БУХГАЛТЕРСКИЙ БАЛАНС", "BUXGALTERIYA BALANSI", "BALANCE SHEET")
        return tr(self.lang, "ОТЧЕТ О ФИНАНСОВЫХ РЕЗУЛЬТАТАХ", "MOLIYAVIY NATIJALAR TO'G'RISIDAGI HISOBOT",
                  "STATEMENT OF FINANCIAL RESULTS")

    def _form_no(self) -> str:
        n = 1 if self.form == "form1" else 2
        return tr(self.lang, f"Форма №{n}", f"{n}-son shakl", f"Form {n}")

    def _unit_text(self) -> str:
        if self.unit == "mUZS":
            return tr(self.lang, "Единица измерения: млн сум", "O'lchov birligi: mln so'm", "Unit: million UZS")
        return tr(self.lang, "Единица измерения: тыс. сум", "O'lchov birligi: ming so'm", "Unit: thousand UZS")

    def font(self, bold=False):
        if self.mono:
            return "Mono-Bold" if bold else "Mono"
        return "Sans-Bold" if bold else "Sans"

    def text(self, x, y, s, size=8.0, bold=False, right=False, center=False, font=None):
        f = font or self.font(bold)
        self.c.setFont(f, size)
        if right:
            self.c.drawRightString(x, y, s)
        elif center:
            self.c.drawCentredString(x, y, s)
        else:
            self.c.drawString(x, y, s)

    # ------------------------------------------------------------------ layout geometry
    def cols(self):
        if self.layout == "mof_grid":
            return dict(code=(40, 72), label=(72, 352), prev=(352, 455), cur=(455, 555), order=("prev", "cur"))
        if self.layout == "software_export":
            return dict(label=(40, 238), code=(240, 268), cur=(270, 410), prev=(412, 555), order=("cur", "prev"))
        return dict(code=(40, 66), label=(66, 360), prev=(360, 455), cur=(460, 555), order=("prev", "cur"))

    # ------------------------------------------------------------------ drawing
    def header(self, first: bool):
        c = self.company
        top = self.H - 40
        if first:
            if self.layout == "mof_grid":
                self.text(555, top, tr(self.lang, "Приложение к НСБУ №15", "15-son BHMS ilovasi", ""), 7, right=True)
                self.text(555, top - 10, self._form_no(), 8, bold=True, right=True)
                self.text(self.W / 2, top - 30, self._title(), 12, bold=True, center=True)
                self.text(self.W / 2, top - 45, self.title_when, 10, center=True)
                y = top - 66
                rows = [
                    (tr(self.lang, "Предприятие, организация", "Korxona, tashkilot", "Entity"), c.name if self.lang != "uz_cyrl" else to_cyrillic(c.name)),
                    (tr(self.lang, "ИНН", "STIR", "TIN"), c.stir),
                    (tr(self.lang, "Вид деятельности", "Faoliyat turi", "Activity"), c.industry),
                    (tr(self.lang, "Адрес", "Manzil", "Address"), c.address if self.lang != "uz_cyrl" else to_cyrillic(c.address)),
                ]
                for lbl, val in rows:
                    self.text(40, y, f"{lbl}:", 8)
                    self.text(170, y, val, 8, bold=True)
                    self.c.line(168, y - 2, 555, y - 2)
                    y -= 13
                self.text(40, y - 2, self._unit_text(), 8)
                self.y = y - 16
            elif self.layout == "software_export":
                nm = to_cyrillic(c.name) if self.lang == "uz_cyrl" else c.name
                self.text(40, top, f"{nm}  ({tr(self.lang, 'ИНН', 'STIR', 'TIN')} {c.stir})", 9, bold=True)
                self.text(40, top - 14, f"{self._title().capitalize()} {self.title_when}", 11, bold=True)
                self.text(40, top - 28, self._unit_text(), 8)
                gen = self.submitted or date(2026, 1, 25)
                self.text(555, top, tr(self.lang, f"Сформировано: {gen:%d.%m.%Y} 10:42", f"Shakllantirildi: {gen:%d.%m.%Y} 10:42", ""), 7, right=True)
                self.text(555, top - 10, self._form_no(), 7, right=True)
                self.y = top - 48
            else:  # typed
                self.text(40, top, self._form_no(), 9)
                self.text(40, top - 16, f"{self._title()}  {self.title_when}", 10, bold=True)
                nm = to_cyrillic(c.name) if self.lang == "uz_cyrl" else c.name
                self.text(40, top - 30, f"{tr(self.lang, 'Организация', 'Tashkilot', 'Entity')}: {nm}   {tr(self.lang, 'ИНН', 'STIR', 'TIN')}: {c.stir}", 8.5)
                self.text(40, top - 42, self._unit_text(), 8.5)
                self.y = top - 62
        else:
            self.y = self.H - 50
        self.table_header()

    def table_header(self):
        g = self.cols()
        prev_h, cur_h = column_headers(self.lang, self.form, self.quarterly)
        heads = {"code": tr(self.lang, "Код стр.", "Satr kodi", "Code"),
                 "label": tr(self.lang, "Наименование показателя", "Ko'rsatkichlar nomi", "Item"),
                 "prev": prev_h, "cur": cur_h}
        size = 7.5
        h = 26
        top = self.y
        for k in ("code", "label", "prev", "cur"):
            x0, x1 = g[k]
            parts = _wrap(heads[k], self.font(True), size, x1 - x0 - 6)
            yy = top - 9
            for p in parts[:3]:
                self.text((x0 + x1) / 2, yy, p, size, bold=True, center=True)
                yy -= 8.5
        if self.layout == "mof_grid":
            self.c.setLineWidth(0.6)
            self.c.rect(40, top - h, 515, h)
            for k in ("label", "prev", "cur"):
                self.c.line(g[k][0], top, g[k][0], top - h)
        else:
            self.c.setLineWidth(0.8)
            self.c.line(40, top - h, 555, top - h)
            if self.layout == "software_export":
                self.c.line(40, top + 2, 555, top + 2)
        self.y = top - h

    def new_page(self):
        self.footer_pageno()
        self.c.showPage()
        self.page += 1
        self.header(first=False)

    def footer_pageno(self):
        self.text(555, 25, tr(self.lang, f"стр. {self.page}", f"{self.page}-bet", f"page {self.page}"), 7, right=True)

    def section(self, title: str):
        for t in title.split("\n"):
            if self.y - 13 < 70:
                self.new_page()
            self.y -= 13
            g = self.cols()
            self.text(g["label"][0] + 3, self.y + 3.5, t, 8, bold=True)
            if self.layout == "mof_grid":
                self.c.setLineWidth(0.4)
                self.c.rect(40, self.y, 515, 13)

    def row(self, ln: Line, label: str, prev_s: str, cur_s: str) -> int:
        g = self.cols()
        size = 7.6
        lab_w = g["label"][1] - g["label"][0] - 6 - ln.indent * 8
        parts = _wrap(label, self.font(ln.total), size, lab_w)
        h = 12.5 + 9 * (len(parts) - 1)
        if self.y - h < 70:
            self.new_page()
        top = self.y
        self.y -= h
        base = top - 9.2
        for i, p in enumerate(parts):
            self.text(g["label"][0] + 3 + ln.indent * 8, base - 9 * i, p, size, bold=ln.total)
        self.text((g["code"][0] + g["code"][1]) / 2, base, ln.code, size, center=True, bold=ln.total)
        self.text(g["prev"][1] - 4, base, prev_s, size, right=True, bold=ln.total)
        self.text(g["cur"][1] - 4, base, cur_s, size, right=True, bold=ln.total)
        if self.layout == "mof_grid":
            self.c.setLineWidth(0.4)
            self.c.rect(40, self.y, 515, h)
            for k in ("label", "prev", "cur"):
                self.c.line(g[k][0], top, g[k][0], self.y)
        elif self.layout == "software_export" and ln.total:
            self.c.setLineWidth(0.3)
            self.c.line(g["label"][0], top, 555, top)
        elif self.layout == "typed":
            # dot leaders between label end and the value column
            end = g["label"][0] + 3 + ln.indent * 8 + pdfmetrics.stringWidth(parts[-1], self.font(ln.total), size) + 4
            if end < g["prev"][0] - 10 and len(parts) == 1:
                self.c.setFont(self.font(), size)
                dots = "." * int((g["prev"][0] - 6 - end) / pdfmetrics.stringWidth(".", self.font(), size))
                self.c.drawString(end, base, dots)
        return self.page

    def footer(self):
        c = self.company
        if self.y < 120:
            self.new_page()
        y = self.y - 30
        sub = self.submitted or date(2026, 1, 25)
        self.text(40, y, f"{tr(self.lang, 'Руководитель', 'Rahbar', 'Director')} ____________  {c.director}", 8.5)
        self.text(300, y, f"{tr(self.lang, 'Главный бухгалтер', 'Bosh hisobchi', 'Chief accountant')} ____________  {c.accountant}", 8.5)
        self.text(40, y - 16, f"{tr(self.lang, 'Дата представления', 'Taqdim etilgan sana', 'Submitted')}: {sub:%d.%m.%Y}", 8.5)
        self.footer_pageno()

    def save(self):
        self.c.save()


def render_form(path: Path, form: str, lang: str, layout: str, company: Company, *, title_when: str,
                cur: dict[str, int | None], prev: dict[str, int | None], quarterly: bool = False,
                unit: str = "kUZS", submitted: date | None = None, label_override: dict[str, str] | None = None,
                drop_codes: set[str] | None = None, row_order: list[str] | None = None,
                blank_prev: set[str] | None = None) -> dict:
    """Write the PDF and return the truth dict for this document."""
    r = FormRenderer(path, form, lang, layout, company, title_when=title_when, quarterly=quarterly,
                     unit=unit, submitted=submitted)
    r.header(first=True)
    divisor = 1000.0 if unit == "mUZS" else 1.0
    decimals = 1 if unit == "mUZS" else 0
    fields: dict[str, dict] = {}
    blanks: list[str] = []
    extra: list[dict] = []
    lns = lines(form)
    if row_order:
        by = {ln.code: ln for ln in lns}
        lns = [by[c] for c in row_order if c in by] + [ln for ln in lns if ln.code not in row_order]
    for ln in lns:
        if drop_codes and ln.code in drop_codes:
            continue
        if form == "form1" and ln.code in F1_SECTIONS:
            ru, uz, en = F1_SECTIONS[ln.code]
            r.section(tr(lang, ru, uz, en))
        dash = zero_as_dash(ln)
        pv = None if (blank_prev and ln.code in blank_prev) else prev.get(ln.code)
        cv = cur.get(ln.code)

        def show(v):
            if v is None:
                return ""
            x = v / divisor if divisor != 1 else v
            return fmt(x, r.num_style, r.neg_style, dash=dash, decimals=decimals)

        ps, cs = show(pv), show(cv)
        label = (label_override or {}).get(ln.code) or ln.label(lang)
        page = r.row(ln, label, ps, cs)
        rec = {"page": page}
        for key, v, s in (("cur", cv, cs), ("prev", pv, ps)):
            if v is None or s in ("", "-"):
                rec[key] = None
                blanks.append(f"{ln.code}.{key}")
            else:
                rec[key] = int(v)
                rec[f"printed_{key}"] = s
        if ln.in_dictionary:
            fields[ln.code] = rec
        else:
            extra.append({"code": ln.code, **rec})
    r.footer()
    r.save()
    order = r.cols()["order"]
    return {"fields": fields, "blank_cells": blanks, "extra_rows": extra, "layout": layout,
            "language": lang, "unit": "kUZS", "printed_unit": unit, "columns_left_to_right": list(order),
            "pages": r.page}
