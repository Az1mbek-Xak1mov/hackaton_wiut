"""Loan book (148 borrowers) + per-borrower monitoring bundles + seeded applications.

Statuses are NOT stored as data: each bundle's truth.json carries the scenario parameters it was
generated from; the monitoring run computes the status from the documents.
"""
from __future__ import annotations

import csv
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from .company import INDUSTRIES, REGIONS, make_company
from .finmodel import make_fin, split_inventory
from .pdf_forms import date_phrase, period_phrase, render_form
from .statement import Party, Txn, assign_recurring, balance_to_target, make_ctx, month_txns, write_statement
from .totals import f1_totals

ROOT = Path(__file__).resolve().parents[2]

# demo-data bank.borrowers, with the deviations needed for the disclosed rules (see notes in manifest)
NAMED = [
    dict(loan_id="L-2025-0417", name="Zilola Mebel MChJ", industry_key="furniture", industry="Furniture manufacturing", region="Samarqand",
         original=1200.0, term=36, outstanding=740.4, trend=-28.0, coverage=1.4, scenario="attn", indicators=["M01", "M02", "M04", "M05"], hero=True),
    dict(loan_id="L-2024-0288", name="Qarshi Don Mahsulotlari MChJ", industry_key="bakery", industry="Grain products", region="Qashqadaryo",
         original=1800.0, term=48, outstanding=1075.0, trend=-12.6, coverage=1.47, scenario="attn", indicators=["M03", "M04"], pay_growth=0.44),
    dict(loan_id="L-2025-0102", name="Nukus Qurilish MChJ", industry_key="construction", industry="Construction", region="Qoraqalpog'iston",
         original=4200.0, term=60, outstanding=3200.0, trend=-7.9, coverage=1.8, scenario="watch", indicators=["M02"], recv_growth=0.38),
    dict(loan_id="L-2025-0233", name="Jizzax Yog' Zavodi MChJ", industry_key="oil", industry="Oil processing", region="Jizzax",
         original=1600.0, term=36, outstanding=1320.0, trend=None, coverage=2.1, scenario="watch", indicators=["M06"], late_statement=True),
    dict(loan_id="L-2025-0391", name="Oltin Vodiy Konserva MChJ", industry_key="food_dist", industry="Food processing", region="Farg'ona",
         original=1100.0, term=36, outstanding=980.0, trend=-0.8, coverage=2.2, scenario="watch", indicators=["M02"], recv_growth=0.36,
         deviation="design trend +4.1%; set to -0.8% so M02 (receivables +25% while revenue <= 0%) is the single indicator"),
    dict(loan_id="L-2025-0315", name="Chimgan Tur Servis MChJ", industry_key="tourism", industry="Tourism services", region="Tashkent region",
         original=600.0, term=24, outstanding=455.0, trend=-19.5, coverage=1.6, scenario="watch", indicators=["M01"],
         deviation="design coverage 1.2x; set to 1.6x, otherwise M01+M04 => Attention under the disclosed rules"),
    dict(loan_id="L-2024-0510", name="Farg'ona Taxi Park MChJ", industry_key="transport", industry="Passenger transport", region="Farg'ona",
         original=450.0, term=36, outstanding=288.5, trend=6.8, coverage=1.4, scenario="watch", indicators=["M04"], late_months=[4, 5],
         deviation="design coverage 1.6x and late installments caught up in Sep; late payments moved to Apr/May (outside the last 3) "
                   "and coverage set to 1.4x so exactly one indicator (M04) fires"),
    dict(loan_id="L-2025-0044", name="Namangan Meva Eksport MChJ", industry_key="fruit_export", industry="Fruit export", region="Namangan",
         original=2500.0, term=36, outstanding=2140.0, trend=38.4, coverage=4.1, scenario="stable", indicators=[]),
    dict(loan_id="L-2024-0197", name="Buxoro Gilam MChJ", industry_key="textile", industry="Carpet manufacturing", region="Buxoro",
         original=2400.0, term=48, outstanding=1850.0, trend=11.2, coverage=3.4, scenario="stable", indicators=[]),
    dict(loan_id="L-2025-0276", name="Toshkent Plastik MChJ", industry_key="plastics", industry="Plastics manufacturing", region="Tashkent",
         original=800.0, term=30, outstanding=612.0, trend=2.3, coverage=2.9, scenario="stable", indicators=[]),
    dict(loan_id="L-2025-0358", name="Urganch Sut MChJ", industry_key="dairy", industry="Dairy", region="Xorazm",
         original=650.0, term=36, outstanding=520.0, trend=1.9, coverage=2.7, scenario="stable", indicators=[]),
    dict(loan_id="L-2025-0129", name="Andijon Avto Ehtiyot MChJ", industry_key="auto_parts", industry="Auto parts retail", region="Andijon",
         original=500.0, term=24, outstanding=396.0, trend=-3.1, coverage=2.5, scenario="stable", indicators=[]),
]
GEN_MIX = {"stable": 116, "W_rev": 4, "W_recv": 3, "W_pay": 2, "W_cov": 2, "W_stmt": 2,
           "A_rev_cov": 2, "A_late": 3, "A_pay_cov": 1, "A_rev_recv": 1}
