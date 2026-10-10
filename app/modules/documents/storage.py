import hashlib
import io
import os
import shutil
import zipfile
from pathlib import Path

from app.core.config import settings

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME = "application/vnd.ms-excel"
# image/heic is accepted so the pipeline answers with its specific message (HEIC is not read yet)
SUPPORTED = {"application/pdf", XLSX_MIME, XLS_MIME, "text/csv", "image/jpeg", "image/png", "image/tiff", "image/heic"}
_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avic")


def files_root() -> Path:
    root = Path(settings.FILES_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def abs_path(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else files_root() / p


def rel_path(p: str | os.PathLike) -> str:
    """Stores paths relative to FILES_DIR when they live inside it."""
    p = Path(p)
    try:
        return str(p.resolve().relative_to(files_root().resolve()))
    except ValueError:
        return str(p)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def detect_mime(content: bytes, filename: str) -> tuple[str, str]:
    """(mime, extension) from magic bytes; the filename is only a tie-breaker."""
    head = content[:1024]
    if b"%PDF" in head:
        return "application/pdf", "pdf"
    if content[:4] == b"PK\x03\x04":
        try:
            names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        except zipfile.BadZipFile:
            names = []
        if any(n.startswith("xl/") for n in names):
            return XLSX_MIME, "xlsx"
        if any(n.startswith("word/") for n in names):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
        return "application/zip", "zip"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff", "tif"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":   # OLE2: legacy Excel, or a legacy Word file
        if "Workbook".encode("utf-16-le") in content or "Book".encode("utf-16-le") in content:
            return XLS_MIME, "xls"
        return "application/msword", "doc"
    if content[4:8] == b"ftyp" and content[8:12] in _HEIC_BRANDS:
        return "image/heic", "heic"
    ext = Path(filename).suffix.lower().lstrip(".") or "bin"
    if b"\x00" not in content[:8192]:
        low = content[:8192].lower()
        if b"<table" in low and ext in ("xls", "htm", "html", "xml"):   # bank-client 'Excel' saved as HTML / XML
            return XLS_MIME, "xls"
        if ext == "csv":
            return "text/csv", "csv"
    return "application/octet-stream", ext


def save_original(doc_uuid: str, content: bytes, ext: str) -> str:
    folder = files_root() / doc_uuid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"original.{ext}"
    path.write_bytes(content)
    return rel_path(path)


def doc_dir(doc_uuid: str) -> Path:
    folder = files_root() / doc_uuid
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def delete_doc_files(doc_uuid: str) -> None:
    shutil.rmtree(files_root() / doc_uuid, ignore_errors=True)
