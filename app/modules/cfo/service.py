"""AI CFO (docs/plan/02-PIPELINE.md §8): a tool loop over the owner's facts store.

The model never sees documents and never does arithmetic: `sum_transactions`, `upcoming_obligations` and
`compute` register new citable facts, and the final answer goes through the same citation verifier as the
narrative. With the LLM off (or after two rejected answers) the reply is a keyword search over the facts.
"""
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.modules.borrowers.models import Borrower
from app.modules.borrowers.service import BorrowerService
from app.modules.cfo.models import CfoMessage, CfoThread
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.extraction.service import FactSerializer, fact_to_draft, persist_facts
from app.modules.llm import prompts
from app.modules.llm.narrative import redactor
from app.modules.llm.provider import LLMError, LLMUnavailable, available, complete, parse_json
from app.modules.statements.models import Transaction

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6
BUDGET_S = 20.0
MAX_VERIFY_ROUNDS = 2

ANSWER_SCHEMA = {
    "title": "cfo_answer", "type": "object",
    "properties": {
        "direct_answer": {"type": "string"},
        "table": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "fact_id": {"type": "string"}}, "required": ["label", "fact_id"]}},
        "cant_see": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["direct_answer", "table", "cant_see", "next_steps"],
}

TOOLS = [
    {"name": "search_facts", "description": "Find figures in the business's records by keywords.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "keywords, e.g. 'cash balance', 'revenue', 'loan repayment'"},
         "period": {"type": "string", "description": "optional: 2026-09, Q3-2026, H1-2026, FY2025"}},
         "required": ["query"]}},
    {"name": "sum_transactions", "description": "Total of bank-statement transactions; returns a new fact.",
     "parameters": {"type": "object", "properties": {
         "period": {"type": "string", "description": "YYYY-MM, or YYYY-MM..YYYY-MM"},
         "category": {"type": "string", "description": "sales_receipt, supplier_payment, salary, payroll_tax, tax, "
                                                       "loan_repayment, rent_utilities, bank_fee, other"},
         "counterparty": {"type": "string"},
         "direction": {"type": "string", "enum": ["in", "out"]}},
         "required": ["period"]}},
    {"name": "cash_balance_series", "description": "Month-end account balances between two months.",
     "parameters": {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
                    "required": ["from", "to"]}},
    {"name": "upcoming_obligations", "description": "Recurring payments expected in the next N days.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]}},
    {"name": "compute", "description": "Arithmetic over fact ids (+ − × ÷, parentheses). Returns a new fact.",
     "parameters": {"type": "object", "properties": {
         "expression": {"type": "string", "description": "e.g. 'f_ab12cd - f_ef34gh'"},
         "label": {"type": "string", "description": "what the result means, e.g. 'Cash after October payments'"}},
         "required": ["expression", "label"]}},
    {"name": "missing_data", "description": "Which documents would be needed for a topic the records do not cover.",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
]

MISSING = [  # topic keywords → document that would answer it
    (("receivable", "owes me", "customer debt", "unpaid invoice", "debitor", "aging"),
     "Sales ledger (invoices with due dates) — receivables by customer are not in the bank statement"),
    (("inventory", "stock", "yarn", "warehouse", "materials on hand"),
     "Stock count or Form 1 at the latest month end — inventory is only known at balance-sheet dates"),
    (("payable", "supplier debt", "owe to supplier", "creditor"),
     "Purchase ledger or supplier contracts — unpaid supplier invoices are not in the bank statement"),
    (("tax", "vat", "qqs", "profit tax"), "Tax declarations for the period"),
    (("profit", "margin", "p&l", "expenses"), "Form 2 (income statement) for the period"),
    (("forecast", "next month", "will i have", "enough cash"),
     "Signed contracts and expected receipts — future collections are not in the records"),
]

_WORD = re.compile(r"[a-zа-яўқғҳ0-9']+", re.IGNORECASE)
STOP = {"the", "a", "an", "is", "are", "my", "of", "in", "for", "to", "and", "what", "how", "why", "did", "do",
        "does", "i", "me", "was", "were", "be", "it", "this", "that", "on", "at", "much", "many", "with", "by"}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in STOP and len(w) > 1]


