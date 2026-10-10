"""parse_document: route a file to the text-layer / OCR / XLSX parser, classify it, apply the quality gate.

    doc = parse_document("/data/files/<uuid>/original.pdf", "application/pdf", "/data/files/<uuid>")
    doc.pages[i].image_path   -> 150-dpi PNG for the evidence pane (bbox * image_scale = PNG px)
"""
from __future__ import annotations

import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from app.pipeline import classify as cls
from app.pipeline.parse_pdf import MIN_CHARS_TEXT_PAGE, PAGE_DPI, is_encrypted, render_page_png, text_layer_words
from app.pipeline.parse_xlsx import read_xlsx, sheet_text
from app.pipeline.rows import cluster_rows, row_text
from app.pipeline.types import ParsedDoc, ParsedPage

MAX_PAGES = 50
MIN_SHORT_SIDE_PX = 900
MIN_BLUR = 50.0
MIN_OCR_CONF = 60.0
CONF_IF_BLURRED = 75.0
_STATEMENT_HEADER = {
    "date": r"\b(?:дата|sana|сана|date)\b",
    "debit": r"\b(?:дебет|debet|debit|расход|chiqim|чиқим|списание)\b",
    "credit": r"\b(?:кредит|kredit|credit|приход|kirim|кирим|поступление)\b",
    "purpose": r"(?:назначение|maqsad|мақсад|purpose|описание|izoh)",
    "counterparty": r"(?:контрагент|kontragent|корреспондент|получател|отправител|наименование|nomi|counterparty|payer|payee)",
}


def sniff_kind(path: str, mime: str = "") -> str:
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
            if any(n.startswith("word/") for n in names):
                return "docx"
        except zipfile.BadZipFile:
            pass
        return "unsupported"
    if head[:3] == b"\xff\xd8\xff" or head.startswith(b"\x89PNG") or head[:4] in (b"II*\x00", b"MM\x00*") \
            or head[:4] == b"RIFF":
        return "image"
    return "unsupported"


def _deadline_ts(deadline) -> float | None:
    if deadline is None:
        return None
    if isinstance(deadline, datetime):
        return deadline.timestamp()
    return float(deadline)


def xlsx_header_score(sheets) -> float:
    best = 0
    for s in sheets:
        for row in s.rows[:30]:
            text = cls.light_norm(" ".join(str(v) for v in row if isinstance(v, str)))
            hits = sum(1 for pat in _STATEMENT_HEADER.values() if re.search(pat, text))
            best = max(best, hits)
    return 3.0 if best >= 3 else (1.0 if best == 2 else 0.0)


def _codes_in(pages: list[ParsedPage]) -> set[str]:
    out = set()
    for p in pages:
        for w in p.words:
            t = w.text.strip()
            if re.fullmatch(r"\d{3}", t):
                out.add(t)
    return out


def _page_text(pages: list[ParsedPage], max_pages: int = 3) -> str:
    parts = []
    for p in pages[:max_pages]:
        for r in cluster_rows(p.words, p.n, ocr=p.ocr_used):
            parts.append(row_text(r))
    return "\n".join(parts)


def _ocr_page(img: Image.Image, n: int, out_dir: Path, *, source_dpi: float | None, lang: str | None = None,
              lang_out: list | None = None) -> ParsedPage:
    from app.pipeline.ocr import ocr_image
    # page 1 decides the languages (with a retry on poor confidence); later pages reuse them
    res = ocr_image(img, lang=lang, retry_below=85.0 if lang is None else 0.0)
    if lang_out is not None:
        lang_out.append(res.lang)
    # page PNG: processed (upright, deskewed) image at ~150 dpi equivalent
    proc = res.image
    target_w = proc.width * (PAGE_DPI / 300.0) if source_dpi else min(1700, proc.width)
    scale = min(1.0, target_w / proc.width)
    png = proc.resize((max(1, int(proc.width * scale)), max(1, int(proc.height * scale))), Image.LANCZOS) if scale < 1 else proc
    path = out_dir / "pages" / f"{n}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    png.save(path, "PNG", optimize=True)
    return ParsedPage(n=n, width=float(res.width), height=float(res.height), words=res.words, image_path=str(path),
                      image_scale=png.width / res.width, ocr_used=True, ocr_mean_conf=res.mean_conf,
                      skew_deg=res.skew_deg, blur_score=res.blur)