GROUP_SUM = {"stable": 68_800.0, "watch": 11_400.0, "attn": 6_200.0}   # mln UZS (demo-data statusDistribution)


def _status_of(s: str) -> str:
    if s in ("stable", "watch", "attn"):
        return s
    return "watch" if s.startswith("W") else "attn"


def scenario_params(rng, s: str) -> dict:
    p = dict(trend=float(rng.uniform(-10, 25)), coverage=float(rng.uniform(2.0, 6.0)), recv_growth=float(rng.uniform(-0.1, 0.12)),
             pay_growth=float(rng.uniform(-0.1, 0.15)), late_months=[], late_statement=False, indicators=[])
    if s == "W_rev":
        p.update(trend=float(rng.uniform(-30, -16)), indicators=["M01"])
    elif s == "W_recv":
        p.update(trend=float(rng.uniform(-10, -0.5)), recv_growth=float(rng.uniform(0.3, 0.5)), indicators=["M02"])
    elif s == "W_pay":
        p.update(pay_growth=float(rng.uniform(0.45, 0.7)), indicators=["M03"])
    elif s == "W_cov":
        p.update(coverage=float(rng.uniform(0.7, 1.4)), indicators=["M04"])
    elif s == "W_stmt":
        p.update(late_statement=True, indicators=["M06"])
    elif s == "A_rev_cov":
        p.update(trend=float(rng.uniform(-35, -17)), coverage=float(rng.uniform(0.5, 1.35)), indicators=["M01", "M04"])
    elif s == "A_late":
        p.update(late_months=[int(rng.choice([7, 8, 9]))], indicators=["M05"])
    elif s == "A_pay_cov":
        p.update(pay_growth=float(rng.uniform(0.45, 0.8)), coverage=float(rng.uniform(0.6, 1.3)), indicators=["M03", "M04"])
    elif s == "A_rev_recv":
        p.update(trend=float(rng.uniform(-30, -18)), recv_growth=float(rng.uniform(0.3, 0.5)), indicators=["M01", "M02"])
    return p