def _period_match(label: str, period: str | None) -> bool:
    if not period:
        return True
    p = period.strip().upper()
    return p in (label or "").upper()


class CfoService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ context
    def _load(self, borrower: Borrower) -> None:
        self.borrower = borrower
        docs = self.db.scalars(select(Document).where(Document.borrower_id == borrower.id,
                                                      Document.owner_kind != "public")).all()
        self.docs = {d.id: d for d in docs}
        doc_ids = list(self.docs) or [-1]
        rows = list(self.db.scalars(select(Fact).where(Fact.document_id.in_(doc_ids))).all())
        rows += list(self.db.scalars(select(Fact).where(Fact.borrower_id == borrower.id,
                                                        Fact.document_id.is_(None))).all())
        self.rows = {f.key: f for f in rows}
        self.facts = {f.key: fact_to_draft(f) for f in rows}
        self.txns = list(self.db.scalars(select(Transaction).where(Transaction.document_id.in_(doc_ids))
                                         .order_by(Transaction.booked_on)).all())
        self.recurring = [r for d in docs if d.doc_type == "bank_statement"
                          for r in ((d.summary or {}).get("recurring") or [])]
        self.statement_doc = next((d for d in docs if d.doc_type == "bank_statement"), None)

    def _register(self, drafts: list, document: Document | None = None) -> list[Fact]:
        rows, _ = persist_facts(self.db, drafts, document=document, borrower_id=self.borrower.id,
                                attach_computed=document is not None)
        for r in rows:
            self.rows[r.key] = r
            self.facts[r.key] = fact_to_draft(r)
        return rows

    def _brief(self, key: str) -> dict:
        from app.pipeline.compute import fact_display
        f = self.facts[key]
        d, u = fact_display(f)
        return {"id": key, "label": f.label, "display": f"{d} {u}".strip(), "period": f.period_label}

    # ------------------------------------------------------------------ tools
    def tool_search_facts(self, query: str, period: str | None = None, limit: int = 12) -> dict:
        toks = _tokens(query)
        scored = []
        for k, f in self.facts.items():
            hay = f"{f.label} {f.field} {f.period_label}".lower()
            score = sum(1 for t in toks if t in hay)
            if score and _period_match(f"{f.period_label} {f.label}", period):
                scored.append((score, f.period_label or "", k))
        top = sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]
        return {"facts": [self._brief(k) for _, _, k in top]}

    def tool_sum_transactions(self, period: str, category: str | None = None, counterparty: str | None = None,
                              direction: str | None = None) -> dict:
        from app.pipeline.types import FactDraft
        start, end = _period_bounds(period)
        if start is None:
            return {"error": "period must be YYYY-MM or YYYY-MM..YYYY-MM"}
        sel = [t for t in self.txns if start <= t.booked_on <= end]
        if category:
            sel = [t for t in sel if t.category == category]
        if counterparty:
            sel = [t for t in sel if counterparty.lower() in (t.counterparty or "").lower()]
        if direction == "in":
            sel = [t for t in sel if float(t.amount) > 0]
        elif direction == "out":
            sel = [t for t in sel if float(t.amount) < 0]
        total = sum(float(t.amount) for t in sel)
        if direction == "out":
            total = -total
        what = " ".join(x for x in [category or "all", f"from/to {counterparty}" if counterparty else "",
                                    {"in": "receipts", "out": "payments"}.get(direction or "", "transactions")] if x)
        rows = sorted(t.row_n for t in sel)
        draft = FactDraft(field=f"statement.sum.{category or 'all'}.{direction or 'net'}", label=f"Sum of {what}, {period}",
                          value=round(total / 1000.0, 3), unit="kUZS", kind="aggregate", period_label=period[:16],
                          passage=(f"{len(sel)} rows: {rows[0]}–{rows[-1]}" if rows else "no matching rows"),
                          method="aggregate", note=f"{len(sel)} transactions")
        row = self._register([draft], self.statement_doc)[0]
        return {"fact": self._brief(row.key), "transactions": len(sel)}

    def tool_cash_balance_series(self, **kw) -> dict:
        start, _ = _period_bounds(kw.get("from") or "")
        _, end = _period_bounds(kw.get("to") or "")
        out = []
        for k, f in self.facts.items():
            if f.field.startswith("statement.balance_end."):
                ym = f.field.rsplit(".", 1)[-1]
                s, e = _period_bounds(ym)
                if s and (start is None or s >= start) and (end is None or e <= end):
                    out.append((ym, k))
        return {"balances": [self._brief(k) for _, k in sorted(out)]}

    def tool_upcoming_obligations(self, days: int = 30) -> dict:
        from app.pipeline.types import FactDraft
        last = max((t.booked_on for t in self.txns), default=None)
        if last is None:
            return {"obligations": [], "note": "no bank statement uploaded"}
        horizon = last + timedelta(days=int(days or 30))
        drafts, labels = [], []
        for g in self.recurring:
            if not isinstance(g, dict) or g.get("category") in ("sales_receipt", "own_transfer"):
                continue
            nd = g.get("next_due")
            try:
                due = date.fromisoformat(nd) if isinstance(nd, str) else None
            except ValueError:
                due = None
            if due is None or due > horizon:
                continue
            amount = abs(float(g.get("amount_uzs") or 0))
            drafts.append(FactDraft(field=f"statement.expected.{g.get('group')}", label=f"Expected: {g.get('label')}",
                                    value=round(amount / 1000.0, 3), unit="kUZS", kind="aggregate",
                                    period_label=due.isoformat(), method="aggregate",
                                    passage=f"recurring on day {g.get('day_of_month')}, {g.get('count')} months seen",
                                    note="typical monthly amount of a recurring payment", inputs=list(g.get("evidence") or [])))
            labels.append(due.isoformat())
        rows = self._register(drafts, self.statement_doc) if drafts else []
        return {"obligations": [self._brief(r.key) | {"due": lab} for r, lab in zip(rows, labels)],
                "as_of_statement_end": last.isoformat()}

    def tool_compute(self, expression: str, label: str = "") -> dict:
        from app.pipeline.compute import ComputeError, compute
        try:
            draft = compute(expression, self.facts, label=label or expression)
        except ComputeError as exc:
            return {"error": str(exc)}
        row = self._register([draft])[0]
        return {"fact": self._brief(row.key)}

    def tool_missing_data(self, topic: str) -> dict:
        t = (topic or "").lower()
        hits = [doc for keys, doc in MISSING if any(k in t for k in keys)]
        have = sorted({d.doc_type for d in self.docs.values()})
        return {"missing": hits or ["A document covering this topic"], "documents_on_file": have}

    def _run_tool(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(**{k: v for k, v in (args or {}).items() if not k.startswith("_")})
        except TypeError as exc:
            return {"error": f"bad arguments: {exc}"}

    # ------------------------------------------------------------------ answering
    def ask(self, user, question: str) -> dict:
        question = (question or "").strip()
        if not question:
            raise AppException(code="question_required", status_code=422, detail="Ask a question")
        borrower = BorrowerService(self.db).owner_borrower(user)
        self._load(borrower)
        thread = self._thread(borrower, user)
        self.db.add(CfoMessage(thread_id=thread.id, role="user", content=question))
        self.db.flush()
        result = None
        if available(self.db):
            try:
                result = self._llm_answer(question)
            except (LLMUnavailable, LLMError) as exc:
                logger.warning("CFO LLM path failed: %s", exc)
        if result is None:
            result = self._facts_only(question, llm_on=available(self.db))
        msg = CfoMessage(thread_id=thread.id, role="assistant", content=result["answer"]["direct_answer"],
                         answer=result["answer"], citations=result["citations"], tool_trace=result["tool_trace"],
                         mode=result["mode"])
        self.db.add(msg)
        self.db.commit()
        return self._out(msg)

    def _llm_answer(self, question: str) -> dict | None:
        from app.pipeline.verify import feedback_message, verify_cfo_answer

        redact = redactor([self.borrower.name], [self.borrower.stir])
        context = {"business": "the borrower", "documents_on_file": sorted({d.doc_type for d in self.docs.values()}),
                   "statement_period": self._statement_span()}
        messages = [{"role": "system", "content": prompts.load("cfo")},
                    {"role": "user", "content": redact(f"Context: {json.dumps(context)}\nQuestion: {question}")}]
        trace, calls, t0 = [], 0, time.monotonic()
        for verify_round in range(MAX_VERIFY_ROUNDS):
            answer = None
            while True:
                over = calls >= MAX_TOOL_CALLS or time.monotonic() - t0 > BUDGET_S
                res = complete(self.db, "cfo", messages, tools=None if over else TOOLS,
                               json_schema=ANSWER_SCHEMA if over else None)
                messages.append(res.message or {"role": "assistant", "content": res.text})
                if res.tool_calls and not over:
                    for tc in res.tool_calls:
                        calls += 1
                        out = self._run_tool(tc.name, tc.arguments)
                        trace.append({"tool": tc.name, "args": tc.arguments,
                                      "result_key": (out.get("fact") or {}).get("id"),
                                      "result": _short(out)})
                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "content": redact(json.dumps(out, ensure_ascii=False))})
                    continue
                answer = parse_json(res.text)
                if answer is None and not over:
                    calls = MAX_TOOL_CALLS        # force a schema-constrained final answer next round
                    messages.append({"role": "user", "content": "Reply now with the JSON answer object only."})
                    continue
                break
            if answer is None:
                return None
            answer = _normalise_answer(answer)
            report = verify_cfo_answer(answer, self.facts)
            if report.get("ok"):
                return {"answer": answer, "citations": report.get("cited", []), "tool_trace": trace, "mode": "llm",
                        "verifier": report}
            trace.append({"tool": "verifier", "args": {}, "result_key": None,
                          "result": {"rejected": [u.get("text") for u in report.get("unmatched", [])][:8],
                                     "unknown_ids": report.get("unknown_ids", [])}})
            messages.append({"role": "user", "content": feedback_message(report)})
            calls = min(calls, MAX_TOOL_CALLS - 1)
        out = self._facts_only(question, llm_on=True)
        out["answer"]["direct_answer"] = ("I can't answer that from the records with verified numbers. "
                                          "These are the records that match your question.")
        out["tool_trace"] = trace
        return out

    def _facts_only(self, question: str, llm_on: bool) -> dict:
        found = self.tool_search_facts(question, limit=8)["facts"]
        miss = self.tool_missing_data(question)["missing"]
        lead = ("These records match your question." if llm_on else
                "The language model is off. These records match your question.")
        if not found:
            lead = "No figure in the records matches your question."
        answer = {"direct_answer": lead, "table": [{"label": f["label"], "fact_id": f["id"]} for f in found],
                  "cant_see": miss[0] if miss and not found else "", "next_steps": []}
        return {"answer": answer, "citations": [f["id"] for f in found], "tool_trace": [], "mode": "facts_only"}

    def _statement_span(self) -> str:
        if not self.txns:
            return "no bank statement"
        return f"{self.txns[0].booked_on.isoformat()[:7]}..{self.txns[-1].booked_on.isoformat()[:7]}"

    def _thread(self, borrower: Borrower, user) -> CfoThread:
        th = self.db.scalars(select(CfoThread).where(CfoThread.borrower_id == borrower.id,
                                                     CfoThread.user_id == user.id)).first()
        if th is None:
            th = CfoThread(borrower_id=borrower.id, user_id=user.id, title="AI CFO")
            self.db.add(th)
            self.db.flush()
        return th

    def _out(self, msg: CfoMessage) -> dict:
        answer = dict(msg.answer or {})
        table = [{"label": r.get("label", ""), "fact_key": r.get("fact_id") or r.get("fact_key")}
                 for r in answer.get("table") or []]
        answer["table"] = table
        keys = set(msg.citations or []) | {r["fact_key"] for r in table if r["fact_key"]}
        keys |= {t.get("result_key") for t in msg.tool_trace or [] if t.get("result_key")}
        keys |= set(re.findall(r"f_[A-Za-z0-9]{2,24}", json.dumps(answer)))
        rows = [r for r in self.db.scalars(select(Fact).where(Fact.key.in_(list(keys) or ["-"]))).all()]
        return {"uuid": str(msg.uuid), "question": None, "answer": answer, "citations": list(msg.citations or []),
                "tool_trace": msg.tool_trace or [], "mode": msg.mode,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "facts": FactSerializer(self.db).by_key(rows)}

    def history(self, user) -> dict:
        borrower = BorrowerService(self.db).owner_borrower(user)
        th = self.db.scalars(select(CfoThread).where(CfoThread.borrower_id == borrower.id,
                                                     CfoThread.user_id == user.id)).first()
        if th is None:
            return {"business": {"name": borrower.name}, "messages": []}
        msgs = self.db.scalars(select(CfoMessage).where(CfoMessage.thread_id == th.id).order_by(CfoMessage.id)).all()
        out = []
        for m in msgs:
            if m.role == "user":
                out.append({"role": "user", "content": m.content,
                            "created_at": m.created_at.isoformat() if m.created_at else None})
            else:
                out.append({"role": "assistant", **self._out(m)})
        return {"business": {"name": borrower.name}, "messages": out}


