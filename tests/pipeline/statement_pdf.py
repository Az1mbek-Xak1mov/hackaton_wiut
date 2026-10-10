"""A bank-client style statement PDF (text layer): title with the 20-digit account, a ruled transaction table whose
payment purposes mention 'hisob-faktura' and wrap onto a second line, and opening/closing balances."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from test_extract_fixtures import FONT

ACCOUNT = "20208000500882571001"
OWN_STIR = "304882571"

# (date, doc no, debit, credit, counterparty, counterparty STIR, purpose line 1, purpose line 2)
ROWS = [
    ("01.07.2026", "100", None, 13_273_000, "Shodlik Sut MChJ", "349955847",
     "Hisob-faktura №7063 bo'yicha", "tovar uchun to'lov, QQS 12%"),
    ("02.07.2026", "101", 2_137_000, None, "Navro'z Non XK", "261298117",
     "Qadoqlash materiallari uchun", "hisob-faktura №3085"),
    ("05.07.2026", "102", None, 17_035_000, "Lazzat Qurilish MChJ", "312561951",
     "Hisob-faktura №7064 bo'yicha to'lov", None),
    ("10.07.2026", "103", 4_500_000, None, "Soliq qo'mitasi", "200000001",
     "QQS to'lovi, 2026 yil iyun", None),
    ("25.07.2026", "104", 18_500_000, None, "Ipoteka Bank", "201055108",
     "Kredit shartnomasi №2024-1177 bo'yicha", "asosiy qarzni to'lash"),
    ("01.08.2026", "105", None, 9_120_000, "Olmaliq Agro MChJ", "268372403",
     "Hisob-faktura №5079 bo'yicha", "yetkazilgan tovar uchun"),
]
OPENING = 150_100_000


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:,.2f}".replace(",", " ")


def make_statement_pdf(path: str | Path, *, title: str = "MIKROKREDITBANK  —  Shaxsiy kabinet",
                       uz_title: bool = False, ruled: bool = True) -> Path:
    """Default title has no statement keyword at all ('ko'chirma'/'выписка'): only the layout says statement."""
    path = Path(path)
    w, h = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(w, h))
    c.setFont(FONT, 9)
    y = h - 40
    c.drawString(40, y, title)
    y -= 16
    if uz_title:
        c.drawString(40, y, "Hisob raqamidan ko'chirma")
        y -= 16
    c.drawString(40, y, f"Hisob raqami: {ACCOUNT}    STIR: {OWN_STIR}    Mijoz: Zilola Mebel MChJ")
    y -= 16
    c.drawString(40, y, f"Davr: 01.07.2026 - 31.08.2026    Kirish qoldig'i: {_fmt(OPENING)}")
    y -= 26
    xs = [40, 105, 150, 235, 320, 455, 520]   # date, no, debit, credit, counterparty, STIR, purpose
    heads = ["Sana", "Hujjat №", "Debet", "Kredit", "Kontragent nomi", "INN", "To'lov maqsadi"]
    for x, t in zip(xs, heads):
        c.drawString(x, y, t)
    if ruled:
        c.line(36, y - 4, w - 36, y - 4)
    y -= 16
    bal = OPENING
    for d, no, deb, cred, cp, stir, p1, p2 in ROWS:
        bal += (cred or 0) - (deb or 0)
        c.drawString(xs[0], y, d)
        c.drawString(xs[1], y, no)
        if deb:
            c.drawRightString(xs[3] - 12, y, _fmt(deb))
        if cred:
            c.drawRightString(xs[4] - 12, y, _fmt(cred))
        c.drawString(xs[4], y, cp)
        c.drawString(xs[5], y, stir)
        c.drawString(xs[6], y, p1)
        y -= 12
        if p2:
            c.drawString(xs[6], y, p2)
            y -= 12
        if ruled:
            c.line(36, y + 8, w - 36, y + 8)
        y -= 4
    y -= 10
    c.drawString(40, y, f"Chiqish qoldig'i: {_fmt(bal)}")
    c.save()
    return path


def closing_balance() -> float:
    return OPENING + sum((r[3] or 0) - (r[2] or 0) for r in ROWS)