def outstanding_values(rng, groups: dict[str, int], named: list[dict]) -> dict[str, list[float]]:
    """Generated outstanding amounts per status group.

    Hits the group sums exactly, makes 4 200.0 the largest loan and puts two loans at exactly 412.0 so that the
    portfolio median is 412.0 (73 loans below, 73 above) as in demo-data.
    """
    slots = {"stable": (62, 2, 52), "watch": (6, 0, 7), "attn": (3, 0, 4)}   # below, at-median, above
    out = {}
    for g, n in groups.items():
        below_n, mid_n, above_n = slots[g]
        assert below_n + mid_n + above_n == n
        target = GROUP_SUM[g] - sum(b["outstanding"] for b in named if b["scenario"] == g)
        below = np.round(np.clip(np.exp(rng.normal(np.log(230), 0.45, below_n)), 60, 405), 1)
        mids = [412.0] * mid_n
        fixed_top = [4200.0] if g == "stable" else []
        k = above_n - len(fixed_top)
        above = np.exp(rng.normal(np.log(800), 0.6, k))
        rest = target - below.sum() - sum(mids) - sum(fixed_top)
        for _ in range(100):
            above = np.clip(above * rest / above.sum(), 420, 3900)
        above = np.round(above, 1)
        above[np.argmax(above)] = round(above[np.argmax(above)] + rest - above.sum(), 1)
        vals = list(below) + mids + list(above) + fixed_top
        assert abs(sum(vals) - target) < 0.05, (g, sum(vals), target)
        out[g] = [float(v) for v in vals]
    return out


def annuity(principal: float, rate: float, n: int) -> float:
    r = rate / 12
    return principal * r / (1 - (1 + r) ** -n)


def loan_terms(rng, outstanding: float, term: int | None = None, original: float | None = None) -> dict:
    term = term or int(rng.choice([24, 30, 36, 48, 60]))
    rate = float(rng.choice([0.21, 0.22, 0.23, 0.24]))
    paid = int(rng.integers(3, min(term - 3, 30)))
    r = rate / 12
    if original is not None:  # choose the number of paid installments that best explains the outstanding balance
        def bal(k):
            return original * ((1 + r) ** term - (1 + r) ** k) / ((1 + r) ** term - 1)
        paid = min(range(1, min(term - 1, 34)), key=lambda k: abs(bal(k) - outstanding))
    if original is None:
        original = outstanding * ((1 + r) ** term - 1) / ((1 + r) ** term - (1 + r) ** paid)
        original = round(original, -1)
    inst = round(annuity(original, rate, term), 1)
    # disbursed so that `paid` installments fall due on or before 2026-09
    y, m = 2026, 9
    for _ in range(paid):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return dict(term=term, rate=rate, paid=paid, original=round(original, 1), installment=inst, disbursed=date(y, m, int(rng.integers(5, 26))))


def repayments(disbursed: date, paid: int, due_day: int, late: dict[int, int]) -> list[dict]:
    out = []
    y, m = disbursed.year, disbursed.month
    for n in range(1, paid + 1):
        m += 1
        if m == 13:
            y, m = y + 1, 1
        due = date(y, m, min(due_day, 28))
        days = late.get(m if y == 2026 else -1, 0)
        out.append({"n": n, "due": due.isoformat(), "paid": date.fromordinal(due.toordinal() + days).isoformat(), "days_late": days})
    return out


