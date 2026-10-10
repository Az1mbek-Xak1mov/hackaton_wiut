"""One synthetic loan-application bundle with ground truth (eval/generator --n …)."""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np

from .company import BANKS, LENDERS, make_company, stir as new_stir
from .docs_pdf import render_application, render_tax_declaration
from .finmodel import Fin, Loan, make_fin
from .noise import photo_jpg, scan_pdf
from .pdf_forms import date_phrase, period_phrase, render_form
from .statement import Party, assign_recurring, balance_to_target, make_ctx, month_txns, write_statement

PLANTABLE = ["R06", "R07", "R01", "R04", "R05", "R10", "R09"]
ALL_RULES = [f"R{i:02d}" for i in range(1, 13)]
LANG_P = {"ru": 0.4, "uz_latn": 0.4, "uz_cyrl": 0.2}
LAYOUTS = ["mof_grid", "software_export", "typed"]
PURPOSES = [
    ("Aylanma mablag'larni to'ldirish / Пополнение оборотных средств", "Mahsulot zaxirasi garovi / Залог товаров в обороте"),
    ("Asbob-uskuna sotib olish / Приобретение оборудования", "Sotib olinadigan uskuna garovi / Залог приобретаемого оборудования"),
    ("Transport vositasi sotib olish / Приобретение транспорта", "2 ta yuk avtomobili / 2 грузовых автомобиля"),
    ("Ishlab chiqarishni kengaytirish / Расширение производства", "Ko'chmas mulk (ishlab chiqarish binosi) / Недвижимость (производственное здание)"),
]


def _choose(rng, p: dict):
    keys = list(p)
    return keys[int(rng.choice(len(keys), p=np.array(list(p.values())) / sum(p.values())))]


def statement_txns(rng, fin: Fin, ctx, months: list[tuple[int, int]], opening: int, *, inflow_factor: float = 1.0,
                   extra_loans: list[dict] | None = None, targets: dict[date, int] | None = None,
                   vague_rate: float = 0.6) -> list:
    """Build transactions month by month from the financial model (UZS)."""
    c = fin.company
    payroll_share = fin.params.get("payroll_share", 0.08)
    rent = int(round(np.mean([fin.monthly[mm]["rev"] for mm in months]) * 1000 * rng.uniform(0.004, 0.015), -3))
    txns = []
    for (y, m) in months:
        mo = fin.monthly[(y, m)]
        sales = int(round(mo["rev"] * 1000 * 1.12 * rng.normal(0.985, 0.02) * inflow_factor, -3))
        payroll = int(round(mo["rev"] * 1000 * payroll_share, -3))
        util_e = int(round(mo["rev"] * 1000 * rng.uniform(0.003, 0.01), -3))
        purchases = int(round(mo["cogs"] * 1000 * 1.12 * rng.normal(0.99, 0.02) * inflow_factor
                              + (mo["sell"] + mo["other_opex"]) * 1000 * 0.5, -3))
        vat = max(0, int(round((sales - purchases) * 0.12 / 1.12 * rng.normal(1, 0.08), -3)))
        q_tax = 0
        if m in (1, 4, 7, 10):  # prior-quarter tax paid in the first month of the next quarter
            pq = (y, m - 1) if m > 1 else (y - 1, 12)
            q_tax = int(round(fin.monthly.get(pq, {}).get("tax", 0) * 1000, -3))
        loans = []
        for ln in fin.loans:
            for due, princ, intr, _ in ln.schedule():
                if due.year == y and due.month == m:
                    p = Party(ln.lender, ln.meta_stir, ln.meta_account, ln.meta_mfo)
                    loans.append({"party": p, "contract": ln.contract, "amount": princ + intr, "day": ln.due_day,
                                  "contract_date": ln.meta_cdate, "date": None})
        for ex in extra_loans or []:
            if (y, m) in ex["months"]:
                loans.append({**ex, "day": ex["day"]})
        txns += month_txns(
            ctx, y, m, sales=sales, suppliers=purchases, payroll=payroll, rent=rent, electricity=util_e,
            gas=int(round(util_e * rng.uniform(0.1, 0.4), -3)), water=int(round(util_e * rng.uniform(0.03, 0.08), -3)),
            vat=vat, profit_tax=q_tax, loans=loans,
            bank_fee=int(min(2_500_000, max(150_000, round((sales + purchases) * 0.0004, -3)))),
            cash_withdrawal=int(round(rng.uniform(1e6, 8e6), -3)) if rng.random() < 0.3 else 0,
            vague=int(rng.poisson(vague_rate)), other=int(rng.poisson(0.2)))
    for d, target in sorted((targets or {}).items()):
        balance_to_target(txns, opening, target, d, rng)
    assign_recurring(txns)
    return txns