_FILENAME_HINTS = [
    (r"faktura|invoice|сч[её]т", "invoice"), (r"vypiska|vipiska|ko.?chirma|выписк|statement", "bank_statement"),
    (r"balans|balance|форма.?1|forma.?1", "form1"), (r"forma.?2|форма.?2|moliyaviy|pnl|income", "form2"),
    (r"ariza|zayav|заявк|application", "loan_application"), (r"deklar|декларац", "tax_declaration"),
]


def _filename_hint(doc: ParsedDoc, filename: str) -> None:
    """When the content is unreadable, the file name may still say what the document probably is."""
    if doc.doc_type != "unknown" or not filename:
        return
    name = filename.lower()
    for pat, typ in _FILENAME_HINTS:
        if re.search(pat, name):
            doc.doc_type, doc.type_confidence = typ, 0.3
            doc.type_reason = (f"Probably a {cls.TYPE_LABELS[typ]} (from the file name only; the content could not "
                               f"be read well enough to confirm). " + doc.type_reason)
            return


def parse_document(path: str, mime: str = "", out_dir: str | Path = ".", *, max_ocr_pages: int = 10,
                   deadline=None, filename: str = "") -> ParsedDoc:
    from app.pipeline.ocr import OcrUnavailable
    try:
        doc = _parse_document(path, mime, out_dir, max_ocr_pages=max_ocr_pages, deadline=deadline)
    except OcrUnavailable:
        doc = ParsedDoc(kind="pdf_scan" if sniff_kind(path, mime) == "pdf" else "image",
                        failure_cause="This document needs text recognition (OCR), which is not available on this "
                                      "server. Upload a PDF with a text layer or an XLSX file.",
                        type_reason="Scanned document; OCR unavailable.")
    if doc.failure_cause:
        _filename_hint(doc, filename or Path(path).name)
    return doc


