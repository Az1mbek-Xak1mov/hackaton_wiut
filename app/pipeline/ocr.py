"""OCR for scans and photos: render → orientation (OSD) → deskew → illumination normalise → Tesseract.

Languages are chosen per page from the OSD script (Cyrillic → rus+uzb_cyrl, Latin → uzb+eng) and
intersected with what is installed, so a missing traineddata never crashes the pipeline.
Local development: put traineddata in <repo>/.tessdata (used automatically) or set TESSDATA_PREFIX.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image

from app.pipeline.types import Word

_REPO_TESSDATA = Path(__file__).resolve().parents[2] / ".tessdata"
WANTED = ("uzb", "uzb_cyrl", "rus", "eng")
OCR_DPI = 300


@lru_cache(maxsize=1)
def _tessdata_config() -> str:
    if not os.environ.get("TESSDATA_PREFIX") and (_REPO_TESSDATA / "uzb.traineddata").exists():
        return f'--tessdata-dir "{_REPO_TESSDATA}"'
    return ""


@lru_cache(maxsize=1)
def available_langs() -> tuple[str, ...]:
    try:
        langs = pytesseract.get_languages(config=_tessdata_config())
    except Exception:  # tesseract not installed
        return ()
    return tuple(l for l in WANTED if l in langs) + (("osd",) if "osd" in langs else ())


def langs_for(script: str | None) -> str:
    have = [l for l in available_langs() if l != "osd"]
    if script == "Cyrillic":
        pick = [l for l in ("rus", "uzb_cyrl") if l in have]
    elif script == "Latin":
        pick = [l for l in ("uzb", "eng") if l in have]
    else:
        pick = [l for l in ("rus", "uzb") if l in have]
    return "+".join(pick or have or ["eng"])


def _cfg(extra: str) -> str:
    return f"{_tessdata_config()} {extra}".strip()


def render_pdf_page(path: str, index: int, dpi: int = OCR_DPI) -> Image.Image:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[index]
        img = page.render(scale=dpi / 72.0).to_pil()
        page.close()
        return img.convert("RGB")
    finally:
        pdf.close()


def to_gray(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian on a width-normalised (1700 px ≈ A4 at 200 dpi) copy. Higher = sharper."""
    h, w = gray.shape[:2]
    scale = 1700.0 / max(1, w)
    g = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _binarise_small(gray: np.ndarray, width: int = 1000) -> np.ndarray:
    h, w = gray.shape[:2]
    s = width / max(1, w)
    g = cv2.resize(gray, (width, max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _rotate(img: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def estimate_skew(gray: np.ndarray, max_angle: float = 15.0) -> float:
    """Projection-profile skew estimate in degrees (positive = rotate counter-clockwise to fix)."""
    b = _binarise_small(gray)

    def score(a: float) -> float:
        r = _rotate(b, a, border=0)
        prof = r.sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(prof) ** 2))

    best = max(np.arange(-max_angle, max_angle + 0.01, 0.5), key=score)
    fine = max(np.arange(best - 0.5, best + 0.51, 0.1), key=score)
    return float(round(fine, 2))


def detect_osd(gray: np.ndarray) -> tuple[int, str | None]:
    """(rotation in degrees to apply clockwise, script) from Tesseract OSD; (0, None) on failure."""
    if "osd" not in available_langs():
        return 0, None
    h, w = gray.shape[:2]
    s = min(1.0, 1800.0 / max(h, w))
    small = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray
    try:
        out = pytesseract.image_to_osd(Image.fromarray(small), config=_cfg("--psm 0 -c min_characters_to_try=10"))
    except Exception:
        return 0, None
    rot = re.search(r"Rotate:\s*(\d+)", out)
    oconf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
    script = re.search(r"Script:\s*(\w+)", out)
    sconf = re.search(r"Script confidence:\s*([\d.]+)", out)
    angle = int(rot.group(1)) if rot and oconf and float(oconf.group(1)) >= 1.5 else 0
    sc = script.group(1) if script and sconf and float(sconf.group(1)) >= 0.5 else None
    return angle, sc


def speck_share(gray: np.ndarray) -> float:
    """Share of tiny connected components (≤ 3 px at ~145 dpi): salt-and-pepper / dust noise level."""
    h, w = gray.shape[:2]
    s = 1200.0 / max(1, w)
    small = cv2.resize(gray, (1200, max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    _, b = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, _, stats, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    return float((areas <= 3).sum() / len(areas)) if len(areas) >= 50 else 0.0


def denoise(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Median filter sized by the measured speck noise. Returns (image, speck share)."""
    share = speck_share(gray)
    if share > 0.3:
        return cv2.medianBlur(gray, 5), share
    return cv2.medianBlur(gray, 3), share


def remove_table_lines(gray: np.ndarray) -> tuple[np.ndarray, int]:
    """Paint long horizontal / vertical rules white (grid forms): OCR otherwise reads them as | [ ] { }."""
    h, w = gray.shape[:2]
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 25), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 45)))
    lines = cv2.bitwise_or(cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk), cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk))
    n = int(cv2.countNonZero(lines))
    if n == 0:
        return gray, 0
    lines = cv2.dilate(lines, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    out = gray.copy()
    out[lines > 0] = 255
    return out, n


def normalise_illumination(gray: np.ndarray) -> np.ndarray:
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=25)
    norm = cv2.divide(gray, bg, scale=255)
    return norm


_DEBRIS = "|[]{}¦"


def _strip_debris(text: str) -> str:
    """Remove table-rule debris around a token: '[3000' -> '3000', '1812040)' -> '1812040'."""
    t = text.strip(_DEBRIS)
    if t.endswith(")") and "(" not in t and any(c.isdigit() for c in t):
        t = t[:-1]
    if t.startswith("(") and ")" not in t and any(c.isdigit() for c in t):
        t = t[1:]
    if any(c.isdigit() for c in t):
        t = t.rstrip(",.;:—–_'\"’`~")
        if t.endswith("-") and len(t) > 1 and t[-2].isdigit():
            t = t[:-1]
    return t


@dataclass
class OcrPage:
    words: list[Word]
    width: int
    height: int
    image: Image.Image          # processed (rotated + deskewed) grayscale page, OCR pixel space
    mean_conf: float | None
    skew_deg: float
    rotation: int
    blur: float
    script: str | None
    seconds: float
    lang: str = ""


def _profile_cv(b: np.ndarray) -> float:
    prof = b.sum(axis=1, dtype=np.float64)
    return float(np.var(prof) / (np.mean(prof) ** 2 + 1e-9))


def needs_quarter_turn(gray: np.ndarray) -> bool:
    """Text lines run vertically (page scanned / photographed sideways): the row-sum profile of the image
    turned by 90° is far more structured than the upright one."""
    b = _binarise_small(gray)
    cv0, cv90 = _profile_cv(b), _profile_cv(np.ascontiguousarray(np.rot90(b)))
    return cv90 > 1.0 and cv90 > 2.5 * cv0


def _tesseract(proc: np.ndarray, lang: str, psm: int) -> tuple[list[Word], float | None]:
    data = pytesseract.image_to_data(Image.fromarray(proc), lang=lang, config=_cfg(f"--psm {psm} --oem 1"),
                                     output_type=pytesseract.Output.DICT)
    words: list[Word] = []
    confs = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not text or conf < 0:
            continue
        text = _strip_debris(text)
        if not text:
            continue
        x, y, ww, hh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append(Word(text=text, x0=float(x), y0=float(y), x1=float(x + ww), y1=float(y + hh), conf=conf / 100.0))
        confs.append(conf)
    return words, (sum(confs) / len(confs)) if confs else None


def _prepare(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    skew = estimate_skew(gray)
    if abs(skew) >= 0.15:
        gray = _rotate(gray, skew)
    proc, _ = remove_table_lines(normalise_illumination(gray))
    return gray, proc, skew


def _other_langs(lang: str) -> str | None:
    have = [l for l in available_langs() if l != "osd"]
    if "rus" in lang or "uzb_cyrl" in lang:
        alt = [l for l in ("uzb", "eng") if l in have]
    else:
        alt = [l for l in ("rus", "uzb_cyrl") if l in have]
    return "+".join(alt) if alt else None


def ocr_image(img: Image.Image, *, lang: str | None = None, psm: int = 6, retry_below: float = 85.0) -> OcrPage:
    """OCR one page. Retries once with the other script's languages, and once upside down after a quarter
    turn, when recognition confidence is poor — OSD script / orientation guesses are unreliable on noisy scans."""
    t0 = time.perf_counter()
    gray = to_gray(img)
    # small images (phone photos, low-dpi scans): upscale so text is ~30 px high for Tesseract
    h, w = gray.shape[:2]
    short = min(h, w)
    if short < 1600:
        f = min(2.5, 2400.0 / max(1, short))
        gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC)
    gray, _impulse = denoise(gray)
    blur = blur_score(gray)
    rotation = 0
    turned = False
    if needs_quarter_turn(gray):
        gray = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
        rotation, turned = 90, True
    osd_rot, script = detect_osd(gray)
    if osd_rot == 180 or (osd_rot in (90, 270) and not turned):
        k = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[osd_rot]
        gray = cv2.rotate(gray, k)
        rotation = (rotation + osd_rot) % 360
    gray, proc, skew = _prepare(gray)
    lang = lang or langs_for(script)
    words, conf = _tesseract(proc, lang, psm)
    if conf is None or conf < retry_below:
        alt = _other_langs(lang)
        if alt:
            w2, c2 = _tesseract(proc, alt, psm)
            if c2 is not None and (conf is None or c2 > conf + 2):
                words, conf, lang = w2, c2, alt
    if turned and (conf is None or conf < 70):  # quarter turn went the wrong way: try upside down
        g2 = cv2.rotate(gray, cv2.ROTATE_180)
        g2, p2, s2 = _prepare(g2)
        w2, c2 = _tesseract(p2, lang, psm)
        if c2 is not None and (conf is None or c2 > conf + 5):
            gray, proc, skew, words, conf = g2, p2, s2, w2, c2
            rotation = (rotation + 180) % 360
    hh, ww = proc.shape[:2]
    return OcrPage(words=words, width=ww, height=hh, image=Image.fromarray(gray), mean_conf=conf,
                   skew_deg=skew, rotation=rotation, blur=blur, script=script, seconds=time.perf_counter() - t0,
                   lang=lang)


def reocr_digits(page_img: Image.Image, bbox: list[float], pad: float = 6.0) -> tuple[str, float] | None:
    """Second pass on one numeric cell with a digit whitelist. Returns (text, conf 0-1) or None."""
    x0, y0, x1, y1 = bbox
    W, H = page_img.size
    box = (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(W, int(x1 + pad)), min(H, int(y1 + pad)))
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return None
    crop = normalise_illumination(np.asarray(page_img.crop(box).convert("L")))
    try:
        data = pytesseract.image_to_data(Image.fromarray(crop), lang="eng",
                                         config=_cfg("--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789()-.,"),
                                         output_type=pytesseract.Output.DICT)
    except Exception:
        return None
    toks = [(t.strip(), float(c)) for t, c in zip(data["text"], data["conf"]) if t and t.strip() and float(c) >= 0]
    if not toks:
        return None
    text = " ".join(t for t, _ in toks)
    conf = sum(c for _, c in toks) / len(toks) / 100.0
    return text, conf