def attach_loan_meta(rng, ln: Loan) -> Loan:
    bank, mfo = BANKS[int(rng.integers(0, len(BANKS)))]
    ln.meta_stir = new_stir(rng)
    ln.meta_account = "20208000" + "".join(str(int(x)) for x in rng.integers(0, 10, 12))
    ln.meta_mfo = mfo
    ln.meta_cdate = date.fromordinal(ln.first_due.toordinal() - 30).strftime("%d.%m.%Y")
    return ln


def fix_doc_refs(plant_info: list[dict], docs: list[dict]) -> None:
    """Photo variants turn x.pdf into x.jpg: keep planted[].doc pointing at the file that exists."""
    by_stem = {Path(d["file"]).stem: d["file"] for d in docs}
    for p in plant_info:
        if p.get("doc"):
            p["doc"] = by_stem.get(Path(p["doc"]).stem, p["doc"])


def make_bundle(seed: int, out_root: Path, split: str, *, out_dir: Path | None = None, company_over: dict | None = None,
                industry_key: str | None = None, requested_kuzs: int | None = None, term: int | None = None,
                planted_override: list[str] | None = None, drop: set[str] | None = None, noise: bool = True,
                received: date | None = None, bundle_id: str | None = None) -> dict:
    rng = np.random.default_rng(seed)
    bid = bundle_id or f"b{seed:04d}"
    out = out_dir or (out_root / split / bid)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    company = make_company(rng, industry_key, **(company_over or {}))
    lang = _choose(rng, LANG_P)
    layout = LAYOUTS[int(rng.integers(0, 3))]
    n_plant = int(rng.choice([0, 1, 2, 3], p=[0.3, 0.35, 0.25, 0.1]))
    planted = list(rng.choice(PLANTABLE, size=n_plant, replace=False)) if n_plant else []
    if planted_override is not None:
        planted = list(planted_override)
    # declared loans
    loans: list[Loan] = []
    if rng.random() < 0.5:
        bank, _mfo = BANKS[int(rng.integers(0, len(BANKS)))]
        first = date(2025, int(rng.integers(1, 10)), 15)
        loans.append(attach_loan_meta(rng, Loan(f"{first.year}-{int(rng.integers(100, 999)):04d}", bank,
                                                int(round(rng.uniform(0.1, 0.5) * 1e9, -6)), float(rng.uniform(0.2, 0.26)),
                                                int(rng.choice([24, 36])), first, int(rng.integers(5, 26)))))
    fin = make_fin(rng, company, loans=loans)
    f1, f2 = fin.f1, fin.f2
    # ---------------- plants on the numbers (before rendering)
    f1_fy_cur = dict(f1["2025-12-31"]); f1_fy_prev = dict(f1["2024-12-31"])
    f1_h1_cur = dict(f1["2026-06-30"]); f1_h1_prev = dict(f1["2025-12-31"])
    plant_info: list[dict] = []
    if "R01" in planted:
        target = f1_h1_cur if rng.random() < 0.5 else f1_fy_cur
        child = "150" if target["150"] > 0 else "180"
        delta = int(round(target["400"] * rng.uniform(0.01, 0.06)))
        for code in (child, "140", "390", "400"):
            target[code] += delta
        plant_info.append({"rule": "R01", "doc": "form1_H1-2026.pdf" if target is f1_h1_cur else "form1_FY2025.pdf",
                           "delta": delta, "evidence_codes": ["400", "780"]})
    if "R04" in planted:
        np_h1 = f2["H1-2026"]["270"]
        delta = int(max(abs(np_h1) * rng.uniform(0.12, 0.35), 15000))
        f1_h1_cur["450"] -= delta
        f1_h1_cur["420"] += delta
        plant_info.append({"rule": "R04", "doc": "form1_H1-2026.pdf", "delta": delta,
                           "evidence_codes": ["form2:270", "form1:450"]})
    # ---------------- documents
    docs: list[dict] = []
    received = received or date(2026, 10, int(rng.integers(1, 9)))
    stir_bad_doc = None
    if "R09" in planted:
        stir_bad_doc = str(rng.choice(["application.pdf", "form2_FY2025.pdf", "form1_H1-2026.pdf"]))
    wrong_stir = new_stir(rng)
    if stir_bad_doc:
        plant_info.append({"rule": "R09", "doc": stir_bad_doc, "printed_stir": wrong_stir, "true_stir": company.stir})

    def comp_for(fname):
        if fname == stir_bad_doc:
            from dataclasses import replace
            return replace(company, stir=wrong_stir)
        return company

    # application
    rev_fy = f2["FY2025"]["010"]
    if "R07" in planted:
        dev = float(rng.choice([-1, 1]) * rng.uniform(0.04, 0.15))
        declared_rev = int(round(rev_fy * (1 + dev), -3))
        plant_info.append({"rule": "R07", "doc": "application.pdf", "declared": declared_rev, "f2": rev_fy, "diff_pct": round(dev * 100, 1)})
    else:
        declared_rev = rev_fy
    requested = requested_kuzs or int(round(rev_fy * rng.uniform(0.05, 0.3), -4))
    term = term or int(rng.choice([12, 18, 24, 36]))
    rate = float(rng.choice([21.0, 22.0, 23.0, 24.0, 25.0]))
    purpose, collateral = PURPOSES[int(rng.integers(0, len(PURPOSES)))]
    debts = []
    for ln in loans:
        bal = ln.balance_at(received)
        debts.append({"lender": ln.lender, "contract": ln.contract, "balance_kuzs": int(round(bal / 1000)),
                      "monthly_kuzs": int(round(ln.installment / 1000))})
    app_truth = render_application(out / "application.pdf", comp_for("application.pdf"), lang,
                                   requested_kuzs=requested, term_months=term, rate_pct=rate, purpose=purpose,
                                   collateral=collateral, declared_revenue_kuzs=declared_rev,
                                   declared_np_kuzs=f2["FY2025"]["270"], fy=2025, debts=debts, received=received,
                                   amount_style=str(rng.choice(["uzs", "kuzs", "mln"])),
                                   revenue_in_mln_label=bool(rng.random() < 0.5))
    docs.append({"file": "application.pdf", "doc_type": "loan_application", "language": lang,
                 "period": None, **app_truth})
    # forms
    form_specs = [
        ("form1_FY2025.pdf", "form1", f1_fy_cur, f1_fy_prev, date_phrase(lang, date(2025, 12, 31)), ("2025-01-01", "2025-12-31"), date(2026, 1, 25)),
        ("form1_H1-2026.pdf", "form1", f1_h1_cur, f1_h1_prev, date_phrase(lang, date(2026, 6, 30)), ("2026-01-01", "2026-06-30"), date(2026, 7, 24)),
        ("form2_FY2025.pdf", "form2", f2["FY2025"], f2["FY2024"], period_phrase(lang, "FY2025"), ("2025-01-01", "2025-12-31"), date(2026, 1, 25)),
        ("form2_H1-2026.pdf", "form2", f2["H1-2026"], f2["H1-2025"], period_phrase(lang, "H1-2026"), ("2026-01-01", "2026-06-30"), date(2026, 7, 24)),
    ]
    for fname, form, cur, prev, when, (ps, pe), sub in form_specs:
        t = render_form(out / fname, form, lang, layout, comp_for(fname), title_when=when, cur=cur, prev=prev,
                        submitted=sub)
        docs.append({"file": fname, "doc_type": form, "period": {"start": ps, "end": pe}, **t})
    # tax declaration
    if "R10" not in planted:
        h1 = f2["H1-2026"]
        tt = render_tax_declaration(out / "tax_declaration_Q2-2026.pdf", company, lang, period_label="H1-2026",
                                    year=2026, quarter=2, income_kuzs=h1["010"] + h1["090"] + h1["110"],
                                    expenses_kuzs=h1["020"] + h1["040"] + h1["170"], submitted=date(2026, 7, 20))
        docs.append({"file": "tax_declaration_Q2-2026.pdf", "doc_type": "tax_declaration",
                     "period": {"start": "2026-01-01", "end": "2026-06-30"}, **tt})
    else:
        plant_info.append({"rule": "R10", "missing": "tax_declaration"})
    # statement
    months = [(2026, m) for m in range(1, 9)]
    ctx = make_ctx(rng, comp_for("statement_2026-01_08.xlsx"), lang="ru" if lang == "ru" else ("uz_cyrl" if lang == "uz_cyrl" else "uz"))
    extra_loans = []
    if "R06" in planted:
        lender = str(rng.choice(LENDERS))
        contract = f"{int(rng.choice([2024, 2025]))}-{int(rng.integers(1000, 9999))}"
        amount = int(round(np.mean([fin.monthly[mm]["rev"] for mm in months]) * 1000 * rng.uniform(0.01, 0.04), -5))
        day = int(rng.integers(5, 26))
        n_months = int(rng.integers(5, 9))
        lp = Party(lender, new_stir(rng), "20208000" + "".join(str(int(x)) for x in rng.integers(0, 10, 12)), "01153")
        extra_loans.append({"party": lp, "contract": contract, "amount": amount, "day": day,
                            "contract_date": f"{int(rng.integers(1, 28)):02d}.{int(rng.integers(1, 12)):02d}.{contract[:4]}",
                            "months": months[-n_months:]})
        plant_info.append({"rule": "R06", "contract": contract, "lender": lender, "monthly_uzs": amount,
                           "payments": n_months, "day": day})
    inflow_factor = 1.0
    if "R05" in planted:
        inflow_factor = float(rng.uniform(0.5, 0.68))
        plant_info.append({"rule": "R05", "inflow_factor": round(inflow_factor, 3)})
    opening = f1["2025-12-31"]["340"] * 1000
    target_h1 = f1["2026-06-30"]["340"] * 1000
    txns = statement_txns(rng, fin, ctx, months, opening, inflow_factor=inflow_factor, extra_loans=extra_loans,
                          targets={date(2026, 6, 30): target_h1})
    st_layout = "A" if rng.random() < 0.5 else "B"
    st = write_statement(out / "statement_2026-01_08.xlsx", comp_for("statement_2026-01_08.xlsx"), txns, opening,
                         date(2026, 1, 1), date(2026, 8, 31), layout=st_layout, lang=lang)
    docs.append({"file": "statement_2026-01_08.xlsx", "doc_type": "bank_statement",
                 "period": {"start": "2026-01-01", "end": "2026-08-31"}, "variant": {"layout": st_layout}})
    # ---------------- dropped documents (incomplete application files)
    for d in list(docs):
        if drop and d["file"] in drop:
            (out / d["file"]).unlink()
            docs.remove(d)
    if drop and "R10" not in planted:
        planted.append("R10")
        plant_info.append({"rule": "R10", "missing": sorted(drop)})
    # ---------------- noise variants on PDFs
    for d in docs:
        if not d["file"].endswith(".pdf"):
            continue
        if not noise:
            d["variant"] = {"scan": False}
            continue
        roll = rng.random()
        p = out / d["file"]
        if roll < 0.55:
            d["variant"] = {"scan": False}
        elif roll < 0.72:
            d["variant"] = scan_pdf(p, p, rng, dpi=300, skew=float(rng.uniform(-1, 1)), blur=float(rng.uniform(0.2, 0.5)),
                                    jpeg_q=int(rng.integers(55, 80)), stamp=company.name if rng.random() < 0.3 else None)
        elif roll < 0.89 or d.get("pages", 1) > 1:
            d["variant"] = scan_pdf(p, p, rng, dpi=150, skew=float(rng.choice([-1, 1]) * rng.uniform(1, 3)),
                                    blur=float(rng.uniform(0.4, 1.2)), jpeg_q=int(rng.integers(35, 70)))
        else:
            jpg = p.with_suffix(".jpg")
            d["variant"] = photo_jpg(p, jpg, rng, skew=float(rng.uniform(-3, 3)), warp=float(rng.uniform(0.01, 0.05)),
                                     blur=float(rng.uniform(0.3, 0.9)))
            p.unlink()
            d["file"] = jpg.name
    fix_doc_refs(plant_info, docs)
    if stir_bad_doc:
        stir_bad_doc = next((d["file"] for d in docs if Path(d["file"]).stem == Path(stir_bad_doc).stem), stir_bad_doc)
    truth = {
        "bundle_id": bid, "seed": seed, "split": split,
        "company": {"name": company.name, "stir": company.stir, "industry": company.industry, "region": company.region},
        "received": received.isoformat(),
        "documents": [{k: v for k, v in d.items() if k != "pages"} | {"page_count": d.get("pages", 1)} for d in docs],
        "transactions": st,
        "planted": plant_info,
        "expected_clean_rules": [r for r in ALL_RULES if r not in planted],
        "declared_loans": [{"contract": ln.contract, "lender": ln.lender, "installment_uzs": ln.installment,
                            "due_day": ln.due_day} for ln in loans],
        "stir_mismatch_doc": stir_bad_doc,
        "dropped_documents": sorted(drop or []),
        "model_params": fin.params,
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return truth
