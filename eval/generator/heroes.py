"""Hero bundles pinned to design/demo-data.json. The pipeline must re-derive these figures from the files.

hero_farovon  APP-2026-0931 loan file (ru, MoF grid; FY2025 balance is a 150-dpi scan)
hero_navroz   owner documents (uz_latn) + blurred invoice photo
hero_zilola   monitoring documents for loan L-2025-0417 (quarterly reports, ru)
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .company import Company, account
from .docs_pdf import TextDoc, render_application
from .noise import degrade, render_pages, scan_pdf
from .pdf_forms import date_phrase, fmt, period_phrase, render_form
from .statement import (Grammar, Party, StatementCtx, Txn, assign_recurring, balance_to_target, make_ctx,
                        month_txns, party_from, write_statement)
from .company import counterparty
from .totals import f1_totals, f2_totals

M = 1_000_000

# ------------------------------------------------------------------------------------------- Farovon
FAROVON = Company(
    name="Farovon Savdo MChJ", stir="302447118", industry_key="food_dist", industry="Food distribution (dairy & frozen)",
    region="Tashkent", bank="Navbahor Bank ATB", mfo="01121", account="20208000300447118001",
    director="Saidov R.", accountant="Nazarova M.", employees=42, since=2018,
    address="Toshkent sh., Yashnobod tumani, Mahtumquli ko'chasi, 74-uy")

FAR_F1 = {
    "2024-12-31": dict(**{"010": 1_690_500, "011": 402_880, "020": 30_000, "021": 4_840, "150": 52_900, "180": 987_410,
                          "190": 21_880, "220": 652_920, "260": 94_770, "270": 14_310, "310": 18_400, "330": 3_960,
                          "340": 252_900, "410": 400_000, "430": 60_000, "450": 810_075, "470": 180_000,
                          "610": 1_560_263, "670": 96_500, "680": 88_120, "690": 9_100, "700": 10_560, "720": 57_400,
                          "760": 140_212}),
    "2025-12-31": dict(**{"010": 1_812_040, "011": 548_310, "020": 30_000, "021": 8_040, "150": 64_230, "180": 1_233_784,
                          "190": 24_516, "220": 812_406, "260": 128_330, "270": 18_044, "310": 21_120, "330": 4_212,
                          "340": 395_844, "410": 400_000, "430": 60_000, "450": 1_422_164, "470": 240_000,
                          "610": 1_402_516, "670": 118_030, "680": 96_412, "690": 9_860, "700": 11_440, "720": 61_808,
                          "760": 165_946}),
    "2026-06-30": dict(**{"010": 1_902_040, "011": 583_688, "020": 30_000, "021": 8_140, "150": 61_040, "180": 1_351_766,
                          "220": 912_436, "260": 152_348, "270": 19_820, "310": 17_400, "330": 4_110, "340": 351_480,
                          "410": 400_000, "430": 60_000, "450": 1_740_176, "470": 70_224, "610": 1_644_980,
                          "670": 98_410, "680": 92_140, "690": 10_120, "700": 12_060, "720": 63_520, "760": 18_982}),
}
FAR_F2 = {
    "FY2025": {"010": 9_842_316, "020": 8_614_902, "050": 214_300, "060": 291_520, "070": 42_792, "090": 112_450,
               "130": 6_214, "180": 77_360, "250": 108_017},
    "FY2024": {"010": 9_108_227, "020": 7_992_640, "050": 201_400, "060": 270_118, "070": 41_388, "090": 98_330,
               "130": 5_880, "180": 41_215, "250": 99_851},
    "H1-2026": {"010": 5_316_428, "020": 4_672_104, "050": 115_200, "060": 158_050, "070": 23_068, "090": 94_412,
                "130": 3_102, "180": 71_388, "250": 56_120},
    "H1-2025": {"010": 4_790_115, "020": 4_205_960, "050": 105_300, "060": 144_212, "070": 20_900, "090": 52_880,
                "130": 2_940, "180": 38_620, "250": 49_641},
}
FAR_INFLOWS = [862_418_000, 884_106_000, 921_734_000, 905_312_000, 948_602_000, 931_206_000, 918_410_000, 929_124_000]
FAR_N_SALES = [181, 178, 189, 184, 192, 187, 186, 183]
FAR_N_SUP = [46, 47, 48, 47, 49, 48, 47, 48]
LENDER = Party("Oltin Qadam mikromoliya tashkiloti MChJ", "309114582", "20208000100114582001", "01153")


def _check_farovon(f1: dict, f2: dict) -> dict:
    """Assert every number the design shows (mln UZS, 1 decimal) and the ratios."""
    r1 = lambda v: round(v / 1000, 1)  # noqa: E731
    a, b = f1["2025-12-31"], f1["2026-06-30"]
    fy, h1 = f2["FY2025"], f2["H1-2026"]
    checks = {
        "rev_fy": (r1(fy["010"]), 9842.3), "cogs_fy": (r1(fy["020"]), 8614.9), "opex_fy": (r1(fy["040"]), 548.6),
        "np_fy": (r1(fy["270"]), 612.1), "rev_h1": (r1(h1["010"]), 5316.4), "cogs_h1": (r1(h1["020"]), 4672.1),
        "opex_h1": (r1(h1["040"]), 296.3), "np_h1": (r1(h1["270"]), 318.0),
        "ta_fy": (r1(a["400"]), 3988.2), "ca_fy": (r1(a["390"]), 2702.5), "inv_fy": (r1(a["140"]), 1298.0),
        "cl_fy": (r1(a["600"]), 1866.0), "lt_fy": (r1(a["490"]), 0.0),
        "ta_h1": (r1(b["400"]), 4210.6), "ca_h1": (r1(b["390"]), 2870.4), "inv_h1": (r1(b["140"]), 1412.8),
        "cl_h1": (r1(b["600"]), 1940.2), "lt_h1": (r1(b["490"]), 0.0),
        "current_ratio": (round(b["390"] / b["600"], 2), 1.48),
        "quick_ratio": (round((b["390"] - b["140"]) / b["600"], 2), 0.75),
        "net_margin_h1": (round(h1["270"] / h1["010"] * 100, 1), 6.0),
        "net_margin_fy": (round(fy["270"] / fy["010"] * 100, 1), 6.2),
        "debt_to_equity": (round((b["490"] + b["600"]) / b["480"], 2), 0.85),
        "dscr_new": (round((h1["270"] + h1["170"]) / 6 / 44_100, 2), 1.47),
        "dscr_incl_undeclared": (round((h1["270"] + h1["170"]) / 6 / (44_100 + 18_500), 2), 1.04),
        "receivable_days_220": (round(b["220"] / h1["010"] * 181), 31),
        "installment_vs_revenue_pct": (round(44_100 / (h1["010"] / 6) * 100, 1), 5.0),
        "re_roll_h1": (b["450"] - a["450"], h1["270"]),
        "re_roll_fy": (a["450"] - f1["2024-12-31"]["450"], fy["270"]),
    }
    bad = {k: v for k, v in checks.items() if v[0] != v[1]}
    assert not bad, bad
    for k, v in f1.items():
        assert v["400"] == v["780"], k
    return {k: v[0] for k, v in checks.items()}


def build_farovon(root: Path) -> dict:
    out = root / "hero_farovon"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = np.random.default_rng(9001)
    f1 = {k: f1_totals(v) for k, v in FAR_F1.items()}
    f2 = {k: f2_totals(v) for k, v in FAR_F2.items()}
    pinned = _check_farovon(f1, f2)
    c = FAROVON
    docs = []
    received = date(2026, 10, 6)
    t = render_application(out / "Ariza_FarovonSavdo.pdf", c, "ru", requested_kuzs=850_000, term_months=24,
                           rate_pct=22.0, purpose="Пополнение оборотных средств: рефрижераторный фургон 320,0 млн сум; товарный запас 530,0 млн сум",
                           collateral="2 грузовых автомобиля (оценка не представлена)",
                           declared_revenue_kuzs=10_400_000, declared_np_kuzs=610_000, fy=2025, debts=[],
                           received=received, amount_style="uzs", revenue_in_mln_label=True)
    docs.append({"file": "Ariza_FarovonSavdo.pdf", "doc_type": "loan_application", "period": None, **t,
                 "variant": {"scan": False}})
    specs = [
        ("Balans_2025.pdf", "form1", f1["2025-12-31"], f1["2024-12-31"], date_phrase("ru", date(2025, 12, 31)), ("2025-01-01", "2025-12-31"), date(2026, 1, 26)),
        ("Balans_1H2026.pdf", "form1", f1["2026-06-30"], f1["2025-12-31"], date_phrase("ru", date(2026, 6, 30)), ("2026-01-01", "2026-06-30"), date(2026, 7, 27)),
        ("Forma2_2025.pdf", "form2", f2["FY2025"], f2["FY2024"], period_phrase("ru", "FY2025"), ("2025-01-01", "2025-12-31"), date(2026, 1, 26)),
        ("Forma2_1H2026.pdf", "form2", f2["H1-2026"], f2["H1-2025"], period_phrase("ru", "H1-2026"), ("2026-01-01", "2026-06-30"), date(2026, 7, 27)),
    ]
    for fname, form, cur, prev, when, (ps, pe), sub in specs:
        t = render_form(out / fname, form, "ru", "mof_grid", c, title_when=when, cur=cur, prev=prev, submitted=sub)
        docs.append({"file": fname, "doc_type": form, "period": {"start": ps, "end": pe}, **t, "variant": {"scan": False}})
    # FY2025 balance is a 150-dpi scan (inventory confidence lower in the design)
    v = scan_pdf(out / "Balans_2025.pdf", out / "Balans_2025.pdf", rng, dpi=150, skew=1.2, blur=0.45, jpeg_q=62,
                 stamp="FAROVON SAVDO MChJ")
    docs[1]["variant"] = v
    # statement Jan-Aug 2026
    ctx = make_ctx(rng, c, lang="ru", n_customers=64, n_suppliers=14)
    ctx.landlord = Party("Yashnobod Ombor Servis MChJ", "306551209", account(rng), "01089")
    ctx.rent_contract = "12/24"
    txns: list[Txn] = []
    cw = np.array(rng.pareto(1.3, 64) + 0.2); cw = cw / cw.sum()
    sw = np.array(rng.pareto(1.0, 14) + 0.2); sw = sw / sw.sum()
    vat = [9_812_000, 9_640_000, 10_420_000, 9_960_000, 10_810_000, 10_250_000, 10_090_000, 10_330_000]
    elec = [3_412_000, 3_288_000, 3_120_000, 3_064_000, 3_398_000, 3_802_000, 4_116_000, 4_208_000]
    ptax = {1: 26_980_000, 4: 28_040_000, 7: 28_080_000}
    refunds = {3: 4_620_000, 5: 6_140_000, 7: 3_420_000}
    for i, m in enumerate(range(1, 9)):
        extra = []
        d20 = date(2026, m, 20)
        purpose = "Погашение кредита по договору № 2024-1177 от 14.11.2024"
        extra.append(Txn(d20, -18_500_000, LENDER, purpose, "loan_repayment", group="loan:2024-1177",
                         doc_no=41 if m == 2 else 0, meta={"fixed": True, "undeclared": True}))
        if m in refunds:
            cust = ctx.customers[int(rng.integers(0, 64))]
            dd = date(2026, m, int(rng.integers(3, 27)))
            extra.append(Txn(dd, -refunds[m], cust, ctx.grammar.render("refund"), "other", meta={"fixed": True}))
        txns += month_txns(ctx, 2026, m, sales=FAR_INFLOWS[i], suppliers=int(840 * M), payroll_net=27_720_000,
                           payroll_taxes=(3_780_000, 3_780_000), rent=6_500_000, electricity=elec[i], gas=420_000,
                           water=210_000, vat=vat[i], profit_tax=ptax.get(m, 0), bank_fee=850_000 + 1000 * i,
                           customer_weights=cw, supplier_weights=sw, n_sales=FAR_N_SALES[i], n_suppliers=FAR_N_SUP[i],
                           extra=extra)
    opening = f1["2025-12-31"]["340"] * 1000
    balance_to_target(txns, opening, f1["2026-06-30"]["340"] * 1000, date(2026, 6, 30), rng)
    balance_to_target(txns, opening, 378_214_000, date(2026, 8, 31), rng, since=date(2026, 6, 30))
    assign_recurring(txns)
    st = write_statement(out / "vypiska_2026.xlsx", c, txns, opening, date(2026, 1, 1), date(2026, 8, 31), layout="A", lang="ru")
    assert st["month_end_balances"]["2026-06"] == f1["2026-06-30"]["340"] * 1000, st["month_end_balances"]
    inflow = sum(r["amount"] for r in st["rows"] if r["amount"] > 0)
    assert inflow == 7_300_912_000, inflow
    assert len(st["rows"]) == 1946, len(st["rows"])
    cats = sorted({r["category"] for r in st["rows"]})
    docs.append({"file": "vypiska_2026.xlsx", "doc_type": "bank_statement", "period": {"start": "2026-01-01", "end": "2026-08-31"},
                 "variant": {"layout": "A"}})
    truth = {
        "bundle_id": "hero_farovon", "application": "APP-2026-0931", "received": received.isoformat(),
        "company": {"name": c.name, "stir": c.stir, "industry": c.industry, "region": "Tashkent, Yashnobod",
                    "employees": c.employees, "since": c.since},
        "documents": [{k: v for k, v in d.items() if k != "pages"} | {"page_count": d.get("pages", 1)} for d in docs],
        "transactions": st,
        "planted": [
            {"rule": "R06", "label": "Undeclared obligation", "contract": "2024-1177", "contract_date": "2024-11-14",
             "lender": LENDER.name, "monthly_uzs": 18_500_000, "payments": 8, "total_uzs": 148_000_000, "day": 20},
            {"rule": "R07", "label": "Contradiction", "declared_revenue_kuzs": 10_400_000, "f2_010_kuzs": 9_842_316,
             "diff_kuzs": 557_684, "diff_pct": 5.7},
            {"rule": "R10", "label": "Missing document", "missing": "tax_declaration", "period": "Q2-2026"},
        ],
        "expected_findings_exactly": ["R06", "R07", "R10"],
        "expected_clean_rules": [r for r in [f"R{i:02d}" for i in range(1, 13)] if r not in ("R06", "R07", "R10")],
        "loan_request": {"amount_kuzs": 850_000, "term_months": 24, "rate_pct": 22.0, "installment_kuzs": 44_100,
                         "annuity_installment_exact_kuzs": round(850_000 * (0.22 / 12) / (1 - (1 + 0.22 / 12) ** -24), 1)},
        "pinned_design_values": pinned,
        "statement_summary": {"rows": len(st["rows"]), "categories": cats, "inflows_jan_aug_uzs": inflow,
                              "avg_monthly_inflow_uzs": inflow // 8},
        "notes": [
            "Official line codes (dictionary): finance costs = form2 170/180 (design said 120); profit tax = 250 (design 240); total L+E = form1 780.",
            "Receivable days 31 uses form1 220 (trade receivables); 210 total gives 37.5.",
            "Installment vs revenue 5.0% uses F2 H1 revenue / 6 (886.1); with statement inflows (912.6) it is 4.8%.",
        ],
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return truth


# ------------------------------------------------------------------------------------------- Navro'z
NAVROZ = Company(
    name="Navro'z Tekstil MChJ", stir="305118742", industry_key="textile", industry="Textile manufacturing",
    region="Namangan", bank="Bodomzor Bank ATB", mfo="01204", account="20208000900118742001",
    director="Nazarov S.", accountant="Ergasheva D.", employees=64, since=2014,
    address="Namangan sh., Sanoat ko'chasi, 12-uy")
NAV_IN = [1012.4, 1035.8, 1066.1, 1088.0, 1121.0, 1071.0, 1142.0, 1180.0, 1075.6]
NAV_OUT = [998.6, 1009.2, 1042.9, 1040.0, 1085.5, 1047.4, 1210.3, 1247.5, 1193.5]
NAV_END = [415.0, 441.6, 464.8, 512.8, 548.3, 571.9, 503.6, 436.1, 318.2]
NAV_OPEN = 401.2
NAV_N_SALES = [132, 128, 137, 134, 139, 131, 136, 140, 138]
NAV_N_SUP = [119, 121, 124, 120, 125, 118, 122, 123, 123]
NAV_F2_H1 = {"010": 6_349_900, "020": 4_021_600, "050": 412_300, "060": 868_400, "070": 205_500, "180": 162_000, "250": 81_800}
NAV_F2_H1_PREV = {"010": 5_812_400, "020": 3_702_100, "050": 389_500, "060": 822_600, "070": 186_600, "180": 174_000, "250": 0}
NAV_F1 = {
    "2024-12-31": {"010": 3_180_200, "011": 905_400, "020": 45_000, "021": 13_400, "100": 64_800, "150": 548_900,
                   "160": 79_300, "170": 366_200, "190": 28_400, "220": 352_100, "260": 88_300, "270": 19_800,
                   "310": 12_900, "330": 5_920, "340": 318_700, "410": 1_000_000, "430": 120_000, "570": 0,
                   "610": 214_700, "670": 49_800, "680": 57_300, "690": 6_600, "700": 13_100, "720": 44_800, "760": 19_900},
    "2025-12-31": {"010": 3_420_500, "011": 1_104_300, "020": 45_000, "021": 18_200, "100": 120_400, "150": 612_300,
                   "160": 88_400, "170": 402_100, "190": 31_200, "220": 398_600, "260": 96_400, "270": 22_100,
                   "310": 14_800, "330": 6_840, "340": 401_200, "410": 1_000_000, "430": 120_000, "570": 1_512_000,
                   "610": 236_200, "670": 54_300, "680": 61_800, "690": 7_200, "700": 14_600, "720": 48_900, "760": 22_700},
}


def _plug_re(leaf: dict) -> dict:
    leaf = dict(leaf)
    leaf["450"] = 0
    v = f1_totals(leaf)
    leaf["450"] = v["400"] - v["780"]
    return f1_totals(leaf)


def invoice_photo(path: Path, rng, seller: Company, buyer: str, number: str, d: date) -> dict:
    """A 640x480 blurred phone photo of an invoice (amounts unreadable on purpose)."""
    from PIL import ImageDraw, ImageFont
    from .pdf_forms import FONT_DIR
    W, H = 1280, 960
    img = Image.new("RGB", (W, H), (236, 233, 226))
    d0 = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(FONT_DIR / "IBMPlexSans-Regular.ttf"), 22)
    fb = ImageFont.truetype(str(FONT_DIR / "IBMPlexSans-Bold.ttf"), 30)
    d0.rectangle([60, 40, W - 60, H - 40], fill=(252, 252, 250))
    d0.text((W // 2, 90), f"SCHYOT-FAKTURA / СЧЕТ-ФАКТУРА № {number}", fill=(20, 20, 20), font=fb, anchor="mm")
    d0.text((W // 2, 130), f"{d:%d.%m.%Y}", fill=(20, 20, 20), font=f, anchor="mm")
    d0.text((100, 180), f"Yetkazib beruvchi: {seller.name}, STIR {seller.stir}", fill=(20, 20, 20), font=f)
    d0.text((100, 215), f"Xaridor: {buyer}", fill=(20, 20, 20), font=f)
    y = 270
    d0.line([100, y, W - 100, y], fill=(40, 40, 40), width=2)
    items = [("Paxta ip-kalava Ne 30/1", 4200, 38_500), ("Trikotaj mato (suprem)", 1850, 61_200), ("Bo'yoq xizmati", 1, 12_400_000)]
    total = 0
    for name, q, p in items:
        y += 50
        amt = q * p
        total += amt
        d0.text((110, y), name, fill=(20, 20, 20), font=f)
        d0.text((700, y), f"{q}", fill=(20, 20, 20), font=f)
        d0.text((W - 110, y), fmt(amt), fill=(20, 20, 20), font=f, anchor="ra")
    y += 70
    vat = int(total * 0.12)
    for lab, v in (("QQS 12% / НДС 12%", vat), ("Jami / Итого", total + vat)):
        d0.text((700, y), lab, fill=(20, 20, 20), font=fb if "Jami" in lab else f)
        d0.text((W - 110, y), fmt(v), fill=(20, 20, 20), font=fb if "Jami" in lab else f, anchor="ra")
        y += 45
    img = img.rotate(float(rng.uniform(-6, 6)), resample=Image.BICUBIC, fillcolor=(90, 88, 84))
    img = img.resize((640, 480), Image.LANCZOS).filter(ImageFilter.GaussianBlur(2.4))
    img.save(path, "JPEG", quality=38)
    return {"photo": True, "width": 640, "height": 480, "blur": 2.4, "jpeg_q": 38,
            "expected_status": "failed", "expected_cause": "Image is 640×480 px and blurred; amounts are unreadable.",
            "invoice_total_uzs": total + vat}


def build_navroz(root: Path) -> dict:
    out = root / "hero_navroz"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = np.random.default_rng(9002)
    c = NAVROZ
    docs = []
    f2c, f2p = f2_totals(NAV_F2_H1), f2_totals(NAV_F2_H1_PREV)
    assert (f2c["030"], f2c["040"], f2c["240"], f2c["270"]) == (2_328_300, 1_486_200, 680_100, 598_300)
    assert (f2p["030"], f2p["040"], f2p["270"]) == (2_110_300, 1_398_700, 537_600)
    t = render_form(out / "Forma2_1yarim_2026.pdf", "form2", "uz_latn", "mof_grid", c,
                    title_when=period_phrase("uz_latn", "H1-2026"), cur=f2c, prev=f2p, submitted=date(2026, 7, 24),
                    blank_prev={"250"})
    docs.append({"file": "Forma2_1yarim_2026.pdf", "doc_type": "form2", "period": {"start": "2026-01-01", "end": "2026-06-30"},
                 **t, "variant": {"scan": False}, "design_note": "250 prior-year cell blank (design: '2025 cell blank', conf 84)"})
    f1 = {k: _plug_re(v) for k, v in NAV_F1.items()}
    t = render_form(out / "Balans_2025_skan.pdf", "form1", "uz_latn", "mof_grid", c,
                    title_when=date_phrase("uz_latn", date(2025, 12, 31)), cur=f1["2025-12-31"], prev=f1["2024-12-31"],
                    submitted=date(2026, 1, 27))
    # stamp lands over the current-period value column around rows 150-180 (3 low-confidence cells)
    v = scan_pdf(out / "Balans_2025_skan.pdf", out / "Balans_2025_skan.pdf", rng, dpi=200, skew=0.9, blur=0.55,
                 jpeg_q=58, stamp="NAVRO'Z TEKSTIL MChJ * NAMANGAN", stamp_xy=(1400, 520))
    v["stamp_note"] = "stamp over the end-of-period value column near the top of the last page (rows ~490-680): low-confidence cells expected"
    docs.append({"file": "Balans_2025_skan.pdf", "doc_type": "form1", "period": {"start": "2025-01-01", "end": "2025-12-31"},
                 **t, "variant": v})
    # statement Jan-Sep 2026
    ctx = make_ctx(rng, c, lang="uz", n_customers=28, n_suppliers=12)
    named_c = [("Toshkent Mato Bozori MChJ", "301845226"), ("Andijon Kiyim Fabrikasi MChJ", "302991457"),
               ("Dilshod Trade MChJ", "307230614")]
    for i, (n, s) in enumerate(named_c):
        ctx.customers[i] = party_from(rng, n, s)
    ctx.suppliers[0] = party_from(rng, "Qo'qon Paxta Tola MChJ", "303318470")
    yarn = party_from(rng, "Farg'ona Ip-Kalava MChJ", "306702283")
    ctx.landlord = Party("Namangan Sanoat Parki MChJ", "305660127", account(rng), "01204")
    ctx.rent_contract = "7/25"
    cw = np.array([0.22, 0.12, 0.09] + list(rng.pareto(1.4, 25) * 0.02 + 0.012)); cw = cw / cw.sum()
    sw = np.array([0.3] + list(rng.pareto(1.2, 11) * 0.05 + 0.03)); sw = sw / sw.sum()
    salary = [284.2] * 3 + [291.0] * 3 + [298.4] * 3
    ptax = [(33.9, 33.9)] * 3 + [(34.7, 34.7)] * 3 + [(35.6, 35.6)] * 3
    elec = [38.2, 36.9, 33.4, 29.8, 27.2, 30.1, 33.9, 30.9, 36.5]
    gas = [9.8, 9.1, 7.2, 4.1, 2.9, 2.6, 2.8, 3.1, 4.5]
    water = [1.5, 1.4, 1.5, 1.5, 1.6, 1.6, 1.7, 1.6, 1.6]
    interest = [36.0, 34.5, 33.0, 31.5, 30.0, 28.5, 27.0, 25.5, 24.0]
    profit_tax = {1: 48.6, 4: 52.3, 7: 55.0}
    vague_per_month = [0, 0, 2, 2, 2, 2, 2, 2, 2]
    loan_party = Party(c.bank + " (kredit hisobvarag'i)", None, "16307000900118742001", c.mfo)
    txns: list[Txn] = []
    for i, m in enumerate(range(1, 10)):
        fee = 1.1
        fixed = salary[i] + sum(ptax[i]) + 16.0 + elec[i] + gas[i] + water[i] + 72.0 + interest[i] + profit_tax.get(m, 0) + fee
        extra = []
        vague_total = 0
        for _ in range(vague_per_month[i]):
            amt = int(round(rng.uniform(0.8, 4.5) * M, -3))
            vague_total += amt
            dd = date(2026, m, int(rng.integers(2, 27)))
            extra.append(Txn(dd, -amt, ctx.suppliers[int(rng.integers(1, 12))], ctx.grammar.render("vague", d=dd),
                             "supplier_payment", meta={"vague": True, "fixed": True}))
        if m == 9:
            fixed += 185.0
            extra.append(Txn(date(2026, 9, 22), -185 * M, yarn, "Ip-kalava uchun oldindan to'lov (tovar zaxirasi), shartnoma №19/26",
                             "supplier_payment", meta={"fixed": True, "yarn_prepayment": True}))
        suppliers_total = int(round((NAV_OUT[i] - fixed) * M)) - vague_total
        assert suppliers_total > 0
        loans = [{"party": loan_party, "contract": "2025-0882", "split": True, "principal": 72 * M,
                  "interest": int(round(interest[i] * M)), "day": 15, "contract_date": "12.09.2025"}]
        cwm = cw.copy()
        if m >= 8:  # Dilshod Trade stops paying (overdue receivable)
            cwm[2] = 0
            cwm = cwm / cwm.sum()
        txns += month_txns(ctx, 2026, m, sales=int(round(NAV_IN[i] * M)), suppliers=suppliers_total,
                           payroll_net=int(round(salary[i] * M)),
                           payroll_taxes=(int(round(ptax[i][0] * M)), int(round(ptax[i][1] * M))),
                           rent=16 * M, electricity=int(round(elec[i] * M)), gas=int(round(gas[i] * M)),
                           water=int(round(water[i] * M)), profit_tax=int(round(profit_tax.get(m, 0) * M)),
                           loans=loans, bank_fee=int(fee * M), customer_weights=cwm, supplier_weights=sw,
                           n_sales=NAV_N_SALES[i], n_suppliers=NAV_N_SUP[i], extra=extra)
    # salaries go on the 5th; payroll taxes on the 20th (design: "Recurring, 20th of month")
    for t_ in txns:
        if t_.category == "payroll_tax":
            t_.d = date(2026, t_.d.month, 20)
    assign_recurring(txns)
    opening = int(NAV_OPEN * M)
    st = write_statement(out / "bank_vypiska_2026-01_09.xlsx", c, txns, opening, date(2026, 1, 1), date(2026, 9, 30),
                         layout="B", lang="uz_latn")
    ends = [round(st["month_end_balances"][f"2026-{m:02d}"] / M, 1) for m in range(1, 10)]
    assert ends == NAV_END, ends
    assert len(st["rows"]) == 2418, len(st["rows"])
    docs.append({"file": "bank_vypiska_2026-01_09.xlsx", "doc_type": "bank_statement",
                 "period": {"start": "2026-01-01", "end": "2026-09-30"}, "variant": {"layout": "B"}})
    v = invoice_photo(out / "schet-faktura_0917.jpg", rng, c, "Dilshod Trade MChJ, STIR 307230614", "0917", date(2026, 9, 17))
    docs.append({"file": "schet-faktura_0917.jpg", "doc_type": "invoice", "period": None, "variant": v})
    sep = [r for r in st["rows"] if r["date"].startswith("2026-09")]
    by = {}
    for r in sep:
        by[r["category"]] = by.get(r["category"], 0) + r["amount"]
    truth = {
        "bundle_id": "hero_navroz", "owner_user": "SN",
        "company": {"name": c.name, "stir": c.stir, "industry": c.industry, "region": c.region, "employees": c.employees},
        "documents": [{k: v for k, v in d.items() if k != "pages"} | {"page_count": d.get("pages", 1)} for d in docs],
        "transactions": st,
        "pinned_design_values": {
            "month_end_cash_mln": dict(zip([f"2026-{m:02d}" for m in range(1, 10)], ends)),
            "cash_in_mln": dict(zip([f"2026-{m:02d}" for m in range(1, 10)], NAV_IN)),
            "cash_out_mln": dict(zip([f"2026-{m:02d}" for m in range(1, 10)], NAV_OUT)),
            "sep_outflows_by_category_mln": {k: round(-v / M, 1) for k, v in by.items() if v < 0},
            "sep_waterfall_design": {"suppliers_materials": 484.3, "salaries": 298.4, "yarn_prepayment": 185.0,
                                     "loan_installment": 96.0, "taxes_contributions": 71.2, "rent_utilities": 58.6},
            "loan": {"contract": "2025-0882", "principal_monthly": 72.0, "interest_sep": 24.0, "due_day": 15},
            "uncategorised_rows_expected": 14,
        },
        "notes": ["Monthly revenue Apr-Sep in demo-data comes from management accounts; the documents here carry only "
                  "F2 H1-2026 and the cash statement, so Jul-Sep revenue can only be estimated from cash (design marks it 'estimate')."],
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return truth


# ------------------------------------------------------------------------------------------- Zilola
ZILOLA = Company(
    name="Zilola Mebel MChJ", stir="304882571", industry_key="furniture", industry="Furniture manufacturing (kitchen & office)",
    region="Samarqand", bank="Zarafshon Kredit Bank", mfo="00987", account="20208000500882571001",
    director="Qodirov B.", accountant="Sobirova N.", employees=37, since=2016,
    address="Samarqand sh., Spitamen shoh ko'chasi, 41-uy")
ZIL_F2 = {
    # standalone quarters (bank monitoring format); prior-year quarters are the statutory comparison column
    "Q2-2025": {"010": 1_612_400, "020": 921_000, "050": 108_200, "060": 198_700, "070": 27_100, "250": 53_610},
    "Q3-2025": {"010": 1_701_300, "020": 968_900, "050": 110_500, "060": 203_100, "070": 28_400, "250": 58_560},
    "Q1-2026": {"010": 1_736_118, "020": 993_500, "050": 121_000, "060": 216_400, "070": 32_400, "180": 24_700, "250": 52_218},
    "Q2-2026": {"010": 1_790_212, "020": 1_020_310, "050": 118_600, "060": 211_500, "070": 29_800, "180": 25_000, "250": 57_750},
    "Q3-2026": {"010": 1_289_046, "020": 1_006_410, "050": 120_412, "060": 214_806, "070": 30_404, "090": 6_190, "180": 25_204, "250": 0},
}
_ZIL_COMMON = {"020": 12_000, "410": 300_000, "430": 30_000, "330": 0, "690": 3_200, "700": 6_900, "720": 22_400}
ZIL_F1_LEAVES = {
    "2025-12-31": {**_ZIL_COMMON, "010": 2_812_000, "011": 520_100, "021": 3_800, "150": 305_200, "160": 61_000, "170": 128_400,
                   "190": 8_600, "220": 262_040, "260": 44_100, "270": 5_800, "310": 3_000, "340": 198_000, "570": 1_086_000,
                   "610": 205_900, "670": 19_400, "680": 36_900, "760": 9_100},
    "2026-03-31": {**_ZIL_COMMON, "010": 2_840_000, "011": 557_600, "021": 4_400, "150": 318_400, "160": 64_200, "170": 141_300,
                   "190": 8_200, "220": 274_120, "260": 41_300, "270": 6_100, "310": 3_200, "340": 176_000, "570": 970_800,
                   "610": 212_400, "670": 18_200, "680": 38_400, "760": 9_700},
    "2026-06-30": {**_ZIL_COMMON, "010": 2_846_500, "011": 595_100, "021": 5_000, "150": 326_100, "160": 66_900, "170": 152_600,
                   "190": 7_900, "220": 286_040, "260": 39_800, "270": 6_400, "310": 3_100, "340": 150_100, "570": 855_600,
                   "610": 220_300, "670": 16_900, "680": 41_200, "760": 10_200},
    "2026-09-30": {**_ZIL_COMMON, "010": 2_851_200, "011": 632_600, "021": 5_600, "150": 372_800, "160": 71_300, "170": 170_000,
                   "190": 7_600, "220": 403_260, "260": 22_400, "270": 6_900, "310": 3_500, "340": 65_500, "570": 740_400,
                   "610": 231_900, "670": 9_800, "680": 12_600, "760": 12_400},
}
ZIL_CASH = {"open_q3": 150.1, "ends_q3": [118.4, 108.0, 65.5], "in_q3": [452.0, 430.0, 378.0],
            "open_q2": 176.0, "ends_q2": [168.2, 157.6, 150.1], "in_q2": [612.0, 598.4, 604.6]}
CHAIN = ("Samarqand Uy Jihozlari MChJ", "303770915")


def _close(leaf: dict) -> dict:
    """Close the balance: a shortfall of assets becomes capital investments in progress (100), a surplus other payables (760)."""
    leaf = dict(leaf, **{"100": 0})
    v = f1_totals(leaf)
    gap = v["780"] - v["400"]
    if gap >= 0:
        leaf["100"] = gap
    else:
        leaf["760"] = leaf.get("760", 0) - gap
    v = f1_totals(leaf)
    assert v["400"] == v["780"]
    return v


def zilola_f1() -> tuple[dict, dict]:
    """31.12.2025 closes via retained earnings; each quarter then rolls RE by that quarter's net profit."""
    f2 = {k: f2_totals(v) for k, v in ZIL_F2.items()}
    out = {"2025-12-31": _plug_re(ZIL_F1_LEAVES["2025-12-31"])}
    re = out["2025-12-31"]["450"]
    for d, q in (("2026-03-31", "Q1-2026"), ("2026-06-30", "Q2-2026"), ("2026-09-30", "Q3-2026")):
        re += f2[q]["270"]
        out[d] = _close(dict(ZIL_F1_LEAVES[d], **{"450": re}))
    return out, f2


