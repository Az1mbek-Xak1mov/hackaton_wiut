"""Transaction categoriser: own-STIR rule → ordered regex rules (rules.yaml) → TF-IDF + logistic regression.

The model is trained on the generator's train split by `eval/train_categoriser.py` and stored in
`model.joblib` next to this file. Without the model file the categoriser runs on rules only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.pipeline.statements.text import norm, strip_vat_mentions, uz_cyr_to_lat

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "rules.yaml"
MODEL_PATH = HERE / "model.joblib"

CATEGORIES = [
    "sales_receipt", "supplier_payment", "salary", "payroll_tax", "tax", "loan_repayment",
    "loan_disbursement", "rent_utilities", "own_transfer", "cash_withdrawal", "bank_fee", "other",
]
INFLOW_CATEGORIES = {"sales_receipt", "loan_disbursement", "own_transfer", "other"}
OUTFLOW_CATEGORIES = set(CATEGORIES) - {"sales_receipt", "loan_disbursement"}
CATEGORY_LABELS = {
    "sales_receipt": "Customer receipts",
    "supplier_payment": "Supplier payments",
    "salary": "Salaries",
    "payroll_tax": "Payroll taxes and contributions",
    "tax": "Taxes",
    "loan_repayment": "Loan repayments",
    "loan_disbursement": "Loan disbursements",
    "rent_utilities": "Rent and utilities",
    "own_transfer": "Own-account transfers",
    "cash_withdrawal": "Cash withdrawals",
    "bank_fee": "Bank fees",
    "other": "Other",
}
RULE_CONF = 0.98
MODEL_MIN_PROB = 0.6


@dataclass
class Rule:
    category: str
    direction: str
    patterns: list[re.Pattern]
    counterparty: list[re.Pattern]


@lru_cache(maxsize=2)
def load_rules(path: str = str(RULES_PATH)) -> list[Rule]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return [Rule(d["category"], d.get("direction", "any"), [re.compile(p, re.IGNORECASE) for p in d.get("patterns") or []],
                 [re.compile(p, re.IGNORECASE) for p in d.get("counterparty") or []])
            for d in data]


@lru_cache(maxsize=2)
def load_model(path: str = str(MODEL_PATH)):
    p = Path(path)
    if not p.exists():
        return None
    try:
        import joblib

        payload = joblib.load(p)
        return payload if isinstance(payload, dict) and "pipeline" in payload else {"pipeline": payload}
    except Exception:
        return None


def direction_of(amount: float) -> str:
    return "in" if amount >= 0 else "out"


def model_text(purpose: str, counterparty: str, amount: float) -> str:
    return f"__{direction_of(amount)}__ {strip_vat_mentions(uz_cyr_to_lat(norm(purpose)))} | {norm(counterparty)}"


def rule_category(purpose: str, counterparty: str, amount: float) -> str | None:
    base = norm(purpose)
    lat = uz_cyr_to_lat(base)
    text = strip_vat_mentions(base if lat == base else f"{base} || {lat}")
    cp = norm(counterparty)
    d = direction_of(amount)
    for rule in load_rules():
        if rule.direction != "any" and rule.direction != d:
            continue
        if any(rx.search(text) for rx in rule.patterns) or any(rx.search(cp) for rx in rule.counterparty):
            # tax authority receives payroll taxes too: purpose decides between them
            if rule.category == "tax" and any(rx.search(text) for r in load_rules() if r.category == "payroll_tax"
                                              for rx in r.patterns):
                return "payroll_tax"
            return rule.category
    # counterparty-only hints (purpose text truncated or empty)
    for rule in load_rules():
        if rule.category in ("sales_receipt", "supplier_payment", "other"):
            continue
        if rule.direction != "any" and rule.direction != d:
            continue
        if any(rx.search(cp) for rx in rule.patterns):
            return rule.category
    return None


class Categoriser:
    def __init__(self, use_model: bool = True):
        self.model = load_model() if use_model else None

    @property
    def has_model(self) -> bool:
        return self.model is not None

    def model_predict(self, purpose: str, counterparty: str, amount: float) -> tuple[str, float]:
        pipe = self.model["pipeline"]
        proba = pipe.predict_proba([model_text(purpose, counterparty, amount)])[0]
        classes = list(pipe.classes_)
        allowed = INFLOW_CATEGORIES if amount >= 0 else OUTFLOW_CATEGORIES
        ranked = sorted(zip(classes, proba), key=lambda t: -t[1])
        for cat, p in ranked:
            if cat in allowed:
                return str(cat), float(p)
        return "other", 0.0

    def categorise(self, purpose: str, counterparty: str, amount: float,
                   counterparty_stir: str | None = None, own_stir: str | None = None) -> tuple[str, str, float]:
        """Returns (category, source, confidence); source = rule | model."""
        if own_stir and counterparty_stir and counterparty_stir == own_stir:
            return "own_transfer", "rule", RULE_CONF
        cat = rule_category(purpose, counterparty, amount)
        if cat:
            return cat, "rule", RULE_CONF
        if self.model is not None:
            cat, p = self.model_predict(purpose, counterparty, amount)
            if p >= MODEL_MIN_PROB:
                return cat, "model", round(p, 3)
            return "other", "model", round(p, 3)
        return "other", "rule", 0.0