def _parse_document(path: str, mime: str = "", out_dir: str | Path = ".", *, max_ocr_pages: int = 10,
                    deadline=None) -> ParsedDoc:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dl = _deadline_ts(deadline)
    kind = sniff_kind(path, mime)
    doc = ParsedDoc(kind=kind)

    if kind == "docx":
        doc.kind = "unsupported"
        doc.failure_cause = "Word documents are not supported. Export the file as PDF and upload it again."
        doc.type_reason = "Unsupported format (Word document)."
        return doc
    if kind == "unsupported":
        doc.failure_cause = "Unsupported file format. Upload a PDF, XLSX, JPG or PNG file."
        doc.type_reason = "Unsupported format."
        return doc

    if kind == "xlsx":
        try:
            doc.sheets = read_xlsx(path)
        except Exception as exc:  # corrupt workbook
            doc.failure_cause = f"The spreadsheet could not be opened ({exc.__class__.__name__})."
            return doc
        text = sheet_text(doc.sheets)
        doc.doc_type, doc.type_confidence, doc.type_reason = cls.classify_text(
            text, xlsx_header_score=xlsx_header_score(doc.sheets), kind="xlsx")
        doc.text_layer = True
        doc.language = cls.detect_language(text)
        doc.period_start, doc.period_end = cls.detect_period(text, doc.doc_type)
        doc.stir = cls.detect_stir(text)
        return doc

    if kind == "image":
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as exc:
            doc.failure_cause = f"The image could not be opened ({exc.__class__.__name__})."
            return doc
        page = _ocr_page(img, 1, out, source_dpi=None)
        doc.pages = [page]
        doc.kind = "image"
        problems = []
        w, h = img.size
        if min(w, h) < MIN_SHORT_SIDE_PX:
            problems.append(f"the image is {w}×{h} px (minimum {MIN_SHORT_SIDE_PX} px on the short side)")
        if _page_unreadable(page):
            if page.blur_score is not None and page.blur_score < MIN_BLUR:
                problems.append(f"it is blurred (sharpness {page.blur_score:.0f}, minimum {MIN_BLUR:.0f})")
            c = page.ocr_mean_conf or 0
            problems.append(f"text recognition confidence is {c:.0f}% (minimum {MIN_OCR_CONF:.0f}%)")
        if problems:
            doc.failure_cause = ("Could not analyse reliably: " + "; ".join(problems)
                                 + ". Amounts may be unreadable. Re-upload a sharper scan (≥ 200 dpi) or enter the values manually.")
        _finish_classification(doc)
        return doc

    # PDF
    if is_encrypted(path):
        doc.kind = "pdf_text"
        doc.failure_cause = "The PDF is encrypted (password-protected), so it cannot be read. Upload an unprotected copy."
        doc.type_reason = "Encrypted PDF."
        return doc
    try:
        layers = text_layer_words(path, max_pages=MAX_PAGES)
    except Exception as exc:
        doc.failure_cause = f"The PDF could not be opened ({exc.__class__.__name__})."
        return doc
    from concurrent.futures import ThreadPoolExecutor

    from app.pipeline.ocr import render_pdf_page
    ocr_done = 0
    pages: dict[int, ParsedPage] = {}
    to_ocr: list[int] = []
    for i, (pw, ph, words, n_chars) in enumerate(layers):
        n = i + 1
        if n_chars >= MIN_CHARS_TEXT_PAGE:
            png = out / "pages" / f"{n}.png"
            render_page_png(path, i, png)
            pages[n] = ParsedPage(n=n, width=pw, height=ph, words=words, image_path=str(png),
                                  image_scale=PAGE_DPI / 72.0, ocr_used=False)
        elif ocr_done < max_ocr_pages:
            to_ocr.append(i)
            ocr_done += 1
        else:
            png = out / "pages" / f"{n}.png"
            render_page_png(path, i, png)
            pages[n] = ParsedPage(n=n, width=pw, height=ph, words=[], image_path=str(png), image_scale=PAGE_DPI / 72.0)
            doc.partial = True
    if to_ocr:
        langs: list[str] = []
        first = to_ocr[0]
        pages[first + 1] = _ocr_page(render_pdf_page(path, first, 300), first + 1, out, source_dpi=300, lang_out=langs)

        def work(i: int) -> ParsedPage | None:
            if dl is not None and time.time() > dl:
                return None
            return _ocr_page(render_pdf_page(path, i, 300), i + 1, out, source_dpi=300, lang=langs[0] or None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            for i, res in zip(to_ocr[1:], pool.map(work, to_ocr[1:])):
                if res is None:  # deadline: keep the page image, no words
                    png = out / "pages" / f"{i + 1}.png"
                    render_page_png(path, i, png)
                    pw, ph = layers[i][0], layers[i][1]
                    pages[i + 1] = ParsedPage(n=i + 1, width=pw, height=ph, words=[], image_path=str(png),
                                              image_scale=PAGE_DPI / 72.0)
                    doc.partial = True
                else:
                    pages[i + 1] = res
    pages = [pages[k] for k in sorted(pages)]
    doc.pages = pages
    ocr_pages = [p for p in pages if p.ocr_used]
    doc.text_layer = not ocr_pages
    doc.kind = "pdf_scan" if ocr_pages and len(ocr_pages) >= len(pages) / 2 else "pdf_text"
    if ocr_pages:
        bad = [p for p in ocr_pages if _page_unreadable(p)]
        if len(bad) == len(ocr_pages):
            p = bad[0]
            doc.failure_cause = (f"Could not analyse reliably: the scan is unclear (sharpness {p.blur_score or 0:.0f}, minimum "
                                 f"{MIN_BLUR:.0f}; recognition confidence {p.ocr_mean_conf or 0:.0f}%, minimum {MIN_OCR_CONF:.0f}%). "
                                 "Re-upload a sharper scan (≥ 200 dpi) or enter the values manually.")
    if not any(p.words for p in pages) and not doc.failure_cause:
        doc.failure_cause = "No text could be read from this document."
    _finish_classification(doc)
    return doc


def _page_unreadable(p: ParsedPage) -> bool:
    """Recognition confidence decides; blur only matters when confidence is also mediocre."""
    conf = p.ocr_mean_conf or 0.0
    if conf < MIN_OCR_CONF:
        return True
    return (p.blur_score or 0.0) < MIN_BLUR and conf < CONF_IF_BLURRED


def _finish_classification(doc: ParsedDoc) -> None:
    text = _page_text(doc.pages)
    doc.doc_type, doc.type_confidence, doc.type_reason = cls.classify_text(
        text, codes_found=_codes_in(doc.pages[:3]), kind=doc.kind)
    doc.language = cls.detect_language(text)
    doc.period_start, doc.period_end = cls.detect_period(text, doc.doc_type)
    doc.stir = cls.detect_stir(text)
