"""Inputs for reconciliation rules and ratios."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.pipeline.compute import constant_fact, display_with_unit, ensure_key
from app.pipeline.rules.index import FactIndex
from app.pipeline.rules.periods import to_date
from app.pipeline.types import FactDraft, TxnDraft


@dataclass
class AppContext:
    """Everything known about one loan application.

    facts        extracted + aggregate facts (keys assigned; missing keys are assigned here)
    transactions categorised statement rows (recurring_group set)
    documents    [{uuid, filename, doc_type, period_start, period_end, stir, sha256}]
    application  {requested_amount (kUZS), term_months, rate_pct, installment (kUZS), received_on,
                  borrower_stir, declared_revenue_fy (kUZS), declared_revenue_year,
                  declared_debts: [{lender, contract_no, monthly (kUZS), outstanding (kUZS)}],
                  declared_debts_total (kUZS outstanding)}; facts with field "application.<name>" win over these
    recurring    groups from normalise_statement (optional; rebuilt from transactions when empty)
    fact_document fact key → document uuid (enables the R12 conflicting-values check)

    Rules and ratios append every number they state to `derived_facts`. **The runner must persist
    derived_facts** (they are cited as evidence).
    """
    facts: list[FactDraft]
    transactions: list[TxnDraft] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    application: dict = field(default_factory=dict)
    recurring: list[dict] = field(default_factory=list)
    fact_document: dict[str, str] = field(default_factory=dict)
    derived_facts: list[FactDraft] = field(default_factory=list)
    _index: FactIndex | None = field(default=None, repr=False)

    @property
    def index(self) -> FactIndex:
        if self._index is None:
            for f in self.facts:
                ensure_key(f)
            self._index = FactIndex(list(self.facts))
            for f in self.derived_facts:
                self._index.add(f)
        return self._index

    def derive(self, fact: FactDraft) -> FactDraft:
        ensure_key(fact)
        self.derived_facts.append(fact)
        self.index.add(fact)
        return fact

    @property
    def received_on(self) -> date | None:
        f = self.index.field("application.received_on")
        return to_date(self.application.get("received_on")) or (to_date(f.printed) if f else None)

    def app_value(self, name: str) -> tuple[float | None, FactDraft | None]:
        f = self.index.field(f"application.{name}")
        if f is not None:
            return f.value, f
        v = self.application.get(name)
        if v is None or v == "":
            return None, None
        try:
            return float(v), None
        except (TypeError, ValueError):
            return None, None

    def app_fact(self, name: str, label: str, unit: str = "kUZS", period_label: str = "") -> FactDraft | None:
        """The application value as a citable fact (creates a derived fact from the declared input if needed)."""
        v, f = self.app_value(name)
        if f is not None:
            return f
        if v is None:
            return None
        return self.derive(constant_fact(f"application.{name}", label, v, unit, period_label=period_label,
                                         formula="application form", note="declared in the loan application",
                                         method="rule", kind="extracted"))

    def docs_of(self, doc_type: str) -> list[dict]:
        return [d for d in self.documents if d.get("doc_type") == doc_type]


def money(f: FactDraft | None) -> str:
    return display_with_unit(f) if f is not None else "n/a"
