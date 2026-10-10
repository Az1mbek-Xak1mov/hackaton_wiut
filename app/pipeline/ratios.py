"""Deterministic ratios (docs/plan/02-PIPELINE.md §6) as computed facts with formula and input keys.

compute_ratios(ctx) returns NEW facts (ratios and the intermediate facts they need). They are added to
ctx.index so later steps (narrative) can cite them, but not to ctx.derived_facts: the runner persists
ctx.derived_facts + the returned list (disjoint).
"""
from __future__ import annotations

from app.pipeline.compute import ComputeError, compute, constant_fact
from app.pipeline.rules import codes as C
from app.pipeline.rules.application import undeclared_loan_groups, _group_facts
from app.pipeline.rules.context import AppContext
from app.pipeline.rules.periods import Period
from app.pipeline.types import FactDraft


def annuity(principal: float, rate_pct: float, months: int) -> float:
    if months <= 0:
        raise ValueError("term must be positive")
    r = rate_pct / 100.0 / 12.0
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** (-months))


class _Out:
    def __init__(self, ctx: AppContext):
        self.ctx, self.facts = ctx, []

    def add(self, f: FactDraft) -> FactDraft:
        self.ctx.index.add(f)
        self.facts.append(f)
        return f

    def calc(self, field: str, label: str, expr: str, unit: str | None = None, period: str = "") -> FactDraft | None:
        try:
            return self.add(compute(expr, self.ctx.index.by_key, label=label, unit=unit, field=field, period_label=period))
        except ComputeError:
            return None


def _stat(ctx: AppContext, form: str, code: str, p: Period | str | None):
    return ctx.index.stat(form, code, p) if p is not None else None


def installment_fact(ctx: AppContext, out: _Out | None = None) -> FactDraft | None:
    """The requested loan's monthly installment: application field, else annuity(amount, rate, term)."""
    v, f = ctx.app_value("installment")
    if f is not None:
        return f
    existing = ctx.index.field("loan.installment")
    if existing is not None:
        return existing
    add = (out.add if out else ctx.derive)
    if v is not None:
        return add(constant_fact("loan.installment", "Requested loan installment, monthly", v, "kUZS",
                                 formula="application form", note="declared in the loan application", kind="extracted"))
    amount, af = ctx.app_value("requested_amount")
    rate, _ = ctx.app_value("rate_pct")
    term, _ = ctx.app_value("term_months")
    if amount is None or rate is None or not term:
        return None
    value = annuity(amount, rate, int(term))
    inputs = [af.key] if af is not None else []
    return add(constant_fact("loan.installment", "Requested loan installment, monthly (annuity)", value, "kUZS",
                             formula=f"annuity({amount:.0f} kUZS, {rate:g}% a year, {int(term)} months)",
                             inputs=inputs, note=f"annuity of the requested amount at {rate:g}% over {int(term)} months"))


