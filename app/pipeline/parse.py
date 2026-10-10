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
from app.pipeline.numbers import parse_number
from app.pipeline.parse_xlsx import read_csv, read_html_table, read_xls, read_xlsx, sheet_text
from app.pipeline.rows import cluster_rows, row_text
from app.pipeline.types import ParsedDoc, ParsedPage

MAX_PAGES = 50
MIN_SHORT_SIDE_PX = 900
MIN_BLUR = 25.0
MIN_OCR_CONF = 60.0
CONF_IF_BLURRED = 65.0
_STATEMENT_HEADER = {
    "date": r"\b(?:дата|sana|сана|date)\b",
    "debit": r"\b(?:дебет|debet|debit|расход|chiqim|чиқим|списание)\b",
    "credit": r"\b(?:кредит|kredit|credit|приход|kirim|кирим|поступление)\b",
    "purpose": r"(?:назначение|maqsad|мақсад|purpose|описание|izoh)",
    "counterparty": r"(?:контрагент|kontragent|корреспондент|получател|отправител|наименование|nomi|counterparty|payer|payee)",
}


HEIC_UNSUPPORTED = ("iPhone HEIC photos are not supported yet. Please send the photo as JPG (on iPhone: Settings → "
                    "Camera → Formats → Most Compatible) or as a PDF.")
UNSUPPORTED_FORMAT = "Unsupported file format. Upload a PDF, XLSX, XLS, CSV, JPG or PNG file."


