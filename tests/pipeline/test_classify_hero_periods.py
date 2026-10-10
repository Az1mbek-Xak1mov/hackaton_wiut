"""Periods and line values of the generator's hero bundles (data/seed/hero_*/truth.json).

Balance sheets must get the 'на … / … holatiga' date (not the signing / generation date); Form 2 must get
FY / H1 / quarter right — these feed the loan-review period columns and rule R12.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.pipeline.classify import period_labels  # noqa: E402
from app.pipeline.extract_forms import extract_forms  # noqa: E402
from app.pipeline.parse import parse_document  # noqa: E402


def _cases():
    out = []
    for truth in sorted(ROOT.glob("data/seed/hero_*/**/truth.json")):
        t = json.loads(truth.read_text())
        for d in t.get("documents", []):
            if d.get("doc_type") in ("form1", "form2") and d.get("period") and (truth.parent / d["file"]).exists():
                out.append(pytest.param(truth.parent / d["file"], d, id=f"{truth.parent.name}/{d['file']}"))
    return out


CASES = _cases()


@pytest.mark.skipif(not CASES, reason="hero bundles not generated (python -m eval.generator)")
@pytest.mark.parametrize("path,truth", CASES)
def test_hero_period_and_values(tmp_path, path, truth):
    doc = parse_document(str(path), "", tmp_path, filename=path.name)
    typ = truth["doc_type"]
    assert doc.doc_type == typ
    start = date.fromisoformat(truth["period"]["start"]) if truth["period"].get("start") else None
    end = date.fromisoformat(truth["period"]["end"])
    if typ == "form1":
        assert (doc.period_start, doc.period_end) == (None, end)
    else:
        assert (doc.period_start, doc.period_end) == (start, end)
    cur_label, prev_label = period_labels(typ, start if typ == "form2" else None, end)
    facts, _ = extract_forms(doc, typ)
    got = {(f.line_code, f.period_label): f.value for f in facts}
    expected = [((code, lab), rec[k]) for code, rec in (truth.get("fields") or {}).items()
                for k, lab in (("cur", cur_label), ("prev", prev_label)) if rec.get(k) is not None]
    hits = sum(1 for key, v in expected if key in got and abs(got[key] - v) <= 1)
    scanned = bool((truth.get("variant") or {}).get("scan"))
    assert hits / max(1, len(expected)) >= (0.85 if scanned else 1.0), (hits, len(expected))
