"""Fake pipeline stages with the real contract (app/pipeline/types.py), so the runner is tested on its own."""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image

from app.pipeline.types import FactDraft, FindingDraft, ParsedDoc, ParsedPage, TxnDraft, Word

FORM2_FY = {"010": 9842316, "020": 8614900, "040": 548600, "270": 612100}
FORM2_H1 = {"010": 5316400, "020": 4672100, "040": 296300, "270": 318000}


def fake_parse_document(path, mime, out_dir, *, max_ocr_pages=10, deadline=None):
    name = Path(path).read_bytes()[-40:].decode("latin-1")
    pages_dir = Path(out_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    img = pages_dir / "1.png"
    Image.new("RGB", (120, 170), "white").save(img)
    page = ParsedPage(n=1, width=595, height=842, words=[Word("010", 40, 100, 60, 110), Word("9 842 316", 400, 100, 460, 110)],
                      image_path=str(img), image_scale=150 / 72)
    if "H1" in name:
        return ParsedDoc(kind="pdf_text", doc_type="form2", type_confidence=0.95, type_reason="line codes 010 and 270",
                         language="ru", pages=[page], text_layer=True,
                         period_start=date(2026, 1, 1), period_end=date(2026, 6, 30), stir="302447118")
    if "STATEMENT" in name:
        return ParsedDoc(kind="xlsx", doc_type="bank_statement", type_confidence=0.9, type_reason="debit/credit header",
                         language="ru", pages=[], text_layer=True,
                         period_start=date(2026, 1, 1), period_end=date(2026, 8, 31), stir="302447118")
    if "UNKNOWN" in name:
        return ParsedDoc(kind="pdf_text", doc_type="unknown", type_confidence=0.2,
                         type_reason="no statutory line codes found", language="en", pages=[page], text_layer=True)
    return ParsedDoc(kind="pdf_text", doc_type="form2", type_confidence=0.95, type_reason="line codes 010 and 270",
                     language="ru", pages=[page], text_layer=True,
                     period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), stir="302447118")


def fake_extract_forms(doc):
    values = FORM2_H1 if doc.period_end and doc.period_end.month == 6 else FORM2_FY
    labels = {"010": "Net revenue", "020": "Cost of sales", "040": "Operating expenses", "270": "Net profit"}
    facts = [FactDraft(field=f"form2.{c}.x", label=labels[c], value=v, line_code=c, period_label="cur",
                       printed=f"{v:,}".replace(",", " "), page_n=1, bbox=[400, 100, 460, 110], passage=f"{c} … {v}",
                       confidence=0.98 if c != "040" else 0.75)
             for c, v in values.items()]
    return facts, [{"page_n": 1, "text": "Unofficial line", "value_printed": "12", "bbox": None}]


def fake_readable(doc):
    return {"pages": len(doc.pages), "language": doc.language, "numbers": [], "dates": [], "stirs": [],
            "text_excerpt": "…"}


def fake_normalise(doc, own_stir):
    txns = [TxnDraft(row_n=7 + i, booked_on=date(2026, m, 20), amount=-18_500_000.0, counterparty="Ipoteka Bank",
                     purpose="Погашение кредита по договору 2024-1177", category="loan_repayment",
                     recurring_group="loan:2024-1177") for i, m in enumerate(range(1, 9))]
    txns.append(TxnDraft(row_n=40, booked_on=date(2026, 3, 2), amount=912_600_000.0, counterparty="Client",
                         category="sales_receipt"))
    agg = FactDraft(field="statement.inflow.avg_monthly", label="Avg monthly inflows (bank)", value=912600,
                    kind="aggregate", period_label="2026-01..2026-08", confidence=1.0, method="aggregate")
    loan = FactDraft(field="statement.loan_repayment.monthly", label="Detected loan repayment, monthly", value=18500,
                     kind="aggregate", confidence=1.0, method="aggregate", key="f_loan01")
    return txns, [agg, loan], [{"group": "loan:2024-1177", "label": "Loan 2024-1177", "count": 8,
                                "evidence": ["f_loan01"]}]