def compute_ratios(ctx: AppContext) -> list[FactDraft]:
    out = _Out(ctx)
    ix = ctx.index

    # balance-sheet ratios for every balance date
    for p in ix.form_periods("form1", "point"):
        ca = _stat(ctx, "form1", C.F1_CURRENT_ASSETS, p)
        cl = _stat(ctx, "form1", C.F1_CURRENT_LIABILITIES, p)
        inv = _stat(ctx, "form1", C.F1_INVENTORY, p)
        eq = _stat(ctx, "form1", C.F1_EQUITY_TOTAL, p)
        lt = _stat(ctx, "form1", C.F1_LT_LIABILITIES, p)
        if ca and cl and cl.value:
            out.calc("ratio.current_ratio", f"Current ratio, {p.human()}", f"{ca.key} / {cl.key}", "ratio", p.key)
            if inv:
                out.calc("ratio.quick_ratio", f"Quick ratio, {p.human()}", f"({ca.key} - {inv.key}) / {cl.key}",
                         "ratio", p.key)
        if eq and eq.value and cl:
            liab = f"({lt.key} + {cl.key})" if lt else cl.key
            out.calc("ratio.debt_to_equity", f"Debt to equity, {p.human()} (declared liabilities)",
                     f"{liab} / {eq.key}", "ratio", p.key)

    # flow ratios for every income-statement period
    for p in ix.periods_for("form2", C.F2_REVENUE, "flow"):
        rev = _stat(ctx, "form2", C.F2_REVENUE, p)
        npf = _stat(ctx, "form2", C.F2_NET_PROFIT, p)
        if rev and rev.value and npf:
            out.calc("ratio.net_margin", f"Net margin, {p.human()}", f"{npf.key} / {rev.key} * 100", "pct", p.key)

    latest = ix.latest_period("form2", C.F2_REVENUE, "flow")
    if latest is None:
        return out.facts
    rev = _stat(ctx, "form2", C.F2_REVENUE, latest)

    # receivable days: receivables at the period end (else the latest balance date)
    rec = None
    for code in (C.F1_TRADE_RECEIVABLES, C.F1_RECEIVABLES):  # trade receivables first, then all debtors
        rec = _stat(ctx, "form1", code, latest.end.isoformat())
        if rec is None:
            rec = _stat(ctx, "form1", code, ix.latest_period("form1", code, "point"))
        if rec is not None:
            break
    if rec and rev and rev.value and latest.days:
        out.calc("ratio.receivable_days", f"Receivable days, {latest.human()}",
                 f"{rec.key} / {rev.key} * {latest.days}", "days", latest.key)

    inst = installment_fact(ctx, out)
    if inst is None or not latest.months:
        return out.facts

    if rev and rev.value:
        out.calc("ratio.installment_vs_revenue", f"Installment vs average monthly revenue, {latest.human()}",
                 f"{inst.key} / ({rev.key} / {latest.months}) * 100", "pct", latest.key)

    npf = _stat(ctx, "form2", C.F2_NET_PROFIT, latest)
    if npf is None:
        return out.facts
    fin = _stat(ctx, "form2", C.F2_FINANCE_COSTS, latest) or _stat(ctx, "form2", C.F2_INTEREST_EXPENSE, latest)
    if fin is not None:
        cap = out.calc("ratio.debt_service_capacity_monthly",
                       f"Est. monthly cash for debt service, {latest.human()} (net profit + finance costs)",
                       f"({npf.key} + {fin.key}) / {latest.months}", "kUZS", latest.key)
    else:
        cap = out.calc("ratio.debt_service_capacity_monthly",
                       f"Est. monthly cash for debt service, {latest.human()} (net profit only; finance costs "
                       "line not found)", f"{npf.key} / {latest.months}", "kUZS", latest.key)
    if cap is None:
        return out.facts
    out.calc("ratio.dscr_new_loan", "Est. debt service coverage, requested loan only",
             f"{cap.key} / {inst.key}", "ratio", latest.key)

    groups = undeclared_loan_groups(ctx)
    if groups:
        monthly = [_group_facts(ctx, g)["monthly"] for g in groups]
        und = out.calc("loan.undeclared_monthly", "Repayments of loans not declared in the application, monthly",
                       " + ".join(f.key for f in monthly), "kUZS")
        if und is not None:
            out.calc("ratio.dscr_incl_undeclared", "Est. debt service coverage incl. undeclared repayments",
                     f"{cap.key} / ({inst.key} + {und.key})", "ratio", latest.key)
    return out.facts


def latest_ratio(facts: list[FactDraft], field: str) -> FactDraft | None:
    """The ratio fact of a field for the most recent period (helper for the API / narrative)."""
    from app.pipeline.rules.periods import parse_period

    cands = [f for f in facts if f.field == field]
    if not cands:
        return None
    return max(cands, key=lambda f: parse_period(f.period_label).sort_key())
