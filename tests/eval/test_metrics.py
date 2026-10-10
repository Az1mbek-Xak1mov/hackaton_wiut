import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.pipeline.types import FactDraft, TxnDraft  # noqa: E402
from eval import metrics as M  # noqa: E402
from eval.report import render_eval, render_failures  # noqa: E402
from eval.run import hard_check  # noqa: E402


def F(field, value, period, conf=0.99):
    return FactDraft(field=field, label=field, value=value, period_label=period, confidence=conf)


DOC = {"doc_type": "form2", "fields": {"010": {"cur": 1000, "prev": 900}, "020": {"cur": 600, "prev": 500},
                                       "120": {"cur": None, "prev": None}}}


def test_prf_and_percentile():
    assert M.prf(8, 2, 2) == {"tp": 8, "fp": 2, "fn": 2, "precision": 0.8, "recall": 0.8, "f1": 0.8}
    assert M.prf(0, 0, 0)["precision"] is None
    assert M.percentile([5, 1, 3, 2, 4], 50) == 3
    assert M.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert M.percentile([], 50) is None


def test_score_form_counts_and_error_kinds():
    facts = [F("form2.010.net_revenue", 1000, "FY2025"),       # TP
             F("form2.010.net_revenue", 1000, "FY2024"),       # prev wrong: holds the cur value -> swapped
             F("form2.020.cost_of_sales", 601.5, "FY2025", conf=0.5),   # wrong, flagged (not silent)
             F("form2.120.dividend_income", 0, "FY2025"),      # zero for a blank cell: ignored
             F("form2.130.interest_income", 7, "FY2025")]      # value for an absent cell
    sc = M.score_form(DOC, facts, "FY2025", "FY2024")
    assert (sc["tp"], sc["fp"], sc["fn"]) == (1, 3, 3)
    assert sc["wrong"] == 2 and sc["spurious"] == 1 and sc["missing"] == 1 and sc["silent_errors"] == 1
    kinds = sorted(e["kind"] for e in sc["errors"])
    assert "current and prior-year columns swapped" in kinds and "line not extracted" in kinds
    assert "value for a blank or absent cell" in kinds
    # literal cur/prev labels (period not detected) map to the same columns
    assert M.score_form(DOC, [F("form2.010.x", 1000, "cur")], "FY2025", "FY2024")["tp"] == 1


def test_value_error_classes():
    assert M.classify_value_error(-500, 500, None) == "sign lost or inverted"
    assert M.classify_value_error(870, 4991870, None) == "digits dropped or merged"
    assert M.classify_value_error(1633, 1633960, None) == "unit scale error (x1000)"
    assert M.classify_value_error(19563, 10563, None) == "OCR digit misread"
    assert M.classify_value_error(1_000_000, 1000, None) == "unit scale error (x1000)"


def test_score_application():
    doc = {"fields": {"requested_amount": {"value": 850000}, "term_months": {"value": 24},
                      "rate_pct": {"value": 22.0}, "declared_debts_total": {"value": 0}}}
    facts = [FactDraft(field="application.requested_amount", label="", value=850000),
             FactDraft(field="application.term_months", label="", value=36)]
    sc = M.score_application(doc, facts)
    assert (sc["tp"], sc["fp"], sc["fn"], sc["cells"]) == (1, 1, 3, 4)


def test_recurring_matching_by_rows_not_names():
    from datetime import date
    truth = [{"row": r, "recurring_group": "loan:1"} for r in (1, 2, 3)] + \
            [{"row": r, "recurring_group": "salary"} for r in (4, 5, 6)]
    txns = [TxnDraft(row_n=r, booked_on=date(2026, 1, 1), amount=-1, recurring_group="loan:X") for r in (1, 2, 3)] + \
           [TxnDraft(row_n=r, booked_on=date(2026, 1, 1), amount=-1, recurring_group="tax:vat") for r in (7, 8, 9)]
    sc = M.score_recurring(truth, txns)
    assert (sc["tp"], sc["fp"], sc["fn"]) == (1, 1, 1) and sc["missed"] == ["salary"]


def test_score_rules_and_classification():
    rows = M.score_rules([({"R06", "R02"}, {"R06"}), (set(), {"R07"})], ["R02", "R06", "R07"])
    by = {r["rule"]: r for r in rows}
    assert by["R06"]["tp"] == 1 and by["R02"]["fp"] == 1 and by["R07"]["fn"] == 1
    assert by["micro (all rules)"]["precision"] == 0.5 and by["micro (all rules)"]["recall"] == 0.5
    sc = M.classification_scores(["a", "a", "b"], ["a", "b", "b"])
    assert sc["accuracy"] == round(2 / 3, 4) and sc["rows"] == 3


def test_variant_and_hard_checks():
    assert M.variant_of({"variant": {"scan": True, "dpi": 150}}) == "scan 150 dpi"
    assert M.variant_of({"variant": {"photo": True}}) == "phone photo"
    assert M.variant_of({}) == "text layer"
    ok, obs = hard_check({"id": "H16"}, {"docs": [{"failure_cause": "The PDF is encrypted"}]})
    assert ok and "encrypted" in obs
    ok, _ = hard_check({"id": "H13"}, {"docs": [{}], "fired": ["R10"]})
    assert not ok
    ok, _ = hard_check({"id": "H11"}, {"docs": [{"currency_check": {"uzs_rows": 3, "uzs_kept": 3, "foreign_rows": 2,
                                                                     "foreign_kept": 0}}]})
    assert ok


def test_report_renders_every_number_from_the_results():
    data = {"generated_at": "2026-10-10T18:00:00+05:00", "git_sha": "abc1234", "dataset": "synthetic test split",
            "caveat": "Measured on our synthetic generator's test split", "headline": {"Form 2 field F1": 0.9495},
            "field_extraction": [{"doc_type": "form2", "variant": "all", "documents": 80, "cells": 2616, "tp": 2443,
                                  "fp": 87, "fn": 173, "precision": 0.9656, "recall": 0.9339, "f1": 0.9495,
                                  "silent_errors": 68}],
            "known_failures": [{"area": "extraction", "failure": "form2: current and prior-year columns swapped",
                                "count": 33, "example": "data/synth/test/b0176/form2_FY2025.jpg", "detail": "x"}],
            "not_measured": ["LLM token cost"]}
    md = render_eval(data, "eval/results/x.json", ["note one"])
    assert "0.9495" in md and "2 443" in md and "note one" in md and "Measured on our synthetic" in md
    fm = render_failures(data, "eval/results/x.json")
    assert "33 ×" in fm and "b0176/form2_FY2025.jpg" in fm and "What it means" in fm