@dataclass
class FakeAppContext:
    facts: list
    transactions: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    application: dict = field(default_factory=dict)
    recurring: list = field(default_factory=list)
    fact_document: dict = field(default_factory=dict)
    derived_facts: list = field(default_factory=list)


def fake_rules(ctx):
    rev = next((f for f in ctx.facts if f.line_code == "010"), None)
    loan = next((f for f in ctx.facts if f.field == "statement.loan_repayment.monthly"), None)
    out = []
    if loan is not None:
        out.append(FindingDraft(rule_id="R06", severity="attn", label="Undeclared obligation",
                                title="Bank statement shows loan repayments not listed in the application",
                                detail="8 payments", evidence=[loan.key]))
    if rev is not None:
        out.append(FindingDraft(rule_id="R03", severity="info", label="Arithmetic", title="P&L chain checked",
                                detail="", evidence=[rev.key]))
    out.append(FindingDraft(rule_id="R10", severity="neutral", label="Missing document",
                            title="Tax declaration not provided", detail=""))
    return out


def fake_ratios(ctx):
    d1 = FactDraft(field="ratio.dscr_new", label="Est. DSCR (new loan)", value=1.47, unit="ratio", kind="computed",
                   formula="(270+120)/6/installment", method="compute")
    d2 = FactDraft(field="ratio.dscr_incl_undeclared", label="Est. DSCR (incl. undeclared)", value=1.04, unit="ratio",
                   kind="computed", formula="… / (installment + undeclared)", method="compute",
                   note="New loan only → incl. undeclared repayments")
    nm = FactDraft(field="ratio.net_margin", label="Net margin", value=6.0, unit="pct", kind="computed",
                   formula="270 / 010", method="compute")
    return [d1, d2, nm]


def fake_template(ctx, findings, ratio_facts):
    rev = next(f for f in ctx.facts if f.line_code == "010")
    return f"Net revenue was 9 842.3 mln UZS [{rev.key}]."


def fake_verify(text, facts):
    return {"ok": True, "numbers": [], "unmatched": [], "uncited_sentences": [], "unknown_ids": []}


FAKES = {
    ("app.pipeline.parse", "parse_document"): fake_parse_document,
    ("app.pipeline.extract_forms", "extract_forms"): fake_extract_forms,
    ("app.pipeline.readable", "readable_summary"): fake_readable,
    ("app.pipeline.statements", "normalise_statement"): fake_normalise,
    ("app.pipeline.rules", "run_application_rules"): fake_rules,
    ("app.pipeline.rules", "AppContext"): FakeAppContext,
    ("app.pipeline.ratios", "compute_ratios"): fake_ratios,
}


def install(monkeypatch):
    import app.modules.jobs.runner as runner

    def fake_pipeline_fn(module, name):
        if (module, name) in FAKES:
            return FAKES[(module, name)]
        raise runner.PipelineMissing(f"{module}.{name} (fake)")
    monkeypatch.setattr(runner, "pipeline_fn", fake_pipeline_fn)
    monkeypatch.setattr(runner, "optional_fn",
                        lambda m, n: FAKES.get((m, n)))
    import sys
    import types
    narrative = types.ModuleType("app.pipeline.narrative")
    narrative.template_narrative = fake_template
    verify = types.ModuleType("app.pipeline.verify")
    verify.verify = fake_verify
    monkeypatch.setitem(sys.modules, "app.pipeline.narrative", narrative)
    monkeypatch.setitem(sys.modules, "app.pipeline.verify", verify)


def run_all_jobs(session_factory, limit: int = 50) -> int:
    from app.modules.jobs.runner import run_job
    from app.modules.jobs.service import claim_next
    n = 0
    for _ in range(limit):
        s = session_factory()
        try:
            job_id = claim_next(s)
        finally:
            s.close()
        if job_id is None:
            # deferred jobs wait 3 s in production; make them due now for the test
            s = session_factory()
            from app.modules.jobs.models import Job
            pending = s.query(Job).filter(Job.status == "queued").all()
            for j in pending:
                j.run_after = None
            s.commit()
            s.close()
            if not pending:
                break
            continue
        run_job(job_id)
        n += 1
    return n
