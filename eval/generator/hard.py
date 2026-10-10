"""Hand-made hard cases H01-H20 (data/hard/<id>/ + truth.json). Test-only: never used for tuning."""
from __future__ import annotations

import io
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import img2pdf
import numpy as np
from openpyxl import Workbook
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

from .company import make_company
from .docs_pdf import TextDoc
from .finmodel import make_fin
from .heroes import FAROVON, FAR_F2, NAVROZ, invoice_photo
from .noise import degrade, render_pages, scan_pdf
from .pdf_forms import date_phrase, fmt, period_phrase, register_fonts, render_form
from .samples import english_ifrs
from .spec import lines
from .statement import Party, Txn, assign_recurring, make_ctx, month_txns, write_statement
from .totals import f2_totals

ROOT = Path(__file__).resolve().parents[2]


def _w(d: Path, truth: dict) -> None:
    (d / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def build_hard(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = np.random.default_rng(31337)
    co = make_company(rng, "plastics", name="Sharq Polimer MChJ", stir="306118204")
    fin = make_fin(rng, co)
    fy, fyp = fin.f2["FY2025"], fin.f2["FY2024"]
    f1c, f1p = fin.f1["2025-12-31"], fin.f1["2024-12-31"]
    when_f2 = period_phrase("ru", "FY2025")
    cases = []

    def case(cid: str, title: str, expected: str) -> Path:
        d = out / cid
        d.mkdir()
        cases.append({"id": cid, "case": title, "expected": expected})
        return d

    def base_f2(d: Path, name="form2_FY2025.pdf") -> dict:
        return render_form(d / name, "form2", "ru", "mof_grid", co, title_when=when_f2, cur=fy, prev=fyp,
                           submitted=date(2026, 1, 25))

    # H01 rotated page
    d = case("H01", "page rotated 90°", "OSD fixes rotation; fields extracted")
    t = base_f2(d, "tmp.pdf")
    pg = render_pages(d / "tmp.pdf", 200)[0].rotate(90, expand=True)
    buf = io.BytesIO(); degrade(pg, rng, skew=0.0, blur=0.3, jpeg_q=70).save(buf, "JPEG", quality=70, dpi=(200, 200))
    (d / "form2_rotated.pdf").write_bytes(img2pdf.convert([buf.getvalue()], layout_fun=img2pdf.get_fixed_dpi_layout_fun((200, 200))))
    (d / "tmp.pdf").unlink()
    _w(d, {**cases[-1], "documents": [{"file": "form2_rotated.pdf", "doc_type": "form2", "rotation_deg": 90, **t}]})

    # H02 stamp over value cells
    d = case("H02", "official stamp over 2 value cells", "low confidence -> clarification, never a wrong value")
    t = base_f2(d)
    # value column 'cur' x ~ 455-555pt, rows 010/020 near the table top; 200 dpi -> px = pt * 200/72
    scan_pdf(d / "form2_FY2025.pdf", d / "form2_FY2025.pdf", rng, dpi=200, skew=0.3, blur=0.3, jpeg_q=70,
             stamp="SHARQ POLIMER MChJ", stamp_xy=(int(505 * 200 / 72), int(214 * 200 / 72)))
    _w(d, {**cases[-1], "documents": [{"file": "form2_FY2025.pdf", "doc_type": "form2", **t,
                                       "obscured_cells_approx": ["010.cur", "020.cur", "030.cur"]}]})

    # H03 negatives: parentheses and minus mixed (a loss year)
    d = case("H03", "negatives in parentheses and with '-' mixed", "correct signs on every negative line")
    loss = f2_totals({"010": 2_104_330, "020": 1_788_610, "050": 160_400, "060": 248_900, "070": 30_100, "090": 4_200,
                      "130": 0, "180": 61_700, "250": 0})
    lossp = f2_totals({"010": 2_390_100, "020": 1_910_000, "050": 151_000, "060": 231_400, "070": 27_800, "180": 55_200,
                       "250": 2_000})
    t = render_form(d / "form2_loss.pdf", "form2", "ru", "mof_grid", co, title_when=when_f2, cur=loss, prev=lossp,
                    neg_minus_codes={"220", "240"})
    _w(d, {**cases[-1], "documents": [{"file": "form2_loss.pdf", "doc_type": "form2", **t,
                                       "printed_negative_styles": {"100": "paren", "220": "minus", "240": "minus", "270": "paren"}}]})

    # H04 dot thousands
    d = case("H04", "dot thousands separators (9.842.316)", "parsed as integers")
    t = render_form(d / "form2_dots.pdf", "form2", "ru", "software_export", co, title_when=when_f2, cur=fy, prev=fyp, sep="dot")
    _w(d, {**cases[-1], "documents": [{"file": "form2_dots.pdf", "doc_type": "form2", **t}]})

    # H05 units in mln
    d = case("H05", "units in mln UZS instead of thousands", "unit detected from the header; values x1000 into kUZS")
    t = render_form(d / "form2_mln.pdf", "form2", "ru", "mof_grid", co, title_when=when_f2, cur=fy, prev=fyp, unit="mUZS")
    _w(d, {**cases[-1], "tolerance_kuzs": 50, "documents": [{"file": "form2_mln.pdf", "doc_type": "form2", **t}]})

    # H06 prior column blank
    d = case("H06", "prior-year column blank", "prev missing with note 'cell blank'; no invented prior values")
    codes = {ln.code for ln in lines("form2")}
    t = render_form(d / "form2_noprev.pdf", "form2", "uz_latn", "mof_grid", co, title_when=period_phrase("uz_latn", "FY2025"),
                    cur=fy, prev=fyp, blank_prev=codes)
    _w(d, {**cases[-1], "documents": [{"file": "form2_noprev.pdf", "doc_type": "form2", **t}]})

    # H07 rows out of order + 2 unofficial rows
    d = case("H07", "rows out of order + 2 unofficial extra rows", "codes mapped regardless of order; extra rows unmapped")
    order = [ln.code for ln in lines("form2")]
    rng.shuffle(order)
    t = render_form(d / "form2_shuffled.pdf", "form2", "ru", "software_export", co, title_when=when_f2, cur=fy, prev=fyp,
                    row_order=order, extra_lines={"010": [("", "в т.ч. экспортная выручка", int(fy["010"] * 0.18), int(fyp["010"] * 0.15))],
                                                  "270": [("", "Справочно: среднесписочная численность, чел.", 61, 58)]})
    _w(d, {**cases[-1], "documents": [{"file": "form2_shuffled.pdf", "doc_type": "form2", "row_order": order, **t}]})

    # H08 apostrophe variants + typo (uz_latn)
    d = case("H08", "label typos and apostrophe variants o‘ oʻ o'", "fuzzy label match still maps every line")
    ov = {}
    for i, ln in enumerate(lines("form2")):
        lab = ln.uz.replace("'", ["‘", "ʻ", "’"][i % 3])
        if i % 4 == 0 and len(lab) > 10:
            lab = lab[:5] + lab[6:]  # drop one letter
        ov[ln.code] = lab
    t = render_form(d / "form2_typos.pdf", "form2", "uz_latn", "typed", co, title_when=period_phrase("uz_latn", "FY2025"),
                    cur=fy, prev=fyp, label_override=ov)
    _w(d, {**cases[-1], "documents": [{"file": "form2_typos.pdf", "doc_type": "form2", **t}]})

    # H09 homoglyphs
    d = case("H09", "mixed Cyrillic/Latin homoglyphs in labels", "homoglyph fold + match")
    swap = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y"})
    ov = {ln.code: (ln.ru.translate(swap) if i % 2 == 0 else ln.ru) for i, ln in enumerate(lines("form2"))}
    t = render_form(d / "form2_homoglyphs.pdf", "form2", "ru", "mof_grid", co, title_when=when_f2, cur=fy, prev=fyp, label_override=ov)
    _w(d, {**cases[-1], "documents": [{"file": "form2_homoglyphs.pdf", "doc_type": "form2", **t}]})

    # H10 Form 1 over 2 pages
    d = case("H10", "Form 1 split over 2 pages", "continuous extraction across pages")
    t = render_form(d / "form1_2pages.pdf", "form1", "ru", "mof_grid", co, title_when=date_phrase("ru", date(2025, 12, 31)), cur=f1c, prev=f1p)
    assert t["pages"] == 2
    _w(d, {**cases[-1], "documents": [{"file": "form1_2pages.pdf", "doc_type": "form1", **t}]})

    # H11 statement with USD rows (extra currency column)
    d = case("H11", "statement with USD rows", "USD rows excluded from UZS aggregates, counted and shown")
    wb = Workbook(); ws = wb.active
    ws.append([co.bank]); ws.append([f"ВЫПИСКА ПО СЧЕТУ № {co.account}"]); ws.append([f"Клиент: {co.name}  ИНН: {co.stir}"])
    ws.append(["Период: с 01.07.2026 по 31.08.2026"]); ws.append(["Входящий остаток на 01.07.2026:", None, 154_300_000]); ws.append([])
    ws.append(["Дата", "№ док.", "Дебет", "Кредит", "Валюта", "Наименование контрагента", "ИНН контрагента", "Назначение платежа"])
    rows = []
    for i in range(40):
        dd = date(2026, 7 + i // 20, 1 + (i % 20))
        usd = i % 8 == 3
        amt = round(float(rng.uniform(800, 9000)), 2) if usd else float(int(rng.uniform(2e6, 40e6) // 1000 * 1000))
        inflow = rng.random() < 0.55
        ws.append([dd, 500 + i, None if inflow else amt, amt if inflow else None, "USD" if usd else "UZS",
                   "Global Textile Trading FZE" if usd else f"Kontragent {i}", None if usd else "30" + str(1000000 + i),
                   ("Export proceeds, contract EX-12/26" if inflow else "Payment for imported dyes, inv. 7781") if usd else
                   ("Оплата за товар по с/ф №" + str(100 + i) if inflow else "Оплата за сырье по договору №14/26")])
        ws.cell(ws.max_row, 1).number_format = "DD.MM.YYYY"
        rows.append({"row": ws.max_row, "currency": "USD" if usd else "UZS", "amount": amt if inflow else -amt})
    wb.save(d / "statement_usd.xlsx")
    _w(d, {**cases[-1], "documents": [{"file": "statement_usd.xlsx", "doc_type": "bank_statement", "rows": rows,
                                       "usd_rows": sum(r["currency"] == "USD" for r in rows)}]})

    # H12 purpose truncated at 60 chars ; H13 microfinance under abbreviation ; H14 salary via card-project bank
    for cid, title, expected in [
        ("H12", "purpose text truncated at 60 chars", "model categorisation with lower confidence"),
        ("H13", "loan repaid to a microfinance org under an abbreviation", "R06 still fires (undeclared recurring loan)"),
        ("H14", "salaries paid via a card-project bank without the word 'salary'", "categorised as salary"),
    ]:
        d = case(cid, title, expected)
        ctx = make_ctx(rng, co, lang="ru")
        txns = []
        for m in range(1, 7):
            extra = []
            if cid == "H13":
                extra.append(Txn(date(2026, m, 12), -9_400_000, Party("MMT \"O.Qadam\"", "309114582", "20208000100114582001", "01153"),
                                 f"Kr. qayt. sh. №MK-311 ({m:02d}/26)", "loan_repayment", group="loan:MK-311"))
            if cid == "H14":
                extra.append(Txn(date(2026, m, 5), -84_600_000, Party("Navbahor Bank ATB - korporativ kartalar loyihasi", None,
                                                                      "22618000100000000101", "01121"),
                                 f"Reestr №{40 + m} bo'yicha mablag'larni xodimlar kartalariga o'tkazish", "salary", group="salary"))
            mo = fin.monthly[(2026, m)]
            txns += month_txns(ctx, 2026, m, sales=int(mo["rev"] * 1120), suppliers=int(mo["cogs"] * 1100),
                               payroll=0 if cid == "H14" else int(mo["rev"] * 80), rent=4_500_000, electricity=2_100_000,
                               vat=3_000_000, bank_fee=400_000, n_sales=20, n_suppliers=12, extra=extra)
        if cid == "H12":
            for t_ in txns:
                t_.purpose = t_.purpose[:60]
        assign_recurring(txns)
        st = write_statement(d / "statement.xlsx", co, txns, 120_000_000, date(2026, 1, 1), date(2026, 6, 30), layout="A", lang="ru")
        extra_truth = {}
        if cid == "H13":
            extra_truth = {"application_declares_debts": [], "planted": [{"rule": "R06", "contract": "MK-311", "lender_printed_as": "MMT \"O.Qadam\""}]}
        _w(d, {**cases[-1], **extra_truth, "documents": [{"file": "statement.xlsx", "doc_type": "bank_statement"}], "transactions": st})

    # H15 English IFRS
    d = case("H15", "English IFRS balance sheet", "non-statutory layout; matched by English label, lower confidence")
    ifrs = english_ifrs(d / "english_ifrs.pdf")
    _w(d, {**cases[-1], "documents": [{"file": "english_ifrs.pdf", **ifrs}]})

    # H16 password-protected PDF
    d = case("H16", "password-protected PDF", "failed: 'PDF is encrypted' (and nothing invented)")
    register_fonts()
    c = canvas.Canvas(str(d / "form2_encrypted.pdf"), pagesize=A4,
                      encrypt=StandardEncryption("s3cret", ownerPassword="owner", canPrint=0, canCopy=0))
    c.setFont("Sans", 12); c.drawString(60, 780, "ОТЧЕТ О ФИНАНСОВЫХ РЕЗУЛЬТАТАХ за 2025 год")
    c.setFont("Sans", 10); c.drawString(60, 750, f"010  Чистая выручка от реализации продукции   {fmt(fy['010'])}")
    c.save()
    _w(d, {**cases[-1], "documents": [{"file": "form2_encrypted.pdf", "user_password": "s3cret", "expected_status": "failed",
                                       "expected_cause": "PDF is encrypted"}]})

    # H17 all-zero form
    d = case("H17", "empty / all-zero Form 2", "analyzed; only zero/dash cells; nothing invented")
    zero = f2_totals({})
    t = render_form(d / "form2_zero.pdf", "form2", "ru", "mof_grid", co, title_when=when_f2, cur=zero, prev=zero)
    _w(d, {**cases[-1], "documents": [{"file": "form2_zero.pdf", "doc_type": "form2", **t}]})

    # H18 duplicate upload
    d = case("H18", "same file uploaded twice", "R12 duplicate (same sha256)")
    t = base_f2(d, "form2_FY2025.pdf")
    shutil.copy(d / "form2_FY2025.pdf", d / "form2_FY2025 (1).pdf")
    _w(d, {**cases[-1], "documents": [{"file": "form2_FY2025.pdf", "doc_type": "form2", **t},
                                      {"file": "form2_FY2025 (1).pdf", "duplicate_of": "form2_FY2025.pdf"}],
           "planted": [{"rule": "R12"}]})

    # H19 blurred low-res phone photo
    d = case("H19", "640x480 blurred phone photo", "failed with cause (resolution, blur score) + whatever text was read")
    v = invoice_photo(d / "photo_640x480.jpg", rng, NAVROZ, "Dilshod Trade MChJ", "0917", date(2026, 9, 17))
    _w(d, {**cases[-1], "documents": [{"file": "photo_640x480.jpg", "doc_type": "invoice", "variant": v}]})

    # H20 letter without figures
    d = case("H20", "a Word letter saved as PDF (no figures)", "unknown + 'what I could read'; no numbers invented")
    t = TextDoc(d / "letter.pdf", "Letter", co.name)
    t.line("Sharq Polimer MChJ", 12, bold=True)
    t.line("Bank filialining kredit bo'limi boshlig'iga", 10)
    t.line("Rasmiy xat / Официальное письмо", 11, bold=True, gap=14)
    for para in [
        "Hurmatli rahbar! Korxonamiz faoliyatini kengaytirish maqsadida bank bilan hamkorlikni davom ettirish niyatidamiz.",
        "Просим рассмотреть возможность реструктуризации графика платежей в связи с сезонным снижением продаж.",
        "Qo'shimcha hujjatlar talab qilinsa, ularni o'z vaqtida taqdim etishga tayyormiz.",
        "С уважением, директор Sharq Polimer MChJ",
    ]:
        t.line(para, 10, gap=10)
    t.save()
    _w(d, {**cases[-1], "documents": [{"file": "letter.pdf", "doc_type": "unknown", "numbers_present": False}]})

    (out / "index.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1))
    print("hard cases:", len(cases))
