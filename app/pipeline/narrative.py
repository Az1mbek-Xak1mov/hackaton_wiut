"""Deterministic template narrative, the repayment-capacity indicator and the LLM fact set.

template_narrative() is used when the LLM is off or every LLM draft was rejected by the verifier. It is built
only from facts and findings and is itself checked by the verifier sentence by sentence (a sentence that
would not verify is dropped), so it always passes.
"""
from __future__ import annotations

import re

from app.pipeline.compute import fact_display
from app.pipeline.ratios import latest_ratio
from app.pipeline.rules import codes as C
from app.pipeline.rules.context import AppContext
from app.pipeline.rules.periods import parse_period
from app.pipeline.types import FactDraft, FindingDraft
from app.pipeline.verify import verify

DISCLAIMER = ("Illustrative indicator derived from the extracted figures and rules shown. Not a validated credit "
              "score; does not replace the officer's assessment.")
CLOSING_LINE = "The officer's decision and reasoning are recorded with the evidence reviewed."
_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
NEXT_STEPS = {
    "R06": "Ask the applicant for the agreement and repayment schedule of the loan seen in the bank statement, and "
           "include it in the debt service calculation.",
    "R07": "Ask which annual revenue figure is correct and obtain the signed annual statement.",
    "R05": "Ask whether customer receipts also go through another bank account.",
    "R01": "Check the balance sheet totals against the original document.",
    "R02": "Check the flagged balance sheet lines against the original document.",
    "R03": "Check the flagged income statement lines against the original document.",
    "R04": "Ask about dividends or adjustments that explain the movement in retained earnings.",
    "R08": "Request statements for the missing periods.",
    "R09": "Confirm the taxpayer identity on each document.",
    "R10": "Obtain the missing documents listed above.",
    "R11": "Ask the applicant to explain the change in half-year revenue.",
    "R12": "Confirm which version of the document is final.",
}


def _d(f: FactDraft) -> str:
    d, u = fact_display(f)
    return f"{d} {u}".strip()


