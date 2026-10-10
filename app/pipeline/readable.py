"""'What I could read' summary for any document (docs/plan/09-API.md `readable` shape).

Always true, never interpreted: numbers with the label printed on their row and their page/bbox,
dates, STIRs, a text excerpt, the language and the OCR confidence.
"""
from __future__ import annotations

from app.pipeline.classify import find_dates, find_stirs
from app.pipeline.numbers import parse_number
from app.pipeline.rows import cluster_rows, is_number_word, row_text
from app.pipeline.types import ParsedDoc

MAX_NUMBERS = 30
MAX_EXCERPT = 1500


def readable_summary(doc: ParsedDoc) -> dict:
    lines: list[str] = []
    numbers: list[dict] = []
    for p in doc.pages:
        for r in cluster_rows(p.words, p.n, ocr=p.ocr_used):
            lines.append(row_text(r))
            nums = [w for w in r.words if is_number_word(w, ocr=p.ocr_used)]
            label = " ".join(w.text for w in r.words if w not in nums).strip()
            for w in nums:
                v = parse_number(w.text, ocr=p.ocr_used)
                # skip line codes, page numbers and other tiny integers without a label
                if v is None or (abs(v) < 1000 and not label) or len(w.text.replace(" ", "")) < 3:
                    continue
                if len(numbers) < MAX_NUMBERS:
                    numbers.append({"text": w.text, "value": v, "label": label[:160], "page_n": p.n,
                                    "bbox": [round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)]})
    for s in doc.sheets:
        for i, row in enumerate(s.rows[:200]):
            vals = [v for v in row if v is not None]
            if not vals:
                continue
            lines.append(" | ".join(str(v) for v in vals))
            label = " ".join(str(v) for v in vals if isinstance(v, str))[:160]
            for v in vals:
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000 and len(numbers) < MAX_NUMBERS:
                    numbers.append({"text": f"{v:,}".replace(",", " "), "value": float(v), "label": label,
                                    "page_n": None, "sheet": s.name, "row": i + 1, "bbox": None})
    text = "\n".join(lines)
    confs = [p.ocr_mean_conf for p in doc.pages if p.ocr_used and p.ocr_mean_conf is not None]
    return {
        "pages": len(doc.pages) or len(doc.sheets),
        "language": doc.language,
        "ocr_mean_conf": round(sum(confs) / len(confs), 1) if confs else None,
        "numbers": numbers,
        "dates": list(dict.fromkeys(d.isoformat() for _, d in find_dates(text)))[:20],
        "stirs": find_stirs(text)[:10],
        "text_excerpt": text[:MAX_EXCERPT],
    }