def _period_bounds(period: str) -> tuple[date | None, date | None]:
    import calendar
    p = (period or "").strip()
    parts = p.split("..")
    try:
        if len(parts) == 2:
            s, _ = _period_bounds(parts[0])
            _, e = _period_bounds(parts[1])
            return s, e
        if re.fullmatch(r"\d{4}-\d{2}", p):
            y, m = int(p[:4]), int(p[5:])
            return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
            d = date.fromisoformat(p)
            return d, d
        if m := re.fullmatch(r"Q([1-4])-(\d{4})", p.upper()):
            q, y = int(m.group(1)), int(m.group(2))
            return date(y, 3 * q - 2, 1), date(y, 3 * q, calendar.monthrange(y, 3 * q)[1])
        if m := re.fullmatch(r"H([12])-(\d{4})", p.upper()):
            h, y = int(m.group(1)), int(m.group(2))
            return (date(y, 1, 1), date(y, 6, 30)) if h == 1 else (date(y, 7, 1), date(y, 12, 31))
        if m := re.fullmatch(r"FY(\d{4})", p.upper()):
            y = int(m.group(1))
            return date(y, 1, 1), date(y, 12, 31)
    except ValueError:
        return None, None
    return None, None


def _normalise_answer(a: dict) -> dict:
    table = []
    for r in a.get("table") or []:
        if isinstance(r, dict):
            table.append({"label": str(r.get("label") or ""), "fact_id": str(r.get("fact_id") or r.get("fact_key") or "")})
    steps = [str(s) for s in (a.get("next_steps") or []) if str(s).strip()][:3]
    return {"direct_answer": str(a.get("direct_answer") or ""), "table": table,
            "cant_see": str(a.get("cant_see") or ""), "next_steps": steps}


def _short(out: dict) -> dict:
    s = json.dumps(out, ensure_ascii=False, default=str)
    return out if len(s) < 1500 else {"summary": s[:1500] + "…"}