def build_borrower(args) -> dict:
    """Generate one monitoring bundle (Q3 forms + Jul-Sep statement) for a borrower row."""
    b, out_root = args
    rng = np.random.default_rng(b["seed"])
    out = Path(out_root) / b["loan_id"]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if b.get("hero"):
        src = ROOT / "data" / "seed" / "hero_zilola"
        for f in ("forma1_Q2-2026.pdf", "forma2_Q2-2026.pdf", "forma1_Q3-2026.pdf", "forma2_Q3-2026.pdf", "vypiska_2026-07_09.xlsx"):
            shutil.copy(src / f, out / f)
        (out / "truth.json").write_text(json.dumps({"loan_id": b["loan_id"], "hero": "hero_zilola", "scenario": b["scenario"],
                                                    "indicators": b["indicators"]}, indent=1))
        return {"loan_id": b["loan_id"], "docs": 5}
    company = make_company(rng, b["industry_key"], name=b["name"], stir=b["stir"], region=b["region"], industry=b["industry"])
    inst_k = b["installment"] * 1000                     # kUZS
    annual = max(inst_k * 12 * rng.uniform(5, 14), 1.5e6)
    base = make_fin(np.random.default_rng(b["seed"] + 7), company, annual_rev=annual)
    r0 = base.f2["Q3-2026"]["010"] / base.f2["Q2-2026"]["010"]
    trend = b["trend"] if b["trend"] is not None else float(rng.uniform(-5, 8))
    shock = (1 + trend / 100) / r0 - 1
    fin = make_fin(np.random.default_rng(b["seed"] + 7), company, annual_rev=annual, q3_shock=shock)
    q2, q3 = fin.f2["Q2-2026"], fin.f2["Q3-2026"]
    late_stmt = b.get("late_statement")
    cov = b["coverage"]
    cash_q3 = int(round(cov * inst_k, -2))
    cash_q2 = int(round(inst_k * (cov * rng.uniform(1.05, 1.6) if _status_of(b["scenario"]) != "stable" else cov * rng.uniform(0.85, 1.2)), -2))
    f1q2 = dict(fin.f1["2026-06-30"]); f1q3 = dict(fin.f1["2026-09-30"])

    def fix(v: dict, cash: int, recv: int | None, pay: int | None, lt: int) -> dict:
        leaf = {c: v[c] for c in v if c not in ("012", "022", "130", "140", "210", "320", "390", "400", "480", "490", "600", "770", "780")}
        leaf["330"], leaf["340"], leaf["350"] = 0, cash, 0
        if recv is not None:
            leaf["220"] = recv
        if pay is not None:
            leaf["610"] = pay
        leaf["570"], leaf["580"], leaf["730"] = lt, 0, 0
        t = f1_totals(leaf)
        diff = t["400"] - t["780"]
        if diff > 0:
            leaf["760"] += diff
        else:  # the loan financed equipment: the asset side grows in fixed assets
            leaf["010"] += -diff
        t = f1_totals(leaf)
        assert t["400"] == t["780"]
        return t

    lt_q3 = int(round(b["outstanding"] * 1000))
    princ = inst_k * 0.7
    lt = {"2026-09-30": lt_q3, "2026-06-30": int(round(lt_q3 + 3 * princ)), "2026-03-31": int(round(lt_q3 + 6 * princ)),
          "2025-12-31": int(round(lt_q3 + 9 * princ))}
    recv_q2, pay_q2 = f1q2["220"], f1q2["610"]
    # retained earnings come from the model, which rolls them quarter by quarter by net profit
    bal = {
        "2025-12-31": fix(dict(fin.f1["2025-12-31"]), fin.f1["2025-12-31"]["340"], None, None, lt["2025-12-31"]),
        "2026-03-31": fix(dict(fin.f1["2026-03-31"]), int(round(cash_q2 * rng.uniform(1.0, 1.25), -2)), None, None, lt["2026-03-31"]),
        "2026-06-30": fix(f1q2, cash_q2, recv_q2, pay_q2, lt["2026-06-30"]),
        "2026-09-30": fix(f1q3, cash_q3, int(round(recv_q2 * (1 + b["recv_growth"]))), int(round(pay_q2 * (1 + b["pay_growth"]))), lt_q3),
    }
    v_q2, v_q3 = bal["2026-06-30"], bal["2026-09-30"]
    docs = []
    lang = "ru" if rng.random() < 0.6 else "uz_latn"
    layout = str(rng.choice(["mof_grid", "software_export", "typed"]))
    # statutory convention: Form 1 prev column = 31.12.2025; Form 2 prev column = the same quarter of 2025.
    # Quarter-over-quarter monitoring compares the two latest quarters' documents.
    quarters = [("Q1", "2026-03-31", date(2026, 4, 7)), ("Q2", "2026-06-30", date(2026, 7, 8))] if late_stmt else \
               [("Q2", "2026-06-30", date(2026, 7, 8)), ("Q3", "2026-09-30", date(2026, 10, 5))]
    for q, dkey, signed in quarters:
        f1n, f2n = f"forma1_{q}-2026.pdf", f"forma2_{q}-2026.pdf"
        render_form(out / f1n, "form1", lang, layout, company, title_when=date_phrase(lang, date.fromisoformat(dkey)),
                    cur=bal[dkey], prev=bal["2025-12-31"], submitted=signed)
        render_form(out / f2n, "form2", lang, layout, company, title_when=period_phrase(lang, f"{q}-2026"),
                    cur=fin.f2[f"{q}-2026"], prev=fin.f2[f"{q}-2025"], submitted=signed)
        docs += [f1n, f2n]
    months = [7, 8] if late_stmt else [7, 8, 9]
    # statement Jul-Sep (or Jul-Aug)
    ctx = make_ctx(rng, company, lang="ru" if lang == "ru" else "uz", n_customers=int(rng.integers(5, 18)), n_suppliers=int(rng.integers(4, 12)))
    loan_acct = Party(f"Kreditni qaytarish hisobvarag'i ({b['loan_id']})", None, "16307000" + b["stir"][:9] + "417", company.mfo)
    txns = []
    for m in months:
        mo = fin.monthly[(2026, m)]
        due = date(2026, m, b["due_day"])
        days_late = b["late"].get(m, 0)
        extra = [Txn(date.fromordinal(due.toordinal() + days_late), -int(round(b["installment"] * 1e6)), loan_acct,
                     f"Kredit shartnomasi {b['loan_id']} bo'yicha navbatdagi to'lov ({m:02d}.2026)", "loan_repayment",
                     group=f"loan:{b['loan_id']}", meta={"fixed": True, "due": due.isoformat(), "days_late": days_late})]
        sales = int(round(mo["rev"] * 1000 * 1.12 * rng.normal(0.985, 0.02), -3))
        payroll = int(round(mo["rev"] * 1000 * fin.params["payroll_share"], -3))
        txns += month_txns(ctx, 2026, m, sales=sales, suppliers=int(round(mo["cogs"] * 1000 * 1.1, -3)), payroll=payroll,
                           rent=int(round(mo["rev"] * 1000 * 0.008, -3)), electricity=int(round(mo["rev"] * 1000 * 0.005, -3)),
                           vat=int(round(sales * 0.012, -3)), bank_fee=300_000, n_sales=int(rng.integers(15, 45)),
                           n_suppliers=int(rng.integers(8, 22)), extra=extra)
    opening = v_q2["340"] * 1000
    end = date(2026, months[-1], 31 if months[-1] == 8 else 30)
    target = (v_q3["340"] * 1000) if not late_stmt else int(round(cash_q3 * 1000))
    balance_to_target(txns, opening, target, end, rng)
    assign_recurring(txns)
    fname = f"vypiska_2026-07_{months[-1]:02d}.xlsx"
    st = write_statement(out / fname, company, txns, opening, date(2026, 7, 1), end, layout=str(rng.choice(["A", "B"])), lang=lang)
    docs.append(fname)
    truth = {
        "loan_id": b["loan_id"], "company": {"name": company.name, "stir": company.stir, "industry": company.industry,
                                             "region": company.region},
        "scenario": b["scenario"], "expected_status_under_disclosed_rules": _status_of(b["scenario"]),
        "expected_indicators": b["indicators"],
        "params": {"trend_pct": round(((q2["010"] / fin.f2["Q1-2026"]["010"]) if late_stmt else (q3["010"] / q2["010"])) * 100 - 100, 1),
                   "trend_basis": "Q2 vs Q1 documents" if late_stmt else "Q3 vs Q2 documents",
                   "coverage": round(target / 1000 / inst_k, 2),
                   "receivables_growth": round(v_q3["220"] / v_q2["220"] - 1, 3) if not late_stmt else None,
                   "payables_growth": round(v_q3["610"] / v_q2["610"] - 1, 3) if not late_stmt else None,
                   "late": b["late"], "late_statement": bool(late_stmt), "installment_mln": b["installment"]},
        "column_convention": "Form 1 prev = 31.12.2025; Form 2 prev = same quarter of 2025; QoQ = latest vs previous quarter documents",
        "documents": docs, "statement": {k: st[k] for k in ("opening_balance", "closing_balance", "month_end_balances")},
        "statement_rows": len(st["rows"]), "language": lang, "layout": layout,
    }
    if b.get("deviation"):
        truth["deviation_from_design"] = b["deviation"]
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"loan_id": b["loan_id"], "docs": len(docs)}


