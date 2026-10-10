"""Scan / photo degradations: text-layer PDF -> image-only PDF or JPG."""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import img2pdf
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .pdf_forms import FONT_DIR


def render_pages(pdf_path: Path, dpi: int) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    out = [pdf[i].render(scale=dpi / 72).to_pil().convert("L") for i in range(len(pdf))]
    pdf.close()
    return out


def _stamp(img: Image.Image, rng: np.random.Generator, text: str, center: tuple[int, int] | None = None,
           radius: int | None = None) -> Image.Image:
    """Blue round company stamp (multiplied over the page)."""
    w, h = img.size
    r = radius or int(min(w, h) * 0.085)
    cx, cy = center or (int(w * rng.uniform(0.55, 0.75)), int(h * rng.uniform(0.80, 0.9)))
    rgb = img.convert("RGB")
    layer = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    col = (40, 60, 170, 150)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=max(2, r // 25))
    d.ellipse([cx - int(r * .72), cy - int(r * .72), cx + int(r * .72), cy + int(r * .72)], outline=col, width=max(1, r // 40))
    try:
        f = ImageFont.truetype(str(FONT_DIR / "IBMPlexSans-Bold.ttf"), max(10, r // 5))
    except OSError:
        f = ImageFont.load_default()
    d.text((cx, cy), text[:22], fill=col, font=f, anchor="mm")
    layer = layer.rotate(float(rng.uniform(-25, 25)), center=(cx, cy))
    rgb.paste(layer, (0, 0), layer)
    return rgb


def degrade(img: Image.Image, rng: np.random.Generator, *, skew: float, blur: float, jpeg_q: int,
            salt: float = 0.0005, gray_level: int = 245) -> Image.Image:
    rgb = img.convert("RGB")
    rot = rgb.rotate(skew, resample=Image.BICUBIC, expand=False, fillcolor=(gray_level, gray_level, gray_level))
    if blur > 0:
        rot = rot.filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(rot).astype(np.float32)
    # uneven illumination + paper tone
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 1.0 - 0.06 * ((xx / w - rng.uniform(0, 1)) ** 2 + (yy / h - rng.uniform(0, 1)) ** 2)
    a = a * shade[..., None] * rng.uniform(0.95, 1.0) + rng.normal(0, 4, a.shape)
    m = rng.random(a.shape[:2])
    a[m < salt] = 0
    a[m > 1 - salt] = 255
    a = np.clip(a, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(a).convert("L").save(buf, "JPEG", quality=int(jpeg_q))
    return Image.open(io.BytesIO(buf.getvalue()))


def scan_pdf(src: Path, dst: Path, rng: np.random.Generator, *, dpi: int = 300, skew: float = 0.5,
             blur: float = 0.4, jpeg_q: int = 70, stamp: str | None = None, stamp_xy=None) -> dict:
    """Replace a text-layer PDF by an image-only scan (no text layer)."""
    pages = render_pages(src, dpi)
    jpgs = []
    for i, p in enumerate(pages):
        if stamp and i == len(pages) - 1:
            p = _stamp(p, rng, stamp, center=stamp_xy)
        q = degrade(p, rng, skew=skew if i == 0 else skew * rng.uniform(0.6, 1.2), blur=blur, jpeg_q=jpeg_q)
        buf = io.BytesIO()
        q.save(buf, "JPEG", quality=int(jpeg_q), dpi=(dpi, dpi))
        jpgs.append(buf.getvalue())
    layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
    dst.write_bytes(img2pdf.convert(jpgs, layout_fun=layout))
    return {"scan": True, "dpi": dpi, "skew_deg": round(skew, 2), "blur": round(blur, 2), "jpeg_q": int(jpeg_q),
            "stamp": bool(stamp)}


def photo_jpg(src: Path, dst: Path, rng: np.random.Generator, *, page: int = 0, long_side: int = 1700,
              blur: float = 0.6, jpeg_q: int = 62, warp: float = 0.05, skew: float = 2.0) -> dict:
    """Phone photo of one page: perspective, shadow, JPEG. Returns variant info."""
    img = render_pages(src, 200)[page].convert("RGB")
    a = np.asarray(img)
    h, w = a.shape[:2]
    # place the page on a darker "desk" background with margin
    pad = int(0.06 * max(h, w))
    canvas_img = np.full((h + 2 * pad, w + 2 * pad, 3), (int(rng.uniform(70, 120)),) * 3, dtype=np.uint8)
    canvas_img[pad:pad + h, pad:pad + w] = a
    H, W = canvas_img.shape[:2]
    src_q = np.float32([[pad, pad], [pad + w, pad], [pad + w, pad + h], [pad, pad + h]])
    j = lambda s: rng.uniform(-warp, warp) * s  # noqa: E731
    dst_q = np.float32([[pad + j(w), pad + j(h)], [pad + w + j(w), pad + j(h)],
                        [pad + w + j(w), pad + h + j(h)], [pad + j(w), pad + h + j(h)]])
    M = cv2.getPerspectiveTransform(src_q, dst_q)
    warped = cv2.warpPerspective(canvas_img, M, (W, H), borderValue=(90, 90, 90))
    pil = Image.fromarray(warped).rotate(skew, resample=Image.BICUBIC, fillcolor=(90, 90, 90))
    # shadow gradient
    arr = np.asarray(pil).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    shadow = 1 - 0.25 * np.clip((xx / W - rng.uniform(0.3, 0.9)), 0, 1)
    arr = np.clip(arr * shadow[..., None] + rng.normal(0, 5, arr.shape), 0, 255).astype(np.uint8)
    pil = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(blur))
    scale = long_side / max(pil.size)
    pil = pil.resize((int(pil.size[0] * scale), int(pil.size[1] * scale)), Image.LANCZOS)
    pil.save(dst, "JPEG", quality=int(jpeg_q))
    return {"photo": True, "long_side_px": long_side, "blur": round(blur, 2), "jpeg_q": int(jpeg_q),
            "warp": round(warp, 3), "skew_deg": round(skew, 2)}


def blur_score(path: Path) -> float:
    g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())
