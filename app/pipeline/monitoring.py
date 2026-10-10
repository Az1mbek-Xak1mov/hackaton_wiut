"""Post-disbursement monitoring indicators M01–M06 and the disclosed status rules.

Status: Stable = no indicator triggered · Watch = exactly one triggered, or only the statement is late ·
Attention = two or more triggered, or a late installment. Thresholds are illustrative; calibration against
bank history is pilot month 1. No numeric score is produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.pipeline.compute import ComputeError, compute, constant_fact, format_number, new_fact_key
from app.pipeline.rules import codes as C
from app.pipeline.rules.index import FactIndex
from app.pipeline.rules.periods import (
    add_months, month_end, months_between, parse_period, previous_flow, same_period_last_year, to_date,
)
from app.pipeline.types import FactDraft, FindingDraft, TxnDraft

CALIBRATION_LABEL = "Illustrative thresholds; calibration against bank history is pilot month 1."

DEFAULT_THRESHOLDS = {
    "revenue_drop_pct": -15.0,       # M01 triggered at or below
    "receivables_growth_pct": 25.0,  # M02 triggered at or above, while revenue change <= 0
    "payables_growth_pct": 40.0,     # M03 triggered at or above, over two periods
    "cash_coverage": 1.5,            # M04 triggered below
    "late_days": 0,                  # M05 triggered above (last 3 installments)
    "statement_late_days": 10,       # M06 triggered above (days past the covenant date)
}

INDICATORS = {
    "M01": "Revenue vs prior period",
    "M02": "Receivables growth vs sales",
    "M03": "Payables growth",
    "M04": "Cash coverage of next installment",
    "M05": "Payment punctuality",
    "M06": "Statement timeliness",
}
SEVERITY = {"M01": "attn", "M02": "attn", "M03": "watch", "M04": "watch", "M05": "watch", "M06": "watch"}
STATUS_MEANS = {
    "stable": "No indicator moved beyond its threshold",
    "watch": "One indicator moved; cause not yet confirmed, or data is late",
    "attn": "Two or more indicators moved, or a payment was late",
}


def threshold_disclosure(t: dict | None = None) -> list[dict]:
    t = {**DEFAULT_THRESHOLDS, **(t or {})}
    return [
        {"id": "M01", "indicator": INDICATORS["M01"], "rule": f"revenue change ≤ {t['revenue_drop_pct']:g}%"},
        {"id": "M02", "indicator": INDICATORS["M02"],
         "rule": f"receivables +{t['receivables_growth_pct']:g}% or more while revenue does not grow"},
        {"id": "M03", "indicator": INDICATORS["M03"], "rule": f"payables +{t['payables_growth_pct']:g}% or more over two periods"},
        {"id": "M04", "indicator": INDICATORS["M04"], "rule": f"month-end cash ÷ installment below {t['cash_coverage']:g}×"},
        {"id": "M05", "indicator": INDICATORS["M05"], "rule": "any of the last 3 installments paid late"},
        {"id": "M06", "indicator": INDICATORS["M06"],
         "rule": f"latest statement more than {t['statement_late_days']:g} days past the covenant date"},
    ]


@dataclass
class MonitoringContext:
    facts: list[FactDraft]
    transactions: list[TxnDraft] = field(default_factory=list)
    loan: dict = field(default_factory=dict)        # installment (kUZS), due_day, repayments [{n, due_on, paid_on}]
    documents: list[dict] = field(default_factory=list)
    as_of: date = field(default_factory=date.today)
    covenant_day: int = 10
    thresholds: dict = field(default_factory=dict)


class _Calc:
    def __init__(self, facts: list[FactDraft]):
        self.ix = FactIndex(list(facts))
        self.new: list[FactDraft] = []

    def add(self, f: FactDraft) -> FactDraft:
        self.ix.add(f)
        self.new.append(f)
        return f

    def calc(self, field: str, label: str, expr: str, unit: str | None = None, period: str = "") -> FactDraft | None:
        try:
            return self.add(compute(expr, self.ix.by_key, label=label, unit=unit, field=field, period_label=period))
        except ComputeError:
            return None


def _pct(v: float) -> str:
    return format_number(v, 1, signed=True) + "%"


def _ind(value=None, display="n/a", threshold=None, triggered=False, evidence=None, reason="", basis="") -> dict:
    return {"value": value, "display": display, "threshold": threshold, "triggered": triggered,
            "evidence": [f.key for f in (evidence or []) if f is not None], "reason": reason, "basis": basis}


def _revenue_change(c: _Calc) -> tuple[FactDraft, FactDraft, FactDraft, str] | None:
    ix = c.ix
    latest = ix.latest_period("form2", C.F2_REVENUE, "flow")
    if latest is not None:
        cur = ix.stat("form2", C.F2_REVENUE, latest)
        for prev_label, basis in ((previous_flow(latest), "previous period"),
                                  (same_period_last_year(latest), "same period last year")):
            prev = ix.stat("form2", C.F2_REVENUE, prev_label) if prev_label else None
            if prev and prev.value:
                f = c.calc("monitoring.revenue_change", f"Revenue change, {latest.human()} vs "
                           f"{parse_period(prev_label).human()}", f"({cur.key} - {prev.key}) / {prev.key} * 100",
                           "pct", latest.key)
                if f:
                    return f, cur, prev, f"vs {parse_period(prev_label).human()}"
    sales = sorted(((f.field.rsplit(".", 1)[1], f) for f in ix.facts
                    if f.field.startswith("statement.inflow.sales_receipt.") and f.field[-7:-3].isdigit()),
                   key=lambda t: t[0])
    if len(sales) >= 2:
        (m1, prev), (m2, cur) = sales[-2], sales[-1]
        if months_between(to_date(m1 + "-01"), to_date(m2 + "-01")) == [m1, m2] and prev.value:
            f = c.calc("monitoring.revenue_change", f"Customer receipts change, {parse_period(m2).human()} vs "
                       f"{parse_period(m1).human()}", f"({cur.key} - {prev.key}) / {prev.key} * 100", "pct", m2)
            if f:
                return f, cur, prev, f"vs {parse_period(m1).human()} (bank receipts)"
    return None


def _growth(c: _Calc, code: str, label: str, steps: int = 1) -> tuple[FactDraft, FactDraft, FactDraft] | None:
    ps = c.ix.periods_for("form1", code, "point")
    if len(ps) < 2:
        return None
    cur_p = ps[-1]
    prev_p = ps[-1 - min(steps, len(ps) - 1)]
    cur, prev = c.ix.stat("form1", code, cur_p), c.ix.stat("form1", code, prev_p)
    if not prev.value:
        return None
    f = c.calc(f"monitoring.{label.lower().replace(' ', '_')}_change",
               f"{label} change, {prev_p.human()} to {cur_p.human()}", f"({cur.key} - {prev.key}) / {prev.key} * 100",
               "pct", cur_p.key)
    return (f, cur, prev) if f else None


def _cash_fact(c: _Calc) -> FactDraft | None:
    bal = [f for f in c.ix.facts if f.field.startswith("statement.balance_end.")]
    if bal:
        return max(bal, key=lambda f: parse_period(f.period_label).sort_key())
    p = c.ix.latest_period("form1", C.F1_CASH, "point")
    return c.ix.stat("form1", C.F1_CASH, p) if p else None


def _installment(c: _Calc, loan: dict) -> FactDraft | None:
    if loan.get("installment") is None:
        return None
    return c.add(constant_fact("loan.installment", f"Loan installment{' (contract ' + str(loan['contract_no']) + ')' if loan.get('contract_no') else ''}",
                               float(loan["installment"]), "kUZS", formula="loan book",
                               note="loan book (declared synthetic input)", kind="extracted"))


def _repayment_lateness(ctx: MonitoringContext) -> list[dict]:
    """[{n, due_on, paid_on, days_late, row_n}] for installments due before as_of, newest last."""
    reps = []
    for r in ctx.loan.get("repayments") or []:
        due = to_date(r.get("due_on"))
        if not due or due > ctx.as_of:
            continue
        paid = to_date(r.get("paid_on"))
        late = ((paid or ctx.as_of) - due).days
        reps.append({"n": r.get("n"), "due_on": due, "paid_on": paid, "days_late": max(0, late), "row_n": None})
    inst, due_day = ctx.loan.get("installment"), ctx.loan.get("due_day")
    if not reps and inst and due_day:
        pays = [t for t in ctx.transactions if t.amount < 0 and t.category == "loan_repayment"
                and abs(-t.amount / 1000.0 - float(inst)) <= 0.1 * float(inst)]
        for t in sorted(pays, key=lambda t: t.booked_on):
            d = t.booked_on
            try:
                due = date(d.year, d.month, int(due_day))
            except ValueError:
                due = month_end(d.year, d.month)
            if d < due - timedelta(days=20):  # paid early for the next due date
                continue
            reps.append({"n": None, "due_on": due, "paid_on": d, "days_late": max(0, (d - due).days), "row_n": t.row_n})
    reps.sort(key=lambda r: r["due_on"])
    for r in reps:  # match statement rows for evidence
        if r["row_n"] is None and r["paid_on"]:
            for t in ctx.transactions:
                if t.amount < 0 and t.category == "loan_repayment" and t.booked_on == r["paid_on"]:
                    r["row_n"] = t.row_n
                    break
    return reps


def _statement_end(ctx: MonitoringContext) -> date | None:
    ends = [to_date(d.get("period_end")) for d in ctx.documents if d.get("doc_type") == "bank_statement"]
    ends = [e for e in ends if e]
    if ctx.transactions:
        ends.append(max(t.booked_on for t in ctx.transactions))
    return max(ends) if ends else None


def evaluate_borrower(ctx: MonitoringContext) -> dict:
    t = {**DEFAULT_THRESHOLDS, **(ctx.thresholds or {})}
    c = _Calc(ctx.facts)
    ind: dict[str, dict] = {}

    # M01 revenue vs prior period
    rc = _revenue_change(c)
    if rc:
        f, cur, prev, basis = rc
        trig = f.value <= t["revenue_drop_pct"]
        ind["M01"] = _ind(round(f.value, 2), _pct(f.value), t["revenue_drop_pct"], trig, [f, cur, prev],
                          f"Revenue {_pct(f.value)} {basis}", basis)
    else:
        ind["M01"] = _ind(reason="No comparable revenue period")

    # M02 receivables growth while sales do not grow
    rcode = C.F1_TRADE_RECEIVABLES if len(c.ix.periods_for("form1", C.F1_TRADE_RECEIVABLES, "point")) >= 2 \
        else C.F1_RECEIVABLES
    g = _growth(c, rcode, "Receivables")
    if g:
        f, cur, prev = g
        rev_val = ind["M01"]["value"]
        trig = f.value >= t["receivables_growth_pct"] and rev_val is not None and rev_val <= 0
        ev = [f, cur, prev] + ([c.ix.by_key[k] for k in ind["M01"]["evidence"][:1]] if trig else [])
        ind["M02"] = _ind(round(f.value, 2), _pct(f.value), t["receivables_growth_pct"], trig, ev,
                          f"Receivables {_pct(f.value)} while revenue {'fell' if (rev_val or 0) < 0 else 'did not grow'}")
    else:
        ind["M02"] = _ind(reason="Receivables not available for two balance dates")

    # M03 payables growth over two periods
    code = C.F1_PAYABLES_SUPPLIERS if c.ix.periods_for("form1", C.F1_PAYABLES_SUPPLIERS, "point") else C.F1_CURRENT_LIABILITIES
    g = _growth(c, code, "Payables", steps=2)
    if g:
        f, cur, prev = g
        trig = f.value >= t["payables_growth_pct"]
        ind["M03"] = _ind(round(f.value, 2), _pct(f.value), t["payables_growth_pct"], trig, [f, cur, prev],
                          f"Payables {_pct(f.value)} over two periods")
    else:
        ind["M03"] = _ind(reason="Payables not available for two balance dates")

    # M04 cash coverage of the next installment
    cash, inst = _cash_fact(c), _installment(c, ctx.loan)
    if cash is not None and inst is not None and inst.value:
        f = c.calc("monitoring.cash_coverage", "Cash coverage of the next installment",
                   f"{cash.key} / {inst.key}", "ratio", cash.period_label)
        if f is not None:
            trig = f.value < t["cash_coverage"]
            ind["M04"] = _ind(round(f.value, 3), format_number(f.value, 1) + "×", t["cash_coverage"], trig,
                              [f, cash, inst], f"Cash covers the next installment {format_number(f.value, 1)}× "
                              f"(threshold {t['cash_coverage']:g}×)")
    ind.setdefault("M04", _ind(reason="Month-end cash or installment not available"))

    # M05 punctuality: last 3 installments
    reps = _repayment_lateness(ctx)[-3:]
    if reps:
        worst = max(reps, key=lambda r: r["days_late"])
        trig = worst["days_late"] > t["late_days"]
        n_txt = f" #{worst['n']}" if worst.get("n") else ""
        paid_txt = worst["paid_on"].strftime("%d %b %Y") if worst["paid_on"] else "not yet paid"
        lf = c.add(FactDraft(field="monitoring.days_late", label=f"Installment{n_txt} due {worst['due_on']:%d %b %Y}, "
                             f"paid {paid_txt}: days late", value=float(worst["days_late"]), unit="days",
                             kind="aggregate", period_label=worst["due_on"].isoformat(), method="rule",
                             passage=f"row {worst['row_n']} of the bank statement" if worst["row_n"] else "",
                             note="repayment schedule vs payment date", key=new_fact_key()))
        reason = (f"Installment{n_txt} paid {worst['days_late']} days late" if worst["paid_on"]
                  else f"Installment{n_txt} overdue by {worst['days_late']} days")
        ind["M05"] = _ind(worst["days_late"], f"{worst['days_late']} days", t["late_days"], trig, [lf],
                          reason if trig else "Last 3 installments on time")
    else:
        ind["M05"] = _ind(reason="No installments due yet")

    # M06 statement timeliness
    end = _statement_end(ctx)
    if end is None:
        ind["M06"] = _ind(None, "none", t["statement_late_days"], True, [], "No bank statement uploaded")
    else:
        m = add_months(date(end.year, end.month, 1), 1) if end >= month_end(end.year, end.month) - timedelta(days=2) \
            else date(end.year, end.month, 1)
        due = date(add_months(m, 1).year, add_months(m, 1).month, min(ctx.covenant_day, 28))
        late = (ctx.as_of - due).days
        if late > 0:
            lf = c.add(FactDraft(field="monitoring.statement_days_late", label=f"Statement for "
                                 f"{parse_period(f'{m.year:04d}-{m.month:02d}').human()}: days past the covenant date",
                                 value=float(late), unit="days", kind="aggregate", period_label=ctx.as_of.isoformat(),
                                 method="rule", note=f"due {due.isoformat()}", key=new_fact_key()))
            trig = late > t["statement_late_days"]
            ind["M06"] = _ind(late, f"{late} days", t["statement_late_days"], trig, [lf],
                              f"{parse_period(f'{m.year:04d}-{m.month:02d}').human()} statement not uploaded, "
                              f"{late} days past covenant date")
        else:
            ind["M06"] = _ind(0, "on time", t["statement_late_days"], False, [], "Statements up to date")

    for k, v in ind.items():
        v["label"] = INDICATORS[k]
        v["severity"] = SEVERITY[k]

    triggered = [k for k in sorted(ind) if ind[k]["triggered"]]
    if "M05" in triggered or len(triggered) >= 2:
        status = "attn"
    elif len(triggered) == 1:
        status = "watch"
    else:
        status = "stable"
    order = sorted(triggered, key=lambda k: (SEVERITY[k] != "attn", k))
    reason = "; ".join(ind[k]["reason"] for k in order[:2]) if order else "All indicators within range"
    if len(order) > 2:
        reason += f"; {len(order) - 2} more"
    findings = [FindingDraft(rule_id=k, severity=SEVERITY[k], label=INDICATORS[k], title=ind[k]["reason"],
                             detail=f"{INDICATORS[k]}: {ind[k]['display']} (threshold: "
                                    f"{next(d['rule'] for d in threshold_disclosure(t) if d['id'] == k)}). "
                                    f"{CALIBRATION_LABEL}",
                             evidence=list(ind[k]["evidence"]), params={"value": ind[k]["value"]})
                for k in order]
    return {
        "status": status,
        "reason": reason[:255],
        "indicators": ind,
        "findings": findings,
        "facts": c.new,
        "thresholds": t,
        "trend_pct": ind["M01"]["value"],
        "coverage": ind["M04"]["value"],
        "calibration": CALIBRATION_LABEL,
    }
