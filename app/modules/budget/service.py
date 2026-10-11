"""Owner budget (plan vs actual) and advice.

Actuals come from facts the pipeline produced: bank-statement monthly totals (`statement.inflow.total.YYYY-MM`,
`statement.outflow.total.YYYY-MM`, per-category outflows) and, for months without a statement, the owner's
cash-flow table (`cashflow.inflow.YYYY-MM`). Differences are computed here in Python.

Advice: deterministic rules produce findings with numbers that are facts (plan figures and differences are
registered as facts through `compute`, so every number is citable). The LLM — only through the provider — may
rewrite each finding in plain words; each rewrite must pass the citation verifier, otherwise the rule text is
shown. With the LLM off, the rule texts are the advice.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.audit.service import record
from app.modules.borrowers.service import BorrowerService
from app.modules.budget.models import BudgetAdvice, BudgetLine
from app.modules.cfo.service import CfoService
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer
from app.modules.llm import prompts
from app.modules.llm.narrative import redactor
from app.modules.llm.provider import LLMError, LLMUnavailable, available, complete, parse_json
from app.pipeline.cashflow import month_human
from app.pipeline.compute import ComputeError, compute, constant_fact, display_with_unit, to_kuzs
from app.pipeline.statements.categorise import CATEGORY_LABELS

logger = logging.getLogger(__name__)

MAX_MONTHS = 12
OVER_PLAN = 0.05          # spending more than 5% above plan → finding
REVENUE_GAP = 0.20        # Form 2 revenue vs bank receipts differ by more than 20% → finding
DEBT_SHARE_WATCH = 20.0   # loan repayments above 20% of money out → watch

ADVICE_SCHEMA = {
    "title": "budget_advice", "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "text": {"type": "string"}}, "required": ["id", "text"]}}},
    "required": ["items"],
}


def _uzs(f) -> float:
    return round(to_kuzs(float(f.value), f.unit) * 1000.0, 2)


class BudgetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ data
    def _ctx(self, user) -> CfoService:
        borrower = BorrowerService(self.db).owner_borrower(user)
        cfo = CfoService(self.db)
        cfo._load(borrower)
        return cfo

    def _lines(self, borrower_id: int) -> list[BudgetLine]:
        return list(self.db.scalars(select(BudgetLine).where(BudgetLine.borrower_id == borrower_id)
                                    .order_by(BudgetLine.month, BudgetLine.category)).all())

    @staticmethod
    def _actuals(cfo: CfoService) -> dict[str, dict]:
        """month → {income_key, spending_key, source, categories{cat: key}} from facts (statement wins)."""
        months: dict[str, dict] = {}
        for k, f in cfo.facts.items():
            parts = f.field.split(".")
            if len(parts) != 4 and not (len(parts) == 3 and parts[0] == "cashflow"):
                continue
            ym = parts[-1]
            if len(ym) != 7 or ym[4] != "-":
                continue
            m = months.setdefault(ym, {"statement": {}, "cashflow": {}, "categories": {}})
            if parts[0] == "statement" and parts[2] == "total" and parts[1] in ("inflow", "outflow"):
                m["statement"][parts[1]] = k
            elif parts[0] == "statement" and parts[1] == "outflow":
                m["categories"][parts[2]] = k
            elif parts[0] == "statement" and parts[1] == "balance_end":
                pass
            elif parts[0] == "cashflow" and parts[1] in ("inflow", "outflow", "balance_end"):
                m["cashflow"][parts[1]] = k
        for k, f in cfo.facts.items():
            if f.field.startswith("statement.balance_end."):
                ym = f.field.rsplit(".", 1)[-1]
                months.setdefault(ym, {"statement": {}, "cashflow": {}, "categories": {}})["statement"]["balance_end"] = k
        out = {}
        for ym, m in months.items():
            src = "statement" if ("inflow" in m["statement"] or "outflow" in m["statement"]) else (
                "cashflow" if m["cashflow"] else None)
            if src is None and "balance_end" not in m["statement"]:
                continue
            pick = m[src] if src else {}
            out[ym] = {"source": src, "income_key": pick.get("inflow"), "spending_key": pick.get("outflow"),
                       "balance_key": m["statement"].get("balance_end") or m["cashflow"].get("balance_end"),
                       "categories": m["categories"] if src == "statement" else {}}
        return out

    def _doc_ref(self, cfo: CfoService, key: str | None) -> dict | None:
        if not key or key not in cfo.rows:
            return None
        row = cfo.rows[key]
        doc = cfo.docs.get(row.document_id) if row.document_id else None
        return {"fact_key": key, "label": row.label, "document_uuid": str(doc.uuid) if doc else None,
                "filename": doc.filename if doc else None, "doc_type": doc.doc_type if doc else None,
                "page_n": row.page_n}

    # ------------------------------------------------------------------ budget
    def get(self, user) -> dict:
        cfo = self._ctx(user)
        lines = self._lines(cfo.borrower.id)
        actual = self._actuals(cfo)
        plan: dict[str, dict] = {}
        for ln in lines:
            plan.setdefault(ln.month, {})[ln.category] = ln
        months = sorted(set(plan) | {ym for ym, a in actual.items() if a["source"]})[-MAX_MONTHS:]
        rows = []
        for ym in months:
            p = plan.get(ym, {}).get("total")
            a = actual.get(ym) or {"source": None, "income_key": None, "spending_key": None, "categories": {}}
            inc = _uzs(cfo.facts[a["income_key"]]) if a.get("income_key") else None
            spd = _uzs(cfo.facts[a["spending_key"]]) if a.get("spending_key") else None
            p_inc = float(p.planned_income) if p is not None and p.planned_income is not None else None
            p_spd = float(p.planned_spending) if p is not None and p.planned_spending is not None else None
            cats = []
            for cat in sorted(set(a.get("categories", {})) | {c for c in plan.get(ym, {}) if c != "total"}):
                ck = a.get("categories", {}).get(cat)
                cl = plan.get(ym, {}).get(cat)
                act = _uzs(cfo.facts[ck]) if ck else None
                pl = float(cl.planned_spending) if cl is not None and cl.planned_spending is not None else None
                cats.append({"category": cat, "label": CATEGORY_LABELS.get(cat, cat), "planned_spending": pl,
                             "actual_spending": act, "difference": round(act - pl, 2) if act is not None and pl is not None else None,
                             "fact_key": ck})
            rows.append({
                "month": ym, "label": month_human(ym), "source": a.get("source"),
                "planned_income": p_inc, "planned_spending": p_spd,
                "actual_income": inc, "actual_spending": spd,
                "income_difference": round(inc - p_inc, 2) if inc is not None and p_inc is not None else None,
                "spending_difference": round(spd - p_spd, 2) if spd is not None and p_spd is not None else None,
                "net_actual": round(inc - spd, 2) if inc is not None and spd is not None else None,
                "income_ref": self._doc_ref(cfo, a.get("income_key")),
                "spending_ref": self._doc_ref(cfo, a.get("spending_key")),
                "categories": cats,
            })
        docs = sorted({d.doc_type for d in cfo.docs.values()})
        return {"business": {"name": cfo.borrower.name}, "unit": "UZS", "months": rows,
                "documents_on_file": docs,
                "has_actuals": any(r["source"] for r in rows),
                "categories": [{"id": c, "label": CATEGORY_LABELS.get(c, c)} for c in CATEGORY_LABELS
                               if c not in ("sales_receipt", "loan_disbursement", "own_transfer")]}

    def put(self, user, lines: list[dict]) -> dict:
        borrower = BorrowerService(self.db).owner_borrower(user)
        months = sorted({ln["month"] for ln in lines})
        before = [{"month": x.month, "category": x.category, "planned_income": float(x.planned_income or 0),
                   "planned_spending": float(x.planned_spending or 0)}
                  for x in self._lines(borrower.id) if x.month in months]
        if months:
            self.db.execute(delete(BudgetLine).where(BudgetLine.borrower_id == borrower.id,
                                                     BudgetLine.month.in_(months)))
        seen = set()
        for ln in lines:
            key = (ln["month"], ln.get("category") or "total")
            if key in seen or (ln.get("planned_income") is None and ln.get("planned_spending") is None):
                continue
            seen.add(key)
            self.db.add(BudgetLine(borrower_id=borrower.id, month=key[0], category=key[1],
                                   planned_income=ln.get("planned_income"), planned_spending=ln.get("planned_spending")))
        record(self.db, user, "budget.update", "borrower", borrower.uuid, before={"lines": before},
               after={"lines": [dict(m) for m in lines]})
        self.db.commit()
        return self.get(user)

    # ------------------------------------------------------------------ advice
    def latest_advice(self, user) -> dict:
        borrower = BorrowerService(self.db).owner_borrower(user)
        row = self.db.scalars(select(BudgetAdvice).where(BudgetAdvice.borrower_id == borrower.id)
                              .order_by(BudgetAdvice.id.desc())).first()
        if row is None:
            return {"items": [], "mode": None, "generated_at": None, "facts": {}}
        return self._advice_out(row)

    def _advice_out(self, row: BudgetAdvice) -> dict:
        keys = {k for it in row.items or [] for k in it.get("fact_keys", [])}
        facts = list(self.db.scalars(select(Fact).where(Fact.key.in_(list(keys) or ["-"]))).all())
        return {"uuid": str(row.uuid), "items": row.items, "mode": row.mode,
                "generated_at": row.created_at.isoformat() if row.created_at else None,
                "facts": FactSerializer(self.db).by_key(facts)}

    def generate_advice(self, user) -> dict:
        cfo = self._ctx(user)
        b = cfo.borrower
        # previous advice runs' plan/difference facts are replaced
        old = [k for k, f in cfo.rows.items() if f.field.startswith("budget.") and f.document_id is None]
        if old:
            self.db.execute(delete(Fact).where(Fact.key.in_(old)))
            for k in old:
                cfo.rows.pop(k, None)
                cfo.facts.pop(k, None)
        items = self.rules(cfo)
        mode = "rules"
        if items and available(self.db):
            try:
                if self._explain(cfo, items):
                    mode = "llm"
            except (LLMUnavailable, LLMError) as exc:
                logger.warning("advice LLM path failed: %s", exc)
        row = BudgetAdvice(borrower_id=b.id, mode=mode, items=items)
        self.db.add(row)
        self.db.flush()
        record(self.db, user, "budget.advice", "borrower", b.uuid, after={"items": len(items), "mode": mode})
        self.db.commit()
        return self._advice_out(row)

    # -- rules (deterministic; every number in `rule_text` is a cited fact)
    def _fact(self, cfo: CfoService, draft) -> str:
        return cfo._register([draft])[0].key

    def _disp(self, cfo: CfoService, key: str) -> str:
        return display_with_unit(cfo.facts[key])

    def _item(self, cfo, id_, severity, title, text, keys) -> dict:
        refs = [r for r in (self._doc_ref(cfo, k) for k in keys) if r and r.get("document_uuid")]
        uniq = {r["document_uuid"]: r for r in refs}
        return {"id": id_, "severity": severity, "title": title, "rule_text": text, "text": text,
                "explained": False, "fact_keys": list(dict.fromkeys(keys)), "sources": list(uniq.values())}

    def rules(self, cfo: CfoService) -> list[dict]:
        items: list[dict] = []
        actual = self._actuals(cfo)
        plan = {(ln.month, ln.category): ln for ln in self._lines(cfo.borrower.id)}

        # A1 / A2: latest month with both a plan and actuals — spending above plan, income below plan
        months = sorted(ym for ym in actual if (ym, "total") in plan and actual[ym]["source"])
        if months:
            ym = months[-1]
            a, p = actual[ym], plan[(ym, "total")]
            if a["spending_key"] and p.planned_spending is not None:
                pk = self._fact(cfo, constant_fact(f"budget.plan.spending.{ym}", f"Planned spending, {month_human(ym)}",
                                                   float(p.planned_spending) / 1000.0, "kUZS", period_label=ym,
                                                   method="owner_plan", kind="aggregate",
                                                   note="entered by the owner on the Budget page"))
                act = cfo.facts[a["spending_key"]]
                if to_kuzs(float(act.value), act.unit) > float(p.planned_spending) / 1000.0 * (1 + OVER_PLAN):
                    dk = self._compute(cfo, f"{a['spending_key']} - {pk}", f"Spending above plan, {month_human(ym)}",
                                       f"budget.diff.spending.{ym}")
                    if dk:
                        items.append(self._item(cfo, "A1", "attention", "Spending is above your plan",
                            f"In {month_human(ym)} you spent {self._disp(cfo, a['spending_key'])} [{a['spending_key']}] "
                            f"against a plan of {self._disp(cfo, pk)} [{pk}], which is {self._disp(cfo, dk)} more "
                            f"than planned [{dk}].", [a["spending_key"], pk, dk]))
                # biggest category over its own limit
                worst = None
                for cat, ck in a["categories"].items():
                    cl = plan.get((ym, cat))
                    if cl is None or cl.planned_spending is None:
                        continue
                    over = to_kuzs(float(cfo.facts[ck].value), cfo.facts[ck].unit) - float(cl.planned_spending) / 1000.0
                    if over > 0 and (worst is None or over > worst[2]):
                        worst = (cat, ck, over, cl)
                if worst:
                    cat, ck, _, cl = worst
                    lk = self._fact(cfo, constant_fact(f"budget.plan.{cat}.{ym}",
                                                       f"Planned {CATEGORY_LABELS.get(cat, cat).lower()}, {month_human(ym)}",
                                                       float(cl.planned_spending) / 1000.0, "kUZS", period_label=ym,
                                                       method="owner_plan", kind="aggregate",
                                                       note="entered by the owner on the Budget page"))
                    items.append(self._item(cfo, "A3", "watch", f"{CATEGORY_LABELS.get(cat, cat)} above its limit",
                        f"{CATEGORY_LABELS.get(cat, cat)} in {month_human(ym)} came to {self._disp(cfo, ck)} [{ck}], "
                        f"above your limit of {self._disp(cfo, lk)} [{lk}].", [ck, lk]))
            if a["income_key"] and p.planned_income is not None:
                pk = self._fact(cfo, constant_fact(f"budget.plan.income.{ym}", f"Planned income, {month_human(ym)}",
                                                   float(p.planned_income) / 1000.0, "kUZS", period_label=ym,
                                                   method="owner_plan", kind="aggregate",
                                                   note="entered by the owner on the Budget page"))
                inc = cfo.facts[a["income_key"]]
                if to_kuzs(float(inc.value), inc.unit) < float(p.planned_income) / 1000.0 * (1 - OVER_PLAN):
                    dk = self._compute(cfo, f"{pk} - {a['income_key']}", f"Income below plan, {month_human(ym)}",
                                       f"budget.diff.income.{ym}")
                    if dk:
                        items.append(self._item(cfo, "A2", "watch", "Income is below your plan",
                            f"In {month_human(ym)} money in was {self._disp(cfo, a['income_key'])} [{a['income_key']}] "
                            f"against a plan of {self._disp(cfo, pk)} [{pk}], {self._disp(cfo, dk)} short [{dk}].",
                            [a["income_key"], pk, dk]))

        # B1: cash at month end fell three months in a row
        bal = sorted((ym, x["balance_key"]) for ym, x in actual.items() if x.get("balance_key"))
        if len(bal) >= 4:
            last4 = bal[-4:]
            vals = [float(cfo.facts[k].value) for _, k in last4]
            if all(vals[i + 1] < vals[i] for i in range(3)):
                (y0, k0), (y3, k3) = last4[0], last4[-1]
                dk = self._compute(cfo, f"{k0} - {k3}", f"Fall in cash, {month_human(y0)} to {month_human(y3)}",
                                   f"budget.diff.balance.{y3}")
                if dk:
                    items.append(self._item(cfo, "B1", "attention", "Cash has fallen three months in a row",
                        f"Cash at the end of {month_human(y0)} was {self._disp(cfo, k0)} [{k0}] and at the end of "
                        f"{month_human(y3)} it was {self._disp(cfo, k3)} [{k3}]: down {self._disp(cfo, dk)} [{dk}], "
                        f"falling every month.", [k0, last4[1][1], last4[2][1], k3, dk]))

        # B2: spending exceeded income in the latest month with both
        both = sorted(ym for ym, x in actual.items() if x["income_key"] and x["spending_key"])
        if both:
            ym = both[-1]
            ik, sk = actual[ym]["income_key"], actual[ym]["spending_key"]
            if float(cfo.facts[sk].value) > float(cfo.facts[ik].value):
                dk = self._compute(cfo, f"{sk} - {ik}", f"Money out above money in, {month_human(ym)}",
                                   f"budget.diff.net.{ym}")
                if dk:
                    items.append(self._item(cfo, "B2", "watch", "More money went out than came in",
                        f"In {month_human(ym)} money out was {self._disp(cfo, sk)} [{sk}] and money in was "
                        f"{self._disp(cfo, ik)} [{ik}], so {self._disp(cfo, dk)} more left the business than came "
                        f"in [{dk}].", [sk, ik, dk]))

        # C1: Form 2 revenue vs customer receipts in the bank for the same year
        rev = [(k, f) for k, f in cfo.facts.items() if f.field.startswith("form2.010") and
               (f.period_label or "").upper().startswith("FY")]
        if rev:
            rk, rf = sorted(rev, key=lambda kv: kv[1].period_label)[-1]
            year = rf.period_label[2:6]
            rec = [k for k, f in cfo.facts.items()
                   if f.field.startswith("statement.inflow.sales_receipt.") and f.field.endswith(tuple(
                       f"{year}-{m:02d}" for m in range(1, 13)))]
            if len(rec) >= 1:
                sk = self._compute(cfo, " + ".join(sorted(rec)) if len(rec) > 1 else f"{rec[0]} + 0",
                                   f"Customer receipts in the bank, {year}", f"budget.receipts.{year}")
                if sk:
                    r_v = to_kuzs(float(rf.value), rf.unit)
                    s_v = to_kuzs(float(cfo.facts[sk].value), cfo.facts[sk].unit)
                    if r_v > 0 and abs(r_v - s_v) / r_v > REVENUE_GAP:
                        gk = self._compute(cfo, f"{rk} - {sk}", f"Revenue not seen in the bank, {year}",
                                           f"budget.gap.revenue.{year}")
                        partial = len(rec) < 12
                        if gk:
                            items.append(self._item(cfo, "C1", "watch", "Revenue and bank receipts do not match",
                                f"Form 2 shows revenue of {self._disp(cfo, rk)} [{rk}], but customer receipts in the bank "
                                f"statement come to {self._disp(cfo, sk)} [{sk}], a gap of {self._disp(cfo, gk)} [{gk}]."
                                + (" The statement does not cover the whole year, so part of the gap may be months that"
                                   " are not uploaded." if partial else
                                   " Cash sales, a second bank account or unpaid invoices can explain this; the bank will"
                                   " ask."), [rk, sk, gk]))

        # D1: share of money out that goes to loan repayments (last up to three statement months)
        st_months = sorted(ym for ym, x in actual.items() if x["source"] == "statement" and x["spending_key"])[-3:]
        loan = [actual[ym]["categories"].get("loan_repayment") for ym in st_months]
        loan = [k for k in loan if k]
        if loan:
            outs = [actual[ym]["spending_key"] for ym in st_months]
            lk = self._compute(cfo, " + ".join(loan) + (" + 0" if len(loan) == 1 else ""),
                               "Loan repayments, last months of the statement", "budget.sum.loan_repayment")
            ok_ = self._compute(cfo, " + ".join(outs) + (" + 0" if len(outs) == 1 else ""),
                                "Money out, last months of the statement", "budget.sum.outflow")
            if lk and ok_:
                sh = self._compute(cfo, f"{lk} / {ok_} * 100", "Loan repayments as a share of money out",
                                   "budget.share.loan_repayment", unit="pct")
                if sh:
                    high = float(cfo.facts[sh].value) > DEBT_SHARE_WATCH
                    items.append(self._item(cfo, "D1", "watch" if high else "info",
                        "Loan repayments take a large share of spending" if high else "Loan repayments",
                        f"Loan repayments were {self._disp(cfo, lk)} [{lk}] out of {self._disp(cfo, ok_)} of money out "
                        f"[{ok_}], or {self._disp(cfo, sh)} [{sh}]."
                        + (" A new loan would add to this; plan repayments against the months with the lowest income."
                           if high else ""), [lk, ok_, sh]))

        # E1: largest spending category in the latest statement month
        if st_months:
            ym = st_months[-1]
            cats = {c: k for c, k in actual[ym]["categories"].items() if c not in ("own_transfer",)}
            if cats:
                c, ck = max(cats.items(), key=lambda kv: float(cfo.facts[kv[1]].value))
                items.append(self._item(cfo, "E1", "info", f"Biggest spending: {CATEGORY_LABELS.get(c, c).lower()}",
                    f"The largest spending line in {month_human(ym)} was {CATEGORY_LABELS.get(c, c).lower()}: "
                    f"{self._disp(cfo, ck)} [{ck}].", [ck]))
        return items

    def _compute(self, cfo: CfoService, expr: str, label: str, field: str, unit: str | None = None) -> str | None:
        try:
            draft = compute(expr, cfo.facts, label=label, field=field, unit=unit)
        except ComputeError as exc:
            logger.warning("advice compute failed (%s): %s", expr, exc)
            return None
        return self._fact(cfo, draft)

    # -- plain-language explanation (LLM through the provider, each item verified)
    def _explain(self, cfo: CfoService, items: list[dict]) -> bool:
        from app.pipeline.verify import verify

        redact = redactor([cfo.borrower.name], [cfo.borrower.stir])
        payload = [{"id": it["id"], "finding": it["rule_text"],
                    "facts": [{"id": k, "label": cfo.facts[k].label, "display": display_with_unit(cfo.facts[k])}
                              for k in it["fact_keys"] if k in cfo.facts]} for it in items]
        messages = [{"role": "system", "content": prompts.load("advice")},
                    {"role": "user", "content": redact(json.dumps({"findings": payload}, ensure_ascii=False))}]
        res = complete(self.db, "advice", messages, json_schema=ADVICE_SCHEMA)
        data = parse_json(res.text) or {}
        by_id = {str(x.get("id")): str(x.get("text") or "") for x in data.get("items") or [] if isinstance(x, dict)}
        any_ok = False
        for it in items:
            text = by_id.get(it["id"], "").strip()
            if not text:
                continue
            allowed = {k: cfo.facts[k] for k in it["fact_keys"] if k in cfo.facts}
            report = verify(text, allowed)
            if report.get("ok"):
                it["text"], it["explained"] = text, True
                any_ok = True
            else:
                it["verifier_rejected"] = [u.get("text") for u in report.get("unmatched", [])][:5] + \
                    report.get("forbidden", [])[:3] + report.get("unknown_ids", [])[:3]
        return any_ok
