"""Train the bank-statement purpose-text categoriser on the generator's train split.

    uv run python -m eval.train_categoriser [--data data/synth] [--out app/pipeline/statements/model.joblib]

Reads every data/synth/train/*/truth.json (+ its statement xlsx), parses rows with the production normaliser,
joins the ground-truth category by Excel row number, fits TF-IDF (char 2–5-grams) + logistic regression and
evaluates on the dev split: rules only, model only, and rules → model (the production order).
Writes the model and model_metrics.json next to it. The test split is never read here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline.statements.categorise import (  # noqa: E402
    CATEGORIES, INFLOW_CATEGORIES, MODEL_MIN_PROB, MODEL_PATH, OUTFLOW_CATEGORIES, model_text, rule_category,
)
from app.pipeline.statements.io import load_xlsx_doc  # noqa: E402
from app.pipeline.statements.normalise import parse_transactions  # noqa: E402


class _RulesOnly:
    """Categoriser stand-in so parsing does not depend on an existing model."""

    def categorise(self, purpose, counterparty, amount, counterparty_stir=None, own_stir=None):
        if own_stir and counterparty_stir and own_stir == counterparty_stir:
            return "own_transfer", "rule", 0.98
        c = rule_category(purpose, counterparty, amount)
        return (c, "rule", 0.98) if c else ("other", "rule", 0.0)


def _statements(truth: dict) -> list[dict]:
    tr = truth.get("transactions")
    if isinstance(tr, dict):
        return [tr]
    if isinstance(tr, list):
        return [x for x in tr if isinstance(x, dict) and x.get("rows")]
    return []


def load_split(data: Path, split: str) -> list[dict]:
    """[{text, purpose, counterparty, amount, label, rule, bundle}] for every labelled statement row of a split."""
    out = []
    for tpath in sorted((data / split).glob("*/truth.json")):
        truth = json.loads(tpath.read_text(encoding="utf-8"))
        stir = (truth.get("company") or {}).get("stir")
        for st in _statements(truth):
            f = tpath.parent / st.get("file", "")
            if not f.exists():
                continue
            labels = {r["row"]: r["category"] for r in st["rows"] if r.get("category")}
            doc = load_xlsx_doc(f)
            txns, _ = parse_transactions(doc, stir, _RulesOnly())
            for t in txns:
                if t.row_n not in labels:
                    continue
                out.append({"text": model_text(t.purpose, t.counterparty, t.amount), "purpose": t.purpose,
                            "counterparty": t.counterparty, "amount": t.amount, "label": labels[t.row_n],
                            "rule": t.category if t.category_conf > 0 else None, "bundle": tpath.parent.name})
    return out


def _scores(y_true: list[str], y_pred: list[str]) -> dict:
    from sklearn.metrics import accuracy_score, f1_score

    return {"accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4), "n": len(y_true)}


def _predict(pipe, rows: list[dict]) -> list[str]:
    proba = pipe.predict_proba([r["text"] for r in rows])
    classes = list(pipe.classes_)
    out = []
    for r, p in zip(rows, proba):
        allowed = INFLOW_CATEGORIES if r["amount"] >= 0 else OUTFLOW_CATEGORIES
        ranked = sorted(zip(classes, p), key=lambda t: -t[1])
        cat, pr = next(((c, q) for c, q in ranked if c in allowed), ("other", 0.0))
        out.append(cat if pr >= MODEL_MIN_PROB else "other")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "data" / "synth"))
    ap.add_argument("--out", default=str(MODEL_PATH))
    ap.add_argument("--max-rows", type=int, default=200_000)
    args = ap.parse_args(argv)
    data = Path(args.data)
    train = load_split(data, "train")
    if not train:
        print(f"no labelled statements under {data}/train — the categoriser stays rules-only", file=sys.stderr)
        return 1
    dev = load_split(data, "dev")
    train = train[: args.max_rows]

    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True, max_features=200_000)),
        ("lr", LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000)),
    ])
    pipe.fit([r["text"] for r in train], [r["label"] for r in train])

    metrics: dict = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "train": {"rows": len(train), "bundles": len({r["bundle"] for r in train}),
                               "labels": dict(Counter(r["label"] for r in train))}}
    if dev:
        y = [r["label"] for r in dev]
        rules = [r["rule"] or "other" for r in dev]
        model = _predict(pipe, dev)
        combined = [r["rule"] or m for r, m in zip(dev, model)]
        metrics["dev"] = {"bundles": len({r["bundle"] for r in dev}), "rules_only": _scores(y, rules),
                          "model_only": _scores(y, model), "combined": _scores(y, combined),
                          "rule_coverage": round(sum(1 for r in dev if r["rule"]) / len(dev), 4)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipe, "classes": list(pipe.classes_), "categories": CATEGORIES, "metrics": metrics}, out,
                compress=3)
    (out.parent / "model_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