def _words(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def _stat_latest(ctx: AppContext, form: str, code: str, kind: str) -> FactDraft | None:
    p = ctx.index.latest_period(form, code, kind)
    return ctx.index.stat(form, code, p) if p else None


def _fy_revenue(ctx: AppContext) -> FactDraft | None:
    fys = [p for p in ctx.index.periods_for("form2", C.F2_REVENUE, "flow") if p.months == 12]
    return ctx.index.stat("form2", C.F2_REVENUE, fys[-1]) if fys else None


def _safe_join(sentences: list[str], facts: dict[str, FactDraft], finding_ids: set[str]) -> list[str]:
    """Keep only sentences that pass the verifier on their own."""
    return [s for s in sentences if s and verify(s, facts, finding_ids)["ok"]]


def open_issues(findings: list[FindingDraft]) -> list[FindingDraft]:
    return [f for f in findings if f.severity in ("attn", "watch")]


def repayment_indicator(ctx: AppContext, findings: list[FindingDraft], ratio_facts: list[FactDraft]) -> dict:
    """Rule-based label (no score): capacity level from the new-loan DSCR plus the count of open issues."""
    dscr = latest_ratio(ratio_facts, "ratio.dscr_new_loan")
    dscr2 = latest_ratio(ratio_facts, "ratio.dscr_incl_undeclared")
    cr = latest_ratio(ratio_facts, "ratio.current_ratio")
    nm = latest_ratio(ratio_facts, "ratio.net_margin")
    de = latest_ratio(ratio_facts, "ratio.debt_to_equity")
    if dscr is None:
        level = "Not enough data"
    elif dscr.value >= 1.25:
        level = "Adequate"
    elif dscr.value >= 1.0:
        level = "Tight"
    else:
        level = "Insufficient"
    issues = open_issues(findings)
    n = len(issues)
    label = f"{level}, with {_words(n)} unresolved issue{'s' if n != 1 else ''}" if n and dscr is not None else level
    supports, against = [], []
    if dscr is not None:
        (supports if dscr.value >= 1.25 else against).append(
            f"Estimated debt service coverage {_d(dscr)} for the requested loan")
    if dscr2 is not None:
        (supports if dscr2.value >= 1.25 else against).append(
            f"Coverage {_d(dscr2)} including repayments of undeclared loans")
    if cr is not None:
        (supports if cr.value >= 1.2 else against).append(f"Current ratio {_d(cr)}")
    if nm is not None:
        (supports if nm.value > 0 else against).append(f"Net margin {_d(nm)} ({parse_period(nm.period_label).human()})")
    if de is not None:
        (supports if de.value <= 2.0 else against).append(f"Debt to equity {_d(de)} on declared liabilities")
    for f in issues:
        against.append(f"{f.label}: {f.title}")
    return {"label": label, "level": level, "supports": supports, "weighs_against": against,
            "disclaimer": DISCLAIMER, "open_issues": n}


def narrative_fact_set(ctx: AppContext, findings: list[FindingDraft], ratio_facts: list[FactDraft],
                       limit: int = 60) -> dict[str, FactDraft]:
    """Facts the narrative (LLM or template) may cite: key statutory lines, latest ratios, finding evidence."""
    out: dict[str, FactDraft] = {}

    def put(f: FactDraft | None) -> None:
        if f is not None and f.key and len(out) < limit:
            out.setdefault(f.key, f)

    put(_fy_revenue(ctx))
    for code in (C.F2_REVENUE, C.F2_NET_PROFIT, C.F2_FINANCE_COSTS, C.F2_INTEREST_EXPENSE):
        put(_stat_latest(ctx, "form2", code, "flow"))
    fys = [p for p in ctx.index.periods_for("form2", C.F2_NET_PROFIT, "flow") if p.months == 12]
    if fys:
        put(ctx.index.stat("form2", C.F2_NET_PROFIT, fys[-1]))
    for code in (C.F1_TOTAL_ASSETS, C.F1_CURRENT_ASSETS, C.F1_INVENTORY, C.F1_CURRENT_LIABILITIES, C.F1_LT_LIABILITIES,
                 C.F1_EQUITY_TOTAL):
        put(_stat_latest(ctx, "form1", code, "point"))
    put(ctx.index.field("statement.avg_monthly_inflow"))
    for field in ("ratio.current_ratio", "ratio.quick_ratio", "ratio.net_margin", "ratio.debt_to_equity",
                  "ratio.receivable_days", "ratio.installment_vs_revenue", "ratio.debt_service_capacity_monthly",
                  "ratio.dscr_new_loan", "ratio.dscr_incl_undeclared", "loan.undeclared_monthly", "loan.installment"):
        put(latest_ratio(ratio_facts, field) or ctx.index.field(field))
    nm = [f for f in ratio_facts if f.field == "ratio.net_margin"]
    for f in nm:
        put(f)
    by_key = {**ctx.index.by_key, **{f.key: f for f in ratio_facts}}
    for fd in findings:
        for k in fd.evidence:
            put(by_key.get(k))
    return out


NUMBER_FREE_TITLES = {
    "R01": "The balance sheet does not balance.",
    "R02": "Balance sheet lines do not add up.",
    "R03": "Income statement lines do not add up.",
    "R04": "Net profit does not match the change in retained earnings.",
    "R05": "Bank receipts do not match the revenue reported.",
    "R06": "The bank statement shows loan repayments not listed in the application.",
    "R07": "Revenue differs between the application form and the income statement.",
    "R08": "The documents do not cover the expected periods.",
    "R09": "The documents belong to different taxpayers.",
    "R11": "Half-year revenue is far from half of the previous year's revenue.",
    "R12": "A document was uploaded twice or its figures conflict with another document.",
}
_DOC_NAMES = {"loan_application": "Loan application form", "form1": "Balance sheet (Form 1)",
              "form2": "Income statement (Form 2)", "bank_statement": "Bank statement", "tax_declaration": "Tax declaration"}


def _sentence(text: str) -> str:
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _with_cites(text: str, cites: str, facts: dict[str, FactDraft], fids: set[str]) -> str:
    """Append the evidence cites to every sentence of `text` whose numbers need them (the frontend turns
    the cited values found in the sentence into evidence chips)."""
    parts = re.split(r"(?<=[.!?])\s+", _sentence(text))
    out = []
    for p in parts:
        if cites and re.search(r"\d", p) and not verify(p, facts, fids)["ok"]:
            p = p[:-1] + f" {cites}." if p.endswith(".") else f"{p} {cites}"
        out.append(p)
    return " ".join(x for x in out if x)


def _number_free_title(fd: FindingDraft) -> str:
    if fd.rule_id == "R10":
        name = _DOC_NAMES.get(str(fd.params.get("doc_type", "")), "A required document")
        return f"{name} not provided."
    if fd.rule_id in NUMBER_FREE_TITLES:
        return NUMBER_FREE_TITLES[fd.rule_id]
    return _sentence(re.sub(r"[\d\u2212%×.,]+", "", fd.label or "Issue")).strip() or "Issue found."


def _bullet(fd: FindingDraft, facts: dict[str, FactDraft], fids: set[str]) -> str:
    """Best verifier-clean wording for a finding; never empty. Tried in order: title + detail with cites,
    title + evidence list, title alone, number-free title + evidence list, number-free title."""
    ev = [facts[k] for k in fd.evidence if k in facts][:4]
    cites = " ".join(f"[{f.key}]" for f in ev)
    head = f"- **{fd.label}.**"
    title = _with_cites(fd.title or fd.detail or fd.label, cites, facts, fids)
    detail = _with_cites(fd.detail, cites, facts, fids) if fd.detail and fd.detail != fd.title else ""
    evidence = ""
    if ev:
        parts = [f"{f.label}: {_d(f)} [{f.key}]" for f in ev]
        parts = [p for p in parts if verify(p, facts, fids)["ok"]]
        evidence = ("Evidence: " + "; ".join(parts) + ".") if parts else ""
    plain = _number_free_title(fd)
    candidates = [f"{head} {title} {detail}", f"{head} {title} {evidence}", f"{head} {title}",
                  f"{head} {plain} {evidence}", f"{head} {plain}"]
    for c in candidates:
        c = re.sub(r"\s+", " ", c).strip()
        if c != head and verify(c, facts, fids)["ok"]:
            return c
    return f"{head} {plain}"


def template_narrative(ctx: AppContext, findings: list[FindingDraft], ratio_facts: list[FactDraft]) -> str:
    facts = narrative_fact_set(ctx, findings, ratio_facts, limit=200)
    for f in ratio_facts:
        facts.setdefault(f.key, f)
    fids: set[str] = set()

    # 1 — repayment capacity
    p1: list[str] = []
    fy = _fy_revenue(ctx)
    latest = _stat_latest(ctx, "form2", C.F2_REVENUE, "flow")
    if fy is not None and latest is not None and latest.key != fy.key:
        p1.append(f"Net revenue was {_d(fy)} in {parse_period(fy.period_label).human()} [{fy.key}] and {_d(latest)} "
                  f"in {parse_period(latest.period_label).human()} [{latest.key}].")
    elif latest is not None:
        p1.append(f"Net revenue was {_d(latest)} in {parse_period(latest.period_label).human()} [{latest.key}].")
    nms = sorted([f for f in ratio_facts if f.field == "ratio.net_margin"],
                 key=lambda f: parse_period(f.period_label).sort_key())
    if nms:
        s = f"Net margin was {_d(nms[-1])} in {parse_period(nms[-1].period_label).human()} [{nms[-1].key}]"
        if len(nms) > 1:
            s += f", against {_d(nms[-2])} in {parse_period(nms[-2].period_label).human()} [{nms[-2].key}]"
        p1.append(s + ".")
    cr = latest_ratio(ratio_facts, "ratio.current_ratio")
    qr = latest_ratio(ratio_facts, "ratio.quick_ratio")
    if cr is not None:
        s = f"At {parse_period(cr.period_label).human()} the current ratio was {_d(cr)} [{cr.key}]"
        if qr is not None:
            s += f" and the quick ratio {_d(qr)} [{qr.key}]"
        p1.append(s + ".")
    inst = ctx.index.field("loan.installment") or next((f for f in ratio_facts if f.field == "loan.installment"), None)
    dscr = latest_ratio(ratio_facts, "ratio.dscr_new_loan")
    dscr2 = latest_ratio(ratio_facts, "ratio.dscr_incl_undeclared")
    und = latest_ratio(ratio_facts, "loan.undeclared_monthly")
    if dscr is not None:
        s = "Estimated debt service coverage for the requested loan"
        if inst is not None:
            s += f" (installment {_d(inst)} a month [{inst.key}])"
        p1.append(s + f" is {_d(dscr)} [{dscr.key}].")
    if dscr2 is not None and und is not None:
        p1.append(f"Including repayments of loans not declared in the application ({_d(und)} a month [{und.key}]), "
                  f"coverage falls to {_d(dscr2)} [{dscr2.key}].")
    p1 = _safe_join(p1, facts, fids)

    # 2 — issues: one non-empty, verifier-clean bullet per finding
    p2 = [_bullet(fd, facts, fids) for fd in findings if not (fd.severity == "info" and len(findings) > 4)]

    # 3 — before a decision
    steps: list[str] = []
    for fd in findings:
        step = NEXT_STEPS.get(fd.rule_id)
        if step and f"- {step}" not in steps:
            steps.append(f"- {step}")

    out = ["**Repayment capacity.** " + " ".join(p1) if p1 else "**Repayment capacity.** Not enough figures were "
           "extracted to describe repayment capacity."]
    if p2:
        out.append("**Issues found in the documents.**\n" + "\n".join(p2))
    else:
        out.append("**Issues found in the documents.** No contradictions were found by the reconciliation rules.")
    out.append("**Before a decision.**\n" + ("\n".join(steps) if steps else "- Review the extracted figures.")
               + f"\n\n{CLOSING_LINE}")
    return "\n\n".join(out)
