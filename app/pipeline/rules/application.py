"""Reconciliation rule library R01–R12 for a loan application (docs/plan/02-PIPELINE.md §5).

Every rule is deterministic. Titles and details are templates filled only with fact values; every number a
rule states is itself a fact (extracted, aggregate or a derived computed fact appended to ctx.derived_facts)
and is listed in the finding's evidence.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

from app.pipeline.compute import ComputeError, computed_fact, constant_fact
from app.pipeline.rules import codes as C
from app.pipeline.rules.context import AppContext, money
from app.pipeline.rules.index import stat_parts
from app.pipeline.rules.periods import Period, add_months, month_end, months_between, parse_period, to_date
from app.pipeline.types import FactDraft, FindingDraft

TOL_KUZS = 1.0
SEVERITY_ORDER = {"attn": 0, "watch": 1, "neutral": 2, "info": 3}
REQUIRED_DOCS = {"loan_application": 1, "form1": 2, "form2": 2, "bank_statement": 1, "tax_declaration": 1}
DOC_NAMES = {
    "loan_application": "Loan application form",
    "form1": "Balance sheet (Form 1)",
    "form2": "Income statement (Form 2)",
    "bank_statement": "Bank statement",
    "tax_declaration": "Tax declaration",
}
_SALES_MONTH = re.compile(r"^statement\.inflow\.sales_receipt\.(\d{4}-\d{2})$")
_ANY_MONTH = re.compile(r"^statement\.(inflow|outflow)\.total\.(\d{4}-\d{2})$")


def _finding(rule_id: str, severity: str, label: str, title: str, detail: str, evidence: list[FactDraft | None],
             **params) -> FindingDraft:
    keys: list[str] = []
    for f in evidence:
        if f is not None and f.key and f.key not in keys:
            keys.append(f.key)
    return FindingDraft(rule_id=rule_id, severity=severity, label=label, title=title, detail=detail,
                        evidence=keys, params={k: v for k, v in params.items() if v is not None})


def _calc(ctx: AppContext, field: str, label: str, expr: str, unit: str | None = None, period: str = "") -> FactDraft:
    return ctx.derive(computed_fact(field, label, expr, ctx.index.by_key, unit=unit, period_label=period))


# ------------------------------------------------------------------ helpers shared with ratios / narrative

def resolve(ctx: AppContext, form: str, code: str, period: Period, depth: int = 0) -> tuple[float, list[FactDraft]] | None:
    """Value of a line: the extracted fact, else the sum of its dictionary children when all resolve."""
    f = ctx.index.stat(form, code, period)
    if f is not None:
        return f.value, [f]
    if depth > 3:
        return None
    for fm, parent, children in C.sum_relations():
        if fm != form or parent != code:
            continue
        total, used = 0.0, []
        for child, sign in children:
            r = resolve(ctx, form, child, period, depth + 1)
            if r is None:
                break
            total += sign * r[0]
            used.extend(r[1])
        else:
            return total, used
    return None


def total_passive_code() -> str:
    for form, parent, children in C.sum_relations():
        if form == "form1" and parent != C.F1_EQUITY_TOTAL and any(c == C.F1_EQUITY_TOTAL for c, _ in children):
            return parent
    return C.F1_TOTAL_PASSIVE


def loan_groups(ctx: AppContext) -> list[dict]:
    """Recurring loan-repayment groups (from normalise_statement, or rebuilt from transactions)."""
    groups = [g for g in ctx.recurring if g.get("category") == "loan_repayment"]
    if groups or not ctx.transactions:
        return groups
    by: dict[str, list] = {}
    for t in ctx.transactions:
        if t.recurring_group and t.recurring_group.startswith("loan:") and t.amount < 0:
            by.setdefault(t.recurring_group, []).append(t)
    out = []
    for g, items in by.items():
        months: dict[str, float] = {}
        for t in items:
            ym = f"{t.booked_on.year:04d}-{t.booked_on.month:02d}"
            months[ym] = months.get(ym, 0.0) - t.amount
        out.append({"group": g, "category": "loan_repayment", "count": len(months),
                    "amount": statistics.median(months.values()) / 1000.0, "contract_no": g.split(":", 1)[1],
                    "day_of_month": int(statistics.median(t.booked_on.day for t in items)),
                    "months": sorted(months), "row_ns": sorted(t.row_n for t in items), "fact_keys": {}})
    return out


def _group_facts(ctx: AppContext, g: dict) -> dict[str, FactDraft]:
    keys = g.get("fact_keys") or {}
    out = {k: ctx.index.by_key[v] for k, v in keys.items() if v in ctx.index.by_key}
    if "monthly" not in out:
        gid = g["group"]
        f = ctx.index.field(f"statement.loan_repayment.monthly.{gid}")
        if f is None:
            f = ctx.derive(constant_fact(f"statement.loan_repayment.monthly.{gid}",
                                         f"Loan repayments, contract {g.get('contract_no') or gid}, monthly "
                                         f"(day {g.get('day_of_month')})", g["amount"], "kUZS", method="aggregate",
                                         kind="aggregate", note=f"rows: {', '.join(map(str, g.get('row_ns', [])[:20]))}"))
        out["monthly"] = f
        c = ctx.index.field(f"statement.loan_repayment.count.{gid}")
        out["count"] = c or ctx.derive(constant_fact(f"statement.loan_repayment.count.{gid}",
                                                     f"Loan repayments, contract {g.get('contract_no') or gid}: payments",
                                                     g["count"], "count", method="aggregate", kind="aggregate"))
    return out


def _norm_contract(s: object) -> str:
    return re.sub(r"[^0-9a-z]", "", str(s or "").lower())


def undeclared_loan_groups(ctx: AppContext) -> list[dict]:
    """Recurring loan repayments (≥ 3 months) that do not match a debt declared in the application."""
    app = ctx.application
    declared = app.get("declared_debts") or []
    contracts = {_norm_contract(d.get("contract_no")) for d in declared if d.get("contract_no")}
    declared_monthly = sum(float(d.get("monthly") or 0) for d in declared)
    out = []
    for g in loan_groups(ctx):
        if g.get("count", 0) < 3:
            continue
        if g.get("contract_no") and _norm_contract(g["contract_no"]) in contracts:
            continue
        if not g.get("contract_no") and declared_monthly and declared_monthly >= 0.9 * g["amount"]:
            continue
        out.append(g)
    return out


def latest_balance_period(ctx: AppContext) -> Period | None:
    ps = ctx.index.form_periods("form1", "point")
    return ps[-1] if ps else None


def latest_flow_period(ctx: AppContext, code: str = C.F2_REVENUE) -> Period | None:
    ps = ctx.index.periods_for("form2", code, "flow")
    return ps[-1] if ps else None


def _expected_periods(received: date) -> dict[str, list[str]]:
    y = received.year
    fy = y - 1 if received >= date(y, 4, 1) else y - 2
    out = {"form2": [f"FY{fy}"], "form1": [f"{fy}-12-31"]}
    if received >= date(y, 8, 15):
        out["form2"].append(f"H1-{y}")
        out["form1"].append(f"{y}-06-30")
    return out


def _expected_tax_quarter(received: date) -> str:
    """Latest quarter whose declaration was due (quarter end at least 30 days before the application)."""
    cutoff = received - timedelta(days=30)
    for q in range(4, 0, -1):
        if month_end(cutoff.year, 3 * q) <= cutoff:
            return f"Q{q} {cutoff.year}"
    return f"Q4 {cutoff.year - 1}"


def _doc_periods(ctx: AppContext, form: str) -> set[str]:
    keys = {p.key for p in ctx.index.form_periods(form)}
    for d in ctx.docs_of(form):
        s, e = to_date(d.get("period_start")), to_date(d.get("period_end"))
        if form == "form1" and e:
            keys.add(parse_period(e.isoformat()).key)
        if form == "form2" and s and e:
            months = len(months_between(s, e))
            if months == 12:
                keys.add(f"FY{e.year}")
            elif months == 6:
                keys.add(f"H{1 if e.month <= 6 else 2}-{e.year}")
    return keys


def _human(label: str) -> str:
    return parse_period(label).human()


# ------------------------------------------------------------------ R01–R12

def r01_balance(ctx: AppContext) -> list[FindingDraft]:
    out = []
    pcode = total_passive_code()
    for p in ctx.index.periods_for("form1", C.F1_TOTAL_ASSETS, "point"):
        assets = ctx.index.stat("form1", C.F1_TOTAL_ASSETS, p)
        r = resolve(ctx, "form1", pcode, p)
        if r is None:
            continue
        passive_val, used = r
        diff = assets.value - passive_val
        if abs(diff) <= TOL_KUZS:
            continue
        expr = f"{assets.key} - (" + " + ".join(f.key for f in used) + ")"
        try:
            d = _calc(ctx, f"check.r01.difference.{p.key}", f"Balance sheet difference, {p.human()} "
                      "(assets minus liabilities and equity)", expr, period=p.key)
        except ComputeError:
            continue
        pas = used[0] if len(used) == 1 else _calc(ctx, f"check.r01.passive.{p.key}",
                                                     f"Liabilities and equity, {p.human()}",
                                                     " + ".join(f.key for f in used), period=p.key)
        out.append(_finding("R01", "attn", "Balance sheet does not balance",
                            f"Balance sheet at {p.human()} does not balance",
                            f"Total assets (line {C.F1_TOTAL_ASSETS}) are {money(assets)}, liabilities and equity are "
                            f"{money(pas)}: a difference of {money(d)}.",
                            [assets, pas, d, *used], period=p.key))
    return out


def _relation_findings(ctx: AppContext, form: str, rule_id: str, skip_parents: set[str]) -> list[FindingDraft]:
    out = []
    form_name = "Form 1" if form == "form1" else "Form 2"
    for fm, parent, children in C.sum_relations():
        if fm != form or parent in skip_parents:
            continue
        for p in ctx.index.periods_for(form, parent):
            pf = ctx.index.stat(form, parent, p)
            kids = [(ctx.index.stat(form, c, p), s) for c, s in children]
            if any(k is None for k, _ in kids):
                continue
            total = sum(s * k.value for k, s in kids)
            if abs(pf.value - total) <= TOL_KUZS:
                continue
            expr = " ".join(("+ " if i and s > 0 else ("- " if s < 0 else "")) + k.key for i, (k, s) in enumerate(kids))
            try:
                sf = _calc(ctx, f"check.{rule_id.lower()}.sum.{parent}.{p.key}",
                           f"{form_name} lines {', '.join(c for c, _ in children)} combined, {p.human()}", expr,
                           period=p.key)
                df = _calc(ctx, f"check.{rule_id.lower()}.difference.{parent}.{p.key}",
                           f"{form_name} line {parent} difference, {p.human()}", f"{pf.key} - {sf.key}", period=p.key)
            except ComputeError:
                continue
            ops = " ".join(("+ " if i and s > 0 else ("− " if s < 0 else "")) + c for i, (c, s) in
                           enumerate(children))
            out.append(_finding(rule_id, "watch", f"{form_name} arithmetic",
                                f"{form_name} line {parent} does not equal lines {ops} ({p.human()})",
                                f"Line {parent} is {money(pf)}; lines {ops} give {money(sf)}: a difference of "
                                f"{money(df)}. Check the extraction of these lines against the document.",
                                [pf, sf, df, *[k for k, _ in kids]], parent=parent, period=p.key))
    return out


def r02_form1_sums(ctx: AppContext) -> list[FindingDraft]:
    return _relation_findings(ctx, "form1", "R02", {C.F1_TOTAL_ASSETS, total_passive_code()})


def r03_form2_chain(ctx: AppContext) -> list[FindingDraft]:
    return _relation_findings(ctx, "form2", "R03", set())


def r04_profit_vs_equity(ctx: AppContext) -> list[FindingDraft]:
    out = []
    for p in ctx.index.periods_for("form2", C.F2_NET_PROFIT, "flow"):
        np_ = ctx.index.stat("form2", C.F2_NET_PROFIT, p)
        re_end = ctx.index.stat("form1", C.F1_RETAINED_EARNINGS, p.end.isoformat())
        re_start = ctx.index.stat("form1", C.F1_RETAINED_EARNINGS, (p.start - timedelta(days=1)).isoformat())
        if not (np_ and re_end and re_start):
            continue
        delta = re_end.value - re_start.value
        tol = max(0.05 * abs(np_.value), 10_000.0)
        if abs(delta - np_.value) <= tol:
            continue
        try:
            dre = _calc(ctx, f"check.r04.retained_change.{p.key}", f"Change in retained earnings, {p.human()}",
                        f"{re_end.key} - {re_start.key}", period=p.key)
            diff = _calc(ctx, f"check.r04.difference.{p.key}", f"Net profit minus change in retained earnings, "
                         f"{p.human()}", f"{np_.key} - {dre.key}", period=p.key)
        except ComputeError:
            continue
        out.append(_finding("R04", "watch", "Profit vs equity",
                            f"Net profit for {p.human()} does not match the change in retained earnings",
                            f"Form 2 line {C.F2_NET_PROFIT} shows {money(np_)}; retained earnings (Form 1 line "
                            f"{C.F1_RETAINED_EARNINGS}) changed by {money(dre)}, a gap of {money(diff)}. Dividends "
                            "or prior-period adjustments are not visible in the documents.",
                            [np_, dre, diff, re_end, re_start], period=p.key))
    return out


def _statement_months(ctx: AppContext) -> set[str]:
    months = {m.group(2) for f in ctx.index.facts if (m := _ANY_MONTH.match(f.field))}
    for t in ctx.transactions:
        months.add(f"{t.booked_on.year:04d}-{t.booked_on.month:02d}")
    return months


def r05_revenue_vs_inflows(ctx: AppContext) -> list[FindingDraft]:
    out = []
    covered = _statement_months(ctx)
    if not covered:
        return out
    sales = {m.group(1): f for f in ctx.index.facts if (m := _SALES_MONTH.match(f.field))}
    for p in ctx.index.periods_for("form2", C.F2_REVENUE, "flow"):
        rev = ctx.index.stat("form2", C.F2_REVENUE, p)
        if not rev or rev.value <= 0:
            continue
        overlap = [m for m in months_between(p.start, p.end) if m in covered]
        if len(overlap) < 3:
            continue
        inflow_facts = [sales[m] for m in overlap if m in sales]
        span = f"{overlap[0]}..{overlap[-1]}"
        if inflow_facts:
            inflow = _calc(ctx, f"check.r05.inflows.{p.key}", f"Customer receipts in the bank statement, "
                           f"{_human(overlap[0])}–{_human(overlap[-1])}", " + ".join(f.key for f in inflow_facts),
                           period=span)
        else:
            inflow = ctx.derive(constant_fact(f"check.r05.inflows.{p.key}", f"Customer receipts in the bank statement, "
                                              f"{_human(overlap[0])}–{_human(overlap[-1])}", 0.0, "kUZS",
                                              period_label=span, note="no customer receipts in these months"))
        try:
            if len(overlap) != p.months:
                rev_cmp = _calc(ctx, f"check.r05.revenue_prorated.{p.key}", f"Revenue {p.human()} pro rata for "
                                f"{len(overlap)} statement months", f"{rev.key} * {len(overlap)} / {p.months}",
                                period=span)
            else:
                rev_cmp = rev
            cov = _calc(ctx, f"check.r05.coverage.{p.key}", f"Customer receipts net of VAT as % of revenue, "
                        f"{_human(overlap[0])}–{_human(overlap[-1])}", f"{inflow.key} / 1.12 / {rev_cmp.key} * 100",
                        unit="pct", period=span)
        except ComputeError:
            continue
        ratio = cov.value / 100.0
        if 0.85 <= ratio <= 1.20:
            continue
        sev = "attn" if ratio < 0.70 else "watch"
        direction = "below" if ratio < 0.85 else "above"
        out.append(_finding("R05", sev, "Revenue vs bank inflows",
                            f"Bank receipts are {direction} the revenue reported for {p.human()}",
                            f"Customer receipts in the statement ({money(inflow)}, divided by 1.12 for VAT) cover "
                            f"{money(cov)} of the revenue in Form 2 line {C.F2_REVENUE} for the same months "
                            f"({money(rev_cmp)}). Expected range 85–120%.",
                            [rev, inflow, rev_cmp, cov], period=p.key, months=len(overlap)))
    return out


def r06_undeclared_loans(ctx: AppContext) -> list[FindingDraft]:
    out = []
    app = ctx.application
    declared_known = any(k in app for k in ("declared_debts", "declared_debts_total")) or \
        ctx.index.field("application.declared_debts_total") is not None
    lt_period = latest_balance_period(ctx)
    lt = ctx.index.stat("form1", C.F1_LT_LIABILITIES, lt_period) if lt_period else None
    for g in undeclared_loan_groups(ctx):
        gf = _group_facts(ctx, g)
        lt_zero = lt is not None and abs(lt.value) <= TOL_KUZS
        if not declared_known and not lt_zero:
            continue
        evidence = [gf.get("monthly"), gf.get("count"), gf.get("total"), lt]
        if declared_known:
            dv, dfact = ctx.app_value("declared_debts_total")
            if dfact is None:
                total = dv if dv is not None else sum(float(d.get("outstanding") or 0) for d in
                                                      app.get("declared_debts") or [])
                dfact = ctx.derive(constant_fact("application.declared_debts_total", "Existing debts declared in the "
                                                 "application", total, "kUZS", formula="application form",
                                                 note="declared in the loan application", kind="extracted"))
            evidence.append(dfact)
            title = "Bank statement shows loan repayments not listed in the application"
            declared_txt = ("the application declares no existing debts" if abs(dfact.value) <= TOL_KUZS
                            else f"the application declares {money(dfact)} of existing debts without this contract")
        else:
            title = "Bank statement shows loan repayments with no long-term liabilities on Form 1"
            declared_txt = "the application form is not available"
        contract = g.get("contract_no")
        months = g.get("months") or []
        when = f" from {_human(months[0])} to {_human(months[-1])}" if months else ""
        lt_txt = f"; Form 1 line {C.F1_LT_LIABILITIES} shows {money(lt)}" if lt is not None else ""
        detail = (f"{money(gf.get('count'))} monthly repayments of {money(gf['monthly'])} on day "
                  f"{g.get('day_of_month')}{' under contract ' + contract if contract else ''}{when}; "
                  f"{declared_txt}{lt_txt}.")
        out.append(_finding("R06", "attn", "Undeclared obligation", title, detail, evidence, group=g["group"],
                            contract_no=contract, contract_date=g.get("contract_date"),
                            day_of_month=g.get("day_of_month"), monthly=g.get("amount"), payments=g.get("count"),
                            lender=g.get("counterparty") or None))
    return out


def r07_application_revenue(ctx: AppContext) -> list[FindingDraft]:
    declared, dfact = ctx.app_value("declared_revenue_fy")
    if declared is None:
        return []
    year = ctx.application.get("declared_revenue_year")
    if not year and dfact is not None and parse_period(dfact.period_label).kind == "flow":
        year = parse_period(dfact.period_label).end.year
    if not year:
        fys = [p for p in ctx.index.periods_for("form2", C.F2_REVENUE, "flow") if p.months == 12]
        if not fys:
            return []
        year = fys[-1].end.year
    rev = ctx.index.stat("form2", C.F2_REVENUE, f"FY{int(year)}")
    if rev is None or rev.value == 0:
        return []
    if dfact is None:
        dfact = ctx.app_fact("declared_revenue_fy", f"Revenue FY {year} stated in the application",
                             period_label=f"FY{int(year)}")
    pct = (declared - rev.value) / abs(rev.value) * 100.0
    if abs(pct) <= 2.0:
        return []
    try:
        diff = _calc(ctx, f"check.r07.difference.FY{year}", f"Application revenue minus Form 2 revenue, FY {year}",
                     f"{dfact.key} - {rev.key}", period=f"FY{year}")
        dpct = _calc(ctx, f"check.r07.difference_pct.FY{year}", f"Application revenue vs Form 2 revenue, FY {year}",
                     f"({dfact.key} - {rev.key}) / {rev.key} * 100", unit="pct", period=f"FY{year}")
    except ComputeError:
        return []
    return [_finding("R07", "watch", "Contradiction",
                     f"{year} revenue differs between the application form and the income statement",
                     f"The application states {money(dfact)}; Form 2 line {C.F2_REVENUE} shows {money(rev)}: "
                     f"a difference of {money(diff)} ({money(dpct)}).",
                     [dfact, rev, diff, dpct], year=int(year))]


def r08_periods(ctx: AppContext) -> list[FindingDraft]:
    out = []
    received = ctx.received_on
    if received is None:
        return out
    # statements: >= 6 of the last 8 complete months
    if ctx.docs_of("bank_statement") or ctx.transactions:
        months = {f"{t.booked_on.year:04d}-{t.booked_on.month:02d}" for t in ctx.transactions}
        if not months:  # no parsed rows: fall back to the declared statement periods
            for d in ctx.docs_of("bank_statement"):
                s, e = to_date(d.get("period_start")), to_date(d.get("period_end"))
                if s and e:
                    months.update(months_between(s, e))
        first = add_months(date(received.year, received.month, 1), -8)
        last = add_months(date(received.year, received.month, 1), -1)
        window = months_between(first, last)
        n = len([m for m in window if m in months])
        if n < 6:
            cf = ctx.derive(constant_fact("check.r08.statement_months", "Months of the last 8 covered by bank "
                                          "statements", n, "count", note=f"window {window[0]} to {window[-1]}"))
            out.append(_finding("R08", "neutral", "Period gap", "Bank statements do not cover the last 6 months",
                                f"The statements cover {money(cf)} of the 8 months before the application "
                                f"({_human(window[0])}–{_human(window[-1])}).", [cf], months=n))
    expected = _expected_periods(received)
    for form in ("form2", "form1"):
        present_docs = len(ctx.docs_of(form))
        if present_docs < REQUIRED_DOCS[form] and present_docs < len(expected[form]):
            continue  # R10 reports the missing document
        have = _doc_periods(ctx, form)
        if not have:
            continue
        for exp in expected[form]:
            if parse_period(exp).key not in have:
                latest = sorted((parse_period(h) for h in have), key=lambda p: p.sort_key())[-1]
                out.append(_finding("R08", "neutral", "Period gap",
                                    f"{DOC_NAMES[form]} for {_human(exp)} not provided",
                                    f"Expected the statement for {_human(exp)} for an application received on "
                                    f"{received.day} {received.strftime('%b %Y')}; the latest provided is "
                                    f"{latest.human()}.", [], expected=exp))
    return out


def r09_stir(ctx: AppContext) -> list[FindingDraft]:
    expected = re.sub(r"\D", "", str(ctx.application.get("borrower_stir") or "")) or None
    stirs = [(d, re.sub(r"\D", "", str(d.get("stir") or ""))) for d in ctx.documents if d.get("stir")]
    if not stirs:
        return []
    if not expected:
        counts: dict[str, int] = {}
        for _, s in stirs:
            counts[s] = counts.get(s, 0) + 1
        expected = max(counts, key=counts.get)
    bad = [(d, s) for d, s in stirs if s != expected]
    if not bad:
        return []
    stir_facts = [f for f in ctx.index.facts if f.field.endswith(".stir")]
    names = ", ".join(f"{d.get('filename')} ({s})" for d, s in bad)
    return [_finding("R09", "attn", "STIR mismatch", "Documents belong to different taxpayers",
                     f"The borrower STIR is {expected}; these documents show another STIR: {names}.",
                     stir_facts, expected=expected, documents=[d.get("filename") for d, _ in bad])]


def r10_missing_documents(ctx: AppContext) -> list[FindingDraft]:
    out = []
    received = ctx.received_on
    expected = _expected_periods(received) if received else {"form1": [], "form2": []}
    for doc_type, need in REQUIRED_DOCS.items():
        have = len(ctx.docs_of(doc_type))
        if have >= need:
            continue
        if doc_type in ("form1", "form2"):
            present = _doc_periods(ctx, doc_type)
            missing = [e for e in expected[doc_type] if parse_period(e).key not in present] or [None]
            for e in missing[: need - have]:
                title = f"{DOC_NAMES[doc_type]} for {_human(e)} not provided" if e else f"{DOC_NAMES[doc_type]} not provided"
                out.append(_finding("R10", "neutral", "Missing document", title,
                                    "Requested from the applicant before the review can be completed.", [],
                                    doc_type=doc_type, expected=e))
        elif doc_type == "tax_declaration":
            q = _expected_tax_quarter(received) if received else None
            title = f"Tax declaration for {q} not provided" if q else "Tax declaration not provided"
            out.append(_finding("R10", "neutral", "Missing document", title,
                                "Requested from the applicant before the review can be completed.", [],
                                doc_type=doc_type, expected=q))
        else:
            out.append(_finding("R10", "neutral", "Missing document", f"{DOC_NAMES[doc_type]} not provided",
                                "Requested from the applicant before the review can be completed.", [],
                                doc_type=doc_type))
    return out


def r11_half_year_pattern(ctx: AppContext) -> list[FindingDraft]:
    out = []
    for p in ctx.index.periods_for("form2", C.F2_REVENUE, "flow"):
        m = re.fullmatch(r"H1-(\d{4})", p.raw)
        if not m:
            continue
        fy = ctx.index.stat("form2", C.F2_REVENUE, f"FY{int(m.group(1)) - 1}")
        h1 = ctx.index.stat("form2", C.F2_REVENUE, p)
        if not fy or not h1 or fy.value <= 0:
            continue
        ratio = h1.value / (fy.value / 2.0)
        if 0.5 <= ratio <= 1.6:
            continue
        try:
            rf = _calc(ctx, f"check.r11.h1_vs_fy.{p.key}", f"H1 revenue vs half of FY {int(m.group(1)) - 1} revenue",
                       f"{h1.key} / ({fy.key} / 2) * 100", unit="pct", period=p.key)
        except ComputeError:
            continue
        out.append(_finding("R11", "info", "Revenue pattern",
                            f"Half-year revenue is far from half of the previous year's revenue",
                            f"{p.human()} revenue {money(h1)} is {money(rf)} of half the FY revenue ({money(fy)}). "
                            "Seasonality or a change in business volume should be explained.",
                            [h1, fy, rf], period=p.key))
    return out


def r12_duplicates(ctx: AppContext) -> list[FindingDraft]:
    out = []
    seen: dict[str, dict] = {}
    for d in ctx.documents:
        h = d.get("sha256")
        if not h:
            continue
        if h in seen:
            out.append(_finding("R12", "watch", "Duplicate document",
                                f"The same file was uploaded twice: {seen[h].get('filename')} and {d.get('filename')}",
                                "Only one copy is used in the analysis.", [],
                                documents=[seen[h].get("filename"), d.get("filename")]))
        else:
            seen[h] = d
    if ctx.fact_document:
        names = {d.get("uuid"): d.get("filename") for d in ctx.documents}
        groups: dict[tuple[str, str, str], list[FactDraft]] = {}
        for f in ctx.index.facts:
            sp = stat_parts(f.field)
            if sp and f.key in ctx.fact_document:
                groups.setdefault((sp[0], sp[1], ctx.index.period(f.period_label).key), []).append(f)
        n = 0
        for (form, code, pk), fs in sorted(groups.items()):
            docs = {ctx.fact_document[f.key] for f in fs}
            if len(docs) < 2:
                continue
            lo, hi = min(fs, key=lambda f: f.value), max(fs, key=lambda f: f.value)
            if hi.value - lo.value <= TOL_KUZS:
                continue
            form_name = "Form 1" if form == "form1" else "Form 2"
            out.append(_finding("R12", "watch", "Conflicting figures",
                                f"{form_name} line {code} for {_human(pk)} differs between documents",
                                f"{names.get(ctx.fact_document[lo.key], 'one document')} shows {money(lo)}; "
                                f"{names.get(ctx.fact_document[hi.key], 'another')} shows {money(hi)}.",
                                [lo, hi], line=code, period=pk))
            n += 1
            if n >= 5:
                break
    return out


RULES = [r01_balance, r02_form1_sums, r03_form2_chain, r04_profit_vs_equity, r05_revenue_vs_inflows,
         r06_undeclared_loans, r07_application_revenue, r08_periods, r09_stir, r10_missing_documents,
         r11_half_year_pattern, r12_duplicates]


def run_application_rules(ctx: AppContext) -> list[FindingDraft]:
    """All rules R01–R12, sorted by severity then rule id. Derived facts are in ctx.derived_facts."""
    findings: list[FindingDraft] = []
    for rule in RULES:
        findings.extend(rule(ctx))
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.rule_id))
    return findings


def run_application_rules_with_facts(ctx: AppContext) -> tuple[list[FindingDraft], list[FactDraft]]:
    findings = run_application_rules(ctx)
    return findings, list(ctx.derived_facts)
