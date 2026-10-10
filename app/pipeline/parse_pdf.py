"""PDF text layer → words; page renders for the evidence pane."""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from app.pipeline.types import Word

PAGE_DPI = 150
MIN_CHARS_TEXT_PAGE = 40


def is_encrypted(path: str) -> bool:
    import pypdfium2 as pdfium
    try:
        pdfium.PdfDocument(path).close()
        return False
    except pdfium.PdfiumError as exc:
        return "password" in str(exc).lower() or "security" in str(exc).lower()


def page_count(path: str) -> int:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def text_layer_words(path: str, max_pages: int | None = None) -> list[tuple[float, float, list[Word], int]]:
    """[(width, height, words, n_chars)] per page, in PDF points (top-left origin)."""
    out = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            if max_pages is not None and i >= max_pages:
                break
            try:
                raw = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=2)
            except Exception:
                raw = []
            words = [Word(text=w["text"], x0=float(w["x0"]), y0=float(w["top"]), x1=float(w["x1"]), y1=float(w["bottom"]), conf=1.0)
                     for w in raw if w.get("text", "").strip()]
            n_chars = sum(len(w.text) for w in words)
            cid = sum(w.text.count("(cid:") for w in words)
            if cid > 5:  # unmapped CID fonts: unusable text layer
                words, n_chars = [], 0
            out.append((float(page.width), float(page.height), words, n_chars))
    return out


def render_page_png(path: str, index: int, out_png: Path, dpi: int = PAGE_DPI) -> tuple[int, int]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[index]
        img = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
        page.close()
    finally:
        pdf.close()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png, "PNG", optimize=True)
    return img.size
