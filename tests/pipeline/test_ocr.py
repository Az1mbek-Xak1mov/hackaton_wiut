"""OCR path: noisy 150-dpi scans, rotated pages, unreadable phone photos. Prints seconds per page."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pipeline.extract_forms import extract_forms  # noqa: E402
from app.pipeline.ocr import available_langs  # noqa: E402
from app.pipeline.parse import parse_document  # noqa: E402
from app.pipeline.readable import readable_summary  # noqa: E402

from test_extract_fixtures import balanced_form1, form2_values, make_form_pdf, rasterize  # noqa: E402

pytestmark = pytest.mark.skipif(not available_langs(), reason="tesseract not installed")
F2_CUR, F2_PREV = form2_values(2), form2_values(3, revenue=5_812_400)


def _accuracy(facts, cur, prev, cur_label):
    ok = sum(1 for f in facts
             if abs((cur if f.period_label == cur_label else prev).get(f.line_code, 1e18) - f.value) <= 1)
    return ok / (len(cur) + len(prev))


@pytest.mark.parametrize("dpi,skew,blur", [(150, 1.5, 0.6), (300, 0.7, 0.4)])
def test_noisy_scan_form2_russian(tmp_path, dpi, skew, blur):
    src = make_form_pdf(tmp_path / "f2.pdf", "form2", F2_CUR, F2_PREV, lang="ru", period_text="за 1 полугодие 2026 года")
    scan = rasterize(src, tmp_path / "scan.pdf", dpi=dpi, skew=skew, blur=blur)
    t = time.perf_counter()
    doc = parse_document(str(scan), "", tmp_path / "out")
    secs = time.perf_counter() - t
    print(f"\nOCR {dpi} dpi: {secs:.1f} s/page, conf {doc.pages[0].ocr_mean_conf:.0f}, skew {doc.pages[0].skew_deg}")
    assert doc.kind == "pdf_scan" and doc.pages[0].ocr_used and not doc.failure_cause
    assert doc.doc_type == "form2"
    facts, _ = extract_forms(doc)
    acc = _accuracy(facts, F2_CUR, F2_PREV, "H1-2026")
    assert acc >= 0.9, acc
    wrong = [f for f in facts if abs((F2_CUR if f.period_label == "H1-2026" else F2_PREV).get(f.line_code, 1e18) - f.value) > 1]
    assert all(f.confidence < 0.95 for f in wrong), [(f.line_code, f.confidence) for f in wrong]


def test_scan_uz_cyrillic_balance_sheet(tmp_path):
    cur, prev = balanced_form1(1), balanced_form1(7)
    src = make_form_pdf(tmp_path / "f1.pdf", "form1", cur, prev, lang="uz_cyrl",
                        period_text="2025 йил 31 декабрь ҳолатига", unit_text="минг сўм")
    doc = parse_document(str(rasterize(src, tmp_path / "s.pdf", dpi=150, skew=-2.2, blur=0.7)), "", tmp_path / "o")
    facts, _ = extract_forms(doc)
    assert _accuracy(facts, cur, prev, "2025-12-31") >= 0.9


def test_rotated_page_is_turned_upright(tmp_path):
    src = make_form_pdf(tmp_path / "f2.pdf", "form2", F2_CUR, {}, lang="ru", period_text="за 2025 год")
    doc = parse_document(str(rasterize(src, tmp_path / "r.pdf", dpi=200, skew=0, blur=0.3, rotate90=True)), "", tmp_path / "o")
    facts, _ = extract_forms(doc)
    rev = next(f for f in facts if f.line_code == "010")
    assert rev.value == pytest.approx(F2_CUR["010"])


def test_small_blurred_photo_fails_with_cause_but_reports_text(tmp_path):
    from PIL import Image
    src = make_form_pdf(tmp_path / "f2.pdf", "form2", F2_CUR, {}, lang="ru", period_text="за 2025 год")
    jpg = rasterize(src, tmp_path / "photo.jpg", dpi=60, skew=3, blur=1.2, jpeg_q=35, as_jpg=True)
    with Image.open(jpg) as im:
        im.resize((640, 480)).save(jpg, "JPEG", quality=35)
    doc = parse_document(str(jpg), "image/jpeg", tmp_path / "o", filename="schet-faktura_0917.jpg")
    assert doc.kind == "image" and "640×480" in doc.failure_cause
    assert extract_forms(doc)[0] == []
    r = readable_summary(doc)
    assert r["pages"] == 1 and isinstance(r["text_excerpt"], str)
