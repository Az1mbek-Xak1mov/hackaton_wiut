"""Builders for small synthetic statutory PDFs used by the pipeline tests (no tests in this module).

The real data generator lives in eval/generator; these builders only exist so the pipeline tests are
self-contained and fast.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.pipeline import dictionary as dic  # noqa: E402

FONT = "DejaVu"
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT, _FONT_PATH))

INCOME_LINES = {"010", "090", "110", "120", "130", "140", "150", "160"}


def fmt(v: float) -> str:
    s = f"{abs(int(round(v))):,}".replace(",", " ")
    return f"({s})" if v < 0 else s


def balanced_form1(seed: int = 1) -> dict[str, float]:
    """Leaves random, totals from sum_of, retained earnings plugs the balance."""
    rnd = random.Random(seed)
    vals: dict[str, float] = {}
    for e in dic.entries("form1"):
        if not e.sum_of and not e.parts:
            vals[e.code] = float(rnd.randrange(0, 900_000, 100))
    vals["011"] = min(vals["011"], vals["010"])
    vals["021"] = min(vals["021"], vals["020"])
    vals["440"] = 0.0
    vals["210"] = vals["220"] + float(rnd.randrange(10_000, 200_000, 100))
    vals["490"] = vals["570"] + vals["580"] + float(rnd.randrange(0, 50_000, 100))
    vals["600"] = sum(vals[c] for c in ("610", "670", "680", "720", "730", "740", "750", "760")) + float(rnd.randrange(0, 50_000, 100))

    def resolve():
        changed = True
        while changed:
            changed = False
            for e in dic.entries("form1"):
                if e.sum_of and e.code not in vals:
                    v = dic.evaluate_sum(e, vals)
                    if v is not None:
                        vals[e.code] = v
                        changed = True
    vals.pop("450", None)
    vals["450"] = 0.0
    resolve()
    gap = vals["400"] - vals["780"]
    vals["450"] = gap
    for c in ("480", "780"):
        vals.pop(c)
    resolve()
    assert abs(vals["400"] - vals["780"]) < 0.5
    return vals


def form2_values(seed: int = 2, revenue: float = 6_349_900) -> dict[str, float]:
    rnd = random.Random(seed)
    v = {"010": revenue, "020": round(revenue * rnd.uniform(0.55, 0.8), -2)}
    v["050"], v["060"], v["070"] = (round(revenue * x, -2) for x in (0.05, 0.08, 0.02))
    v["090"] = round(revenue * 0.01, -2)
    for c in ("120", "130", "140", "150", "160"):
        v[c] = 0.0
    v["130"] = 12_300.0
    v["180"], v["190"], v["200"], v["210"] = 162_000.0, 0.0, 4_100.0, 0.0
    v["230"] = 0.0
    v["250"] = 81_800.0
    v["260"] = 0.0
    for e in ("030", "040", "100", "110", "170", "220", "240", "270"):
        v[e] = dic.evaluate_sum(dic.by_code("form2", e), v)
    return v


def _wrap(text: str, width_pt: float, size: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(t, FONT, size) <= width_pt:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_form_pdf(path: Path, form: str, cur: dict[str, float], prev: dict[str, float] | None = None, *,
                  lang: str = "ru", layout: str = "auto", title: str | None = None, period_text: str = "",
                  unit_text: str = "тыс. сум", codes: bool = True, blank_prev: set[str] = frozenset(),
                  value_fmt=fmt, header: str | None = None) -> Path:
    """One-page Form 1 / Form 2. layout: '4col' (official Form 2), '2col' (start/end or prior/current)."""
    if layout == "auto":
        layout = "4col" if form == "form2" else "2col"
    prev = prev or {}
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 40
    titles = {
        ("form1", "ru"): "БУХГАЛТЕРСКИЙ БАЛАНС — ФОРМА №1", ("form2", "ru"): "ОТЧЕТ О ФИНАНСОВЫХ РЕЗУЛЬТАТАХ — ФОРМА №2",
        ("form1", "uz_latn"): "BUXGALTERIYA BALANSI — 1-son shakl", ("form2", "uz_latn"): "MOLIYAVIY NATIJALAR TO'G'RISIDAGI HISOBOT — 2-son shakl",
        ("form1", "uz_cyrl"): "БУХГАЛТЕРИЯ БАЛАНСИ — 1-сон шакл", ("form2", "uz_cyrl"): "МОЛИЯВИЙ НАТИЖАЛАР ТЎҒРИСИДАГИ ҲИСОБОТ — 2-сон шакл",
        ("form1", "en"): "STATEMENT OF FINANCIAL POSITION", ("form2", "en"): "STATEMENT OF PROFIT OR LOSS",
    }
    c.setFont(FONT, 11)
    c.drawString(40, y, title or titles[(form, lang)])
    y -= 16
    c.setFont(FONT, 8)
    c.drawString(40, y, "ООО «Фаровон Савдо»   ИНН 302447118")
    y -= 12
    if period_text:
        c.drawString(40, y, period_text)
        y -= 12
    if unit_text:
        c.drawString(40, y, f"Единица измерения: {unit_text}")
        y -= 16
    label_x, label_w, code_x = 36, 230, 282
    if layout == "4col":
        col_x1 = [370, 432, 494, 556]
        heads = {"ru": ("За соответствующий период прошлого года", "За отчетный период", "доходы (прибыль)", "расходы (убытки)"),
                 "uz_latn": ("O'tgan yilning shu davrida", "Hisobot davrida", "daromadlar (foyda)", "xarajatlar (zararlar)"),
                 "uz_cyrl": ("Ўтган йилнинг шу даврида", "Ҳисобот даврида", "даромадлар (фойда)", "харажатлар (зарарлар)"),
                 "en": ("Prior year", "Current period", "income (profit)", "expenses (loss)")}[lang]
        c.setFont(FONT, 6.5)
        c.drawString(label_x, y, "Наименование показателя" if lang == "ru" else "Ko'rsatkichlar nomi")
        c.drawString(code_x - 4, y, "Код" if lang in ("ru", "uz_cyrl") else "Kod")
        c.drawString(318, y, heads[0][:34])
        c.drawString(450, y, heads[1])
        y -= 9
        for x1, h in zip(col_x1, [heads[2], heads[3], heads[2], heads[3]]):
            c.drawRightString(x1, y, h)
        y -= 12
    else:
        col_x1 = [470, 556]
        if header:
            hl, hr = header.split("|")
        elif form == "form1":
            hl, hr = {"ru": ("На начало отчетного периода", "На конец отчетного периода"),
                      "uz_latn": ("Hisobot davri boshiga", "Hisobot davri oxiriga"),
                      "uz_cyrl": ("Ҳисобот даври бошига", "Ҳисобот даври охирига"),
                      "en": ("31 December 2024", "31 December 2025")}[lang]
        else:
            hl, hr = {"ru": ("За прошлый год", "За отчетный период"), "uz_latn": ("O'tgan yilning shu davrida", "Hisobot davrida"),
                      "uz_cyrl": ("Ўтган йилнинг шу даврида", "Ҳисобот даврида"), "en": ("2024", "2025")}[lang]
        c.setFont(FONT, 6.5)
        c.drawString(label_x, y, "Наименование показателя" if lang == "ru" else "Ko'rsatkichlar nomi")
        if codes:
            c.drawString(code_x - 4, y, "Код")
        c.drawRightString(col_x1[0], y, hl)
        c.drawRightString(col_x1[1], y, hr)
        y -= 14
    size = 7
    for e in dic.entries(form):
        if e.code not in cur:
            continue
        label = e.labels.get(lang, e.labels["en"])[0]
        lines = _wrap(label, label_w, size)
        c.setFont(FONT, size)
        for i, ln in enumerate(lines):
            c.drawString(label_x, y - i * 8.5, ln)
        if codes:
            c.drawString(code_x, y, e.code)
        vcur, vprev = cur.get(e.code), prev.get(e.code)
        if layout == "4col":
            def place(v, inc_x, exp_x):
                if v is None:
                    return
                if e.kind == "result":
                    c.drawRightString(inc_x if v >= 0 else exp_x, y, value_fmt(abs(v)))
                elif e.code in INCOME_LINES:
                    c.drawRightString(inc_x, y, value_fmt(v))
                else:
                    c.drawRightString(exp_x, y, value_fmt(v))
            if e.code not in blank_prev:
                place(vprev, col_x1[0], col_x1[1])
            place(vcur, col_x1[2], col_x1[3])
        else:
            if vprev is not None and e.code not in blank_prev:
                c.drawRightString(col_x1[0], y, value_fmt(vprev))
            if vcur is not None:
                c.drawRightString(col_x1[1], y, value_fmt(vcur))
        y -= max(1, len(lines)) * 8.5 + 3
        if y < 50:
            c.showPage()
            y = H - 50
    c.drawString(40, max(30, y - 20), "Руководитель ______________   Главный бухгалтер ______________")
    c.save()
    return path


def rasterize(pdf: Path, out: Path, *, dpi: int = 150, skew: float = 1.5, blur: float = 0.6, jpeg_q: int = 60,
              noise: float = 0.01, rotate90: bool = False, seed: int = 0, as_jpg: bool = False) -> Path:
    """Render the PDF to an image, add scan noise, save as an image-only PDF (or JPG)."""
    import io

    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    rnd = np.random.default_rng(seed)
    doc = pdfium.PdfDocument(str(pdf))
    img = doc[0].render(scale=dpi / 72.0).to_pil().convert("L")
    doc.close()
    img = img.rotate(skew, resample=Image.BICUBIC, expand=False, fillcolor=255)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    arr = np.asarray(img).astype(np.int16)
    if noise:
        mask = rnd.random(arr.shape) < noise
        arr[mask] = rnd.integers(0, 255, mask.sum())
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if rotate90:
        img = img.rotate(90, expand=True)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=jpeg_q)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if as_jpg:
        img.save(out, "JPEG", quality=jpeg_q)
    else:
        img.save(out, "PDF", resolution=float(dpi))
    return out