def build_loan_book(rng) -> list[dict]:
    rows = []
    groups = {"stable": 116, "watch": 13, "attn": 7}
    outs = outstanding_values(rng, groups, NAMED)
    gen_scen = []
    for s, n in GEN_MIX.items():
        gen_scen += [s] * n
    rng.shuffle(gen_scen)
    used_names = {b["name"] for b in NAMED}
    used_ids = {b["loan_id"] for b in NAMED}
    seed = 10_000
    for b in NAMED:
        b = {"recv_growth": float(rng.uniform(-0.05, 0.1)), "pay_growth": float(rng.uniform(-0.05, 0.12)),
             "late_months": [], "late_statement": False, **b}
        lt = loan_terms(rng, b["outstanding"], b["term"], b["original"])
        if b["loan_id"] == "L-2025-0417":
            lt.update(installment=46.8, paid=11, disbursed=date(2025, 10, 15), term=36, original=1200.0)
        rows.append({**b, **lt, "seed": seed, "stir": "304882571" if b.get("hero") else make_company(rng).stir})
        seed += 1
    pools = {g: list(v) for g, v in outs.items()}
    for s in gen_scen:
        g = _status_of(s)
        o = float(pools[g].pop())
        key = str(rng.choice(list(INDUSTRIES)))
        c = make_company(rng, key)
        while c.name in used_names:
            c = make_company(rng, key)
        used_names.add(c.name)
        p = scenario_params(rng, s)
        lt = loan_terms(rng, o)
        loan_id = f"L-{int(rng.choice([2024, 2025]))}-{int(rng.integers(1000, 9999)):04d}"
        while loan_id in used_ids:
            loan_id = f"L-{int(rng.choice([2024, 2025]))}-{int(rng.integers(1000, 9999)):04d}"
        used_ids.add(loan_id)
        rows.append(dict(loan_id=loan_id, name=c.name, industry_key=key, industry=c.industry, region=c.region,
                         outstanding=round(o, 1), scenario=s, stir=c.stir, seed=seed, **p, **lt))
        seed += 1
    for r in rows:
        r["due_day"] = 15 if r["loan_id"] == "L-2025-0417" else int(rng.choice([5, 10, 15, 20, 25]))
        late = {}
        if r["loan_id"] == "L-2025-0417":
            late = {9: 2}
        for m in r.get("late_months") or []:
            late[m] = int(rng.integers(2, 10))
        r["late"] = late
        r["repayments"] = repayments(r["disbursed"], r["paid"], r["due_day"], late)
        if r["loan_id"] == "L-2025-0417":
            r["repayments"][-1].update(paid="2026-09-17", days_late=2)
    return rows