def _looks_like_csv(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    text = head.decode("utf-8", errors="ignore") or head.decode("cp1251", errors="ignore")
    lines = [ln for ln in text.splitlines()[:10] if ln.strip()]
    if len(lines) < 2:
        return False
    for d in (";", "\t", ",", "|"):   # title lines may have no delimiter; the table rows do
        with_d = [ln for ln in lines if ln.count(d) >= 1]
        if len(with_d) >= 2 and len(with_d) * 2 >= len(lines):
            return True
    return False


def sniff_kind(path: str, mime: str = "") -> str:
    with open(path, "rb") as f:
        head8k = f.read(8192)
    head = head8k[:8]
    ext = Path(path).suffix.lower().lstrip(".")
    if head8k[4:8] == b"ftyp" and head8k[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim",
                                                    b"heis", b"avic"):
        return "heic"
    if head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":   # OLE2: legacy .xls (or .doc)
        with open(path, "rb") as f:
            blob = f.read()
        if "Workbook".encode("utf-16-le") in blob or "Book".encode("utf-16-le") in blob:
            return "xls"
        return "doc"
    lowered = head8k[:2048].lstrip().lower()
    if lowered.startswith((b"<html", b"<!doctype html", b"<table", b"<?xml")) or b"<table" in lowered:
        if b"<table" in head8k.lower() or ext in ("xls", "htm", "html"):
            return "html_table"
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
    if (ext == "csv" or mime == "text/csv") and _looks_like_csv(head8k):
        return "csv"
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


def _title_rows(sheets) -> int:
    """Rows above (and including) the transaction-table header, max 10 — the part of a sheet that says
    what the document is. Transaction purpose texts ('счет-фактура № …') must not vote."""
    for s_ in sheets[:1]:
        for i, row in enumerate(s_.rows[:30]):
            text = cls.light_norm(" ".join(str(v) for v in row if isinstance(v, str)))
            if sum(1 for pat in _STATEMENT_HEADER.values() if re.search(pat, text)) >= 2:
                return min(10, i + 2)
    return 10


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
            label = cls.TYPE_LABELS[typ]
            article = "an" if label[:1].lower() in "aeiou" else "a"
            doc.type_reason = (f"Probably {article} {label} (from the file name only; the content could not "
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

    if kind in ("docx", "doc"):
        doc.kind = "unsupported"
        doc.failure_cause = "Word documents are not supported. Export the file as PDF and upload it again."
        doc.type_reason = "Unsupported format (Word document)."
        return doc
    if kind == "heic":
        doc.kind = "unsupported"
        doc.failure_cause = HEIC_UNSUPPORTED
        doc.type_reason = "Unsupported format (HEIC photo)."
        return doc
    if kind == "unsupported":
        doc.failure_cause = UNSUPPORTED_FORMAT
        doc.type_reason = "Unsupported format."
        return doc

    if kind in ("xlsx", "xls", "csv", "html_table"):
        reader = {"xlsx": read_xlsx, "xls": read_xls, "csv": read_csv, "html_table": read_html_table}[kind]
        doc.kind = "xlsx"   # every spreadsheet-like format continues on the XLSX path
        try:
            doc.sheets = reader(path)
        except Exception as exc:  # corrupt workbook
            doc.failure_cause = f"The spreadsheet could not be opened ({exc.__class__.__name__})."
            return doc
        if not any(r for s_ in doc.sheets for r in s_.rows):
            doc.failure_cause = "The spreadsheet is empty."
            return doc
        text = sheet_text(doc.sheets, max_rows=_title_rows(doc.sheets))  # title + header only: purpose texts mention invoices
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


def _is_txn_row(text: str) -> bool:
    """A statement transaction row: a date and an amount (≥ 1000, not a year, not an account number)."""
    if not cls.find_dates(text):
        return False
    for tok in re.findall(r"\d[\d  .,]*\d", text):
        t = tok.strip()
        digits = sum(c.isdigit() for c in t)
        if digits >= 13 or re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", t) or re.fullmatch(r"(19|20)\d{2}", t):
            continue
        v = parse_number(t)
        if v is not None and abs(v) >= 1000:
            return True
    return False


def _is_statement_header(text: str) -> bool:
    t = cls.light_norm(text)
    hit = {k for k, pat in _STATEMENT_HEADER.items() if re.search(pat, t)}
    return "date" in hit and (("debit" in hit and "credit" in hit) or len(hit) >= 4)


def statement_layout(pages: list[ParsedPage], max_pages: int = 3) -> tuple[str, float, str]:
    """(classification text, statement score, hint) from page rows.

    A statement is recognised by its structure: a transaction-table header (date, debit, credit …) and rows that
    carry a date and an amount. Only the text around that table (title, account, opening/closing balance) votes
    for the document type, so 'hisob-faktura' inside a payment purpose does not make the statement an invoice."""
    kept: list[str] = []
    header = False
    txn_rows = 0
    for p in pages[:max_pages]:
        rows = [row_text(r) for r in cluster_rows(p.words, p.n, ocr=p.ocr_used)]
        flags = [_is_txn_row(t) for t in rows]
        heads = [i for i, t in enumerate(rows) if _is_statement_header(t)]
        txn_idx = [i for i, f in enumerate(flags) if f]
        txn_rows += len(txn_idx)
        header = header or bool(heads)
        if heads or len(txn_idx) >= 3:
            start = heads[0] if heads else txn_idx[0]
            end = txn_idx[-1] if txn_idx and txn_idx[-1] > start else start
            kept += rows[:start + 1] + rows[end + 1:]   # title + header, then the footer (closing balance)
        else:
            kept += rows
    text = "\n".join(kept)
    score, hint = 0.0, []
    if header and txn_rows >= 1:
        score += 3.0
        hint.append("transaction table header (date, debit, credit)")
    elif txn_rows >= 3:
        score += 1.5
    if txn_rows >= 3:
        hint.append(f"{txn_rows} dated transaction rows")
    if score and re.search(r"(?<!\d)\d{20}(?!\d)", re.sub(r"(?<=\d) (?=\d)", "", text)):
        score += 1.0
        hint.append("a 20-digit account number")
    return text, score, ", ".join(hint)


def _finish_classification(doc: ParsedDoc) -> None:
    full = _page_text(doc.pages)
    text, layout_score, hint = statement_layout(doc.pages)
    if not layout_score:
        text = full
    doc.doc_type, doc.type_confidence, doc.type_reason = cls.classify_text(
        text, codes_found=_codes_in(doc.pages[:3]), kind=doc.kind, xlsx_header_score=layout_score,
        structure_hint=hint)
    doc.language = cls.detect_language(full)
    doc.period_start, doc.period_end = cls.detect_period(full, doc.doc_type)
    doc.stir = cls.detect_stir(full)
    if doc.doc_type == "bank_statement":
        _attach_statement_table(doc)


PDF_STATEMENT_UNREADABLE = ("The transaction table of this bank statement could not be read from this PDF or photo. Please "
                            "upload the Excel (XLSX) export from your bank-client.")


def _attach_statement_table(doc: ParsedDoc) -> None:
    """PDF / photo statements: rebuild the transaction table as a sheet for the statement categoriser."""
    from app.pipeline.statements.pdf import has_transactions, pdf_statement_sheet
    try:
        sheet = pdf_statement_sheet(doc.pages)
    except Exception:
        sheet = None
    if sheet is not None and has_transactions(sheet):
        doc.sheets = [sheet]
    elif not doc.failure_cause:
        doc.failure_cause = PDF_STATEMENT_UNREADABLE