def build_zilola(root: Path) -> dict:
    out = root / "hero_zilola"
    if out.exists():
        shutil.rmtree(out)
    (out / "history").mkdir(parents=True)
    rng = np.random.default_rng(9003)
    c = ZILOLA
    f1, f2 = zilola_f1()
    q3, q2 = f2["Q3-2026"], f2["Q2-2026"]
    assert round(q3["010"] / 1000) == 1289 and round(q2["010"] / 1000) == 1790
    assert q3["270"] == -102_000, q3["270"]
    assert round((q3["010"] / q2["010"] - 1) * 100, 1) == -28.0
    assert round(f1["2026-09-30"]["220"] / f1["2026-06-30"]["220"] - 1, 2) == 0.41
    assert f1["2026-09-30"]["210"] / f1["2026-06-30"]["210"] - 1 >= 0.25
    docs = []
    # statutory convention: Form 1 prev = 31.12 of the prior year; Form 2 prev = same quarter of the prior year
    for fname, form, cur, prev, when, sub in [
        ("forma1_Q2-2026.pdf", "form1", f1["2026-06-30"], f1["2025-12-31"], date_phrase("ru", date(2026, 6, 30)), date(2026, 7, 6)),
        ("forma2_Q2-2026.pdf", "form2", q2, f2["Q2-2025"], period_phrase("ru", "Q2-2026"), date(2026, 7, 6)),
        ("forma1_Q3-2026.pdf", "form1", f1["2026-09-30"], f1["2025-12-31"], date_phrase("ru", date(2026, 9, 30)), date(2026, 10, 1)),
        ("forma2_Q3-2026.pdf", "form2", q3, f2["Q3-2025"], period_phrase("ru", "Q3-2026"), date(2026, 10, 1)),
    ]:
        t = render_form(out / fname, form, "ru", "software_export" if form == "form2" else "mof_grid", c, title_when=when,
                        cur=cur, prev=prev, submitted=sub)
        q = "Q2" if "Q2" in fname else "Q3"
        ps = {"Q2": ("2026-04-01", "2026-06-30"), "Q3": ("2026-07-01", "2026-09-30")}[q]
        prev_period = ("2025-12-31" if form == "form1" else f"{q}-2025")
        docs.append({"file": fname, "doc_type": form, "period": {"start": ps[0], "end": ps[1]},
                     "standalone_quarter": form == "form2", "prev_column": prev_period, **t, "variant": {"scan": False}})

    def quarter_statement(months, opening, ends, inflows, chain_receipts, fname, late_sep: bool):
        ctx = make_ctx(rng, c, lang="ru", n_customers=22, n_suppliers=9)
        ctx.customers[0] = party_from(rng, *CHAIN)
        loan_acct = Party("Kreditni qaytarish hisobvarag'i (L-2025-0417)", None, "16307000500882571417", c.mfo)
        txns = []
        bal = opening
        for i, m in enumerate(months):
            due = date(2026, m, 15)
            paid = date(2026, 9, 17) if (late_sep and m == 9) else (date(2026, 8, 14) if m == 8 else due)
            extra = [Txn(paid, -46_800_000, loan_acct, f"Kredit shartnomasi L-2025-0417 bo'yicha navbatdagi to'lov ({m:02d}.2026)",
                         "loan_repayment", group="loan:L-2025-0417", meta={"fixed": True, "due": due.isoformat()})]
            chain = int(round(chain_receipts[i] * M))
            others = int(round(inflows[i] * M)) - chain
            for k, amt in enumerate([chain // 2, chain - chain // 2] if chain else []):
                dd = date(2026, m, 6 + 12 * k)
                extra.append(Txn(dd, amt, ctx.customers[0], ctx.grammar.render("sales_receipt", d=dd), "sales_receipt",
                                 meta={"fixed": True}))
            cw = np.array([0.0] + list(rng.pareto(1.3, 21) + 0.2)); cw = cw / cw.sum()
            month_out = int(round((bal + inflows[i] - ends[i]) * M))
            fixed = 46_800_000 + 92_500_000 + 2 * 12_600_000 + 9_000_000 + 5_100_000 + 1_900_000 + 400_000 + 600_000
            vat = int(round(rng.uniform(6, 12) * M, -3))
            sup = month_out - fixed - vat
            assert sup > 0, (m, sup)
            txns += month_txns(ctx, 2026, m, sales=others, suppliers=sup, payroll_net=92_500_000,
                               payroll_taxes=(12_600_000, 12_600_000), rent=9_000_000, electricity=5_100_000,
                               gas=1_900_000, water=400_000, vat=vat, bank_fee=600_000, customer_weights=cw,
                               n_sales=int(rng.integers(38, 55)), n_suppliers=int(rng.integers(18, 28)), extra=extra)
            bal = ends[i]
        assign_recurring(txns)
        st = write_statement(out / fname, c, txns, int(round(opening * M)), date(2026, months[0], 1),
                             date(2026, months[-1], {6: 30, 9: 30}[months[-1]]), layout="A", lang="ru")
        got = [round(st["month_end_balances"][f"2026-{m:02d}"] / M, 1) for m in months]
        assert got == ends, (fname, got)
        return st
    st3 = quarter_statement([7, 8, 9], ZIL_CASH["open_q3"], ZIL_CASH["ends_q3"], ZIL_CASH["in_q3"], [120.4, 52.0, 17.6],
                            "vypiska_2026-07_09.xlsx", late_sep=True)
    st2 = quarter_statement([4, 5, 6], ZIL_CASH["open_q2"], ZIL_CASH["ends_q2"], ZIL_CASH["in_q2"], [236.0, 224.0, 230.0],
                            "history/vypiska_2026-04_06.xlsx", late_sep=False)
    docs.append({"file": "vypiska_2026-07_09.xlsx", "doc_type": "bank_statement", "period": {"start": "2026-07-01", "end": "2026-09-30"}, "variant": {"layout": "A"}})
    docs.append({"file": "history/vypiska_2026-04_06.xlsx", "doc_type": "bank_statement", "period": {"start": "2026-04-01", "end": "2026-06-30"}, "variant": {"layout": "A"}})
    cash = f1["2026-09-30"]["340"]
    truth = {
        "bundle_id": "hero_zilola", "loan_id": "L-2025-0417",
        "company": {"name": c.name, "stir": c.stir, "industry": c.industry, "region": c.region, "employees": c.employees, "since": c.since},
        "column_convention": "statutory: Form 1 prev = 31.12.2025 (beginning of the reporting year); Form 2 prev = same quarter of 2025. "
                             "Quarter-over-quarter comparison (M01, M02) = Q3 documents vs Q2 documents.",
        "documents": [{k: v for k, v in d.items() if k != "pages"} | {"page_count": d.get("pages", 1)} for d in docs],
        "transactions": st3, "transactions_history": st2,
        "loan": {"installment_kuzs": 46_800, "due_day": 15, "late": [{"n": 11, "due": "2026-09-15", "paid": "2026-09-17", "days_late": 2}]},
        "pinned_design_values": {
            "revenue_q2_q3_mln": [round(q2["010"] / 1000), round(q3["010"] / 1000)],
            "revenue_change_pct": round((q3["010"] / q2["010"] - 1) * 100, 1),
            "costs_q2_q3_mln": [round((q2["010"] - q2["240"]) / 1000), round((q3["010"] - q3["240"]) / 1000)],
            "q3_loss_mln": q3["270"] / 1000,
            "receivables_q4_q1_q2_q3_mln": [round(f1[d]["220"] / 1000) for d in ("2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30")],
            "receivables_change_pct": round((f1["2026-09-30"]["220"] / f1["2026-06-30"]["220"] - 1) * 100),
            "cash_end_q4_q1_q2_q3_mln": [f1[d]["340"] / 1000 for d in ("2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30")],
            "cash_coverage_q3": round(cash / 46_800, 2), "cash_coverage_q2": round(f1["2026-06-30"]["340"] / 46_800, 2),
            "chain_receipts_q3_mln": 190.0,
        },
        "expected_indicators": {"M01": True, "M02": True, "M03": False, "M04": True, "M05": True, "M06": False},
        "scenario": "attn",
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return truth


def build_heroes(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for fn in (build_farovon, build_navroz, build_zilola):
        t = fn(root)
        print(t["bundle_id"], "ok", len(t["documents"]), "documents")