def build_applications(root: Path) -> list[dict]:
    """The six queued applications in demo-data; Farovon is the hero bundle, the rest are generated."""
    from .bundle import make_bundle
    apps = [
        dict(id="APP-2026-0925", name="Nurafshon Agro Servis MChJ", industry_key="agro", requested=310_000, term=12, received=date(2026, 10, 1), planted=["R07"], drop=set()),
        dict(id="APP-2026-0928", name="Oqtosh Qurilish Materiallari MChJ", industry_key="construction", requested=1_500_000, term=36, received=date(2026, 10, 3), planted=[], drop={"statement_2026-01_08.xlsx", "form2_H1-2026.pdf"}),
        dict(id="APP-2026-0933", name="Chirchiq Metall Servis MChJ", industry_key="metal", requested=960_000, term=24, received=date(2026, 10, 7), planted=[], drop=set()),
        dict(id="APP-2026-0934", name="Samarqand Non Kombinati MChJ", industry_key="bakery", requested=420_000, term=18, received=date(2026, 10, 7), planted=[], drop=set()),
        dict(id="APP-2026-0936", name="Buxoro Zardo'zlik MChJ", industry_key="textile", requested=180_000, term=12, received=date(2026, 10, 9), planted=[],
             drop={"form1_FY2025.pdf", "form1_H1-2026.pdf", "form2_H1-2026.pdf", "statement_2026-01_08.xlsx", "tax_declaration_Q2-2026.pdf"}),
    ]
    rows = [dict(id="APP-2026-0931", name="Farovon Savdo MChJ", industry="Food distribution", requested_mln=850.0, term_months=24,
                 received="2026-10-06", bundle="hero_farovon", channel="branch")]
    for i, a in enumerate(apps):
        out = root / "applications" / a["id"]
        t = make_bundle(20_000 + i, root, "applications", out_dir=out, company_over={"name": a["name"]},
                        industry_key=a["industry_key"], requested_kuzs=a["requested"], term=a["term"],
                        planted_override=a["planted"], drop=a["drop"], noise=False, received=a["received"], bundle_id=a["id"])
        rows.append(dict(id=a["id"], name=a["name"], industry=t["company"]["industry"], requested_mln=a["requested"] / 1000,
                         term_months=a["term"], received=a["received"].isoformat(), bundle=f"applications/{a['id']}", channel="branch"))
    with open(root / "applications.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def build_portfolio(root: Path, workers: int = 6) -> None:
    rng = np.random.default_rng(424242)
    rows = build_loan_book(rng)
    pdir = root / "portfolio"
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        list(ex.map(build_borrower, [(r, str(pdir)) for r in rows]))
    cols = ["loan_id", "name", "stir", "industry", "region", "original", "outstanding", "installment", "due_day",
            "term_months", "paid_count", "disbursed_on", "rate_pct", "repayments"]
    with open(root / "loan_book.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({"loan_id": r["loan_id"], "name": r["name"], "stir": r["stir"], "industry": r["industry"],
                        "region": r["region"], "original": r["original"], "outstanding": r["outstanding"],
                        "installment": r["installment"], "due_day": r["due_day"], "term_months": r["term"],
                        "paid_count": r["paid"], "disbursed_on": r["disbursed"].isoformat(), "rate_pct": round(r["rate"] * 100, 1),
                        "repayments": json.dumps(r["repayments"])})
    outs = sorted(r["outstanding"] for r in rows)
    by = {}
    for r in rows:
        g = _status_of(r["scenario"])
        by.setdefault(g, [0, 0.0])
        by[g][0] += 1
        by[g][1] += r["outstanding"]
    manifest = {
        "note": "Synthetic loan book (declared). Amounts in mln UZS. Statuses are computed by the monitoring run from the "
                "documents; 'scenario' is the generator's target, kept only in truth files.",
        "borrowers": len(rows), "exposure_bn": round(sum(outs) / 1000, 1), "median_outstanding_mln": float(np.median(outs)),
        "largest_outstanding_mln": max(outs),
        "scenario_targets": {g: {"n": n, "exposure_bn": round(e / 1000, 1)} for g, (n, e) in by.items()},
        "deviations_from_design": {b["loan_id"]: b["deviation"] for b in NAMED if b.get("deviation")},
    }
    (root / "portfolio_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(json.dumps(manifest, indent=1, ensure_ascii=False))
    build_applications(root)
