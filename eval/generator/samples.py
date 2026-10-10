"""Public sample files for judges (web/public/samples) built from the hero bundles."""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import date
from pathlib import Path

import numpy as np

from .company import Company
from .noise import photo_jpg, scan_pdf
from .pdf_forms import fmt
from .docs_pdf import TextDoc

IFRS_CO = Company(name="Silk Road Packaging LLC", stir="309557104", industry_key="printing", industry="Packaging",
                  region="Tashkent", bank="Oqsaroy Bank ATB", mfo="01153", account="20208000700557104001",
                  director="Rahimov J.", accountant="Karimova L.", employees=55, since=2017)
IFRS_ROWS = [  # (label, 2025, 2024, bold) in thousand UZS
    ("ASSETS", None, None, True),
    ("Non-current assets", None, None, True),
    ("Property, plant and equipment, net", 2_418_600, 2_211_300, False),
    ("Intangible assets", 36_200, 41_800, False),
    ("Total non-current assets", 2_454_800, 2_253_100, True),
    ("Current assets", None, None, True),
    ("Inventories", 1_102_450, 964_300, False),
    ("Trade and other receivables", 865_120, 790_640, False),
    ("Cash and cash equivalents", 312_870, 255_410, False),
    ("Total current assets", 2_280_440, 2_010_350, True),
    ("Total assets", 4_735_240, 4_263_450, True),
    ("EQUITY AND LIABILITIES", None, None, True),
    ("Share capital", 800_000, 800_000, False),
    ("Retained earnings", 1_906_540, 1_588_210, False),
    ("Total equity", 2_706_540, 2_388_210, True),
    ("Long-term bank loans", 640_000, 820_000, False),
    ("Total non-current liabilities", 640_000, 820_000, True),
    ("Trade payables", 1_004_310, 851_960, False),
    ("Short-term borrowings", 210_000, 95_000, False),
    ("Other payables", 174_390, 108_280, False),
    ("Total current liabilities", 1_388_700, 1_055_240, True),
    ("Total liabilities", 2_028_700, 1_875_240, True),
    ("Total equity and liabilities", 4_735_240, 4_263_450, True),
]


def english_ifrs(path: Path) -> dict:
    t = TextDoc(path, "Statement of financial position", IFRS_CO.name)
    t.line(IFRS_CO.name, 12, bold=True)
    t.line("Statement of financial position as at 31 December 2025 (IFRS)", 11, bold=True)
    t.line("Thousand UZS · TIN 309557104 · unaudited management accounts", 8.5)
    t.rule()
    t.y -= 4
    t.c.setFont("Sans-Bold", 8.5)
    t.c.drawRightString(440, t.y - 10, "31 Dec 2025")
    t.c.drawRightString(555, t.y - 10, "31 Dec 2024")
    t.y -= 18
    truth = {}
    for label, cur, prev, bold in IFRS_ROWS:
        t.ensure(14)
        t.y -= 14
        t.c.setFont("Sans-Bold" if bold else "Sans", 9)
        t.c.drawString(40 if bold else 52, t.y, label)
        if cur is not None:
            t.c.drawRightString(440, t.y, fmt(cur))
            t.c.drawRightString(555, t.y, fmt(prev))
            truth[label] = {"cur": cur, "prev": prev, "page": 1}
    t.rule()
    t.line("Approved by the director on 20 February 2026.  Director: Rahimov J.   Chief accountant: Karimova L.", 8.5, gap=12)
    t.save()
    # arithmetic check of the sample itself
    v = {k: d["cur"] for k, d in truth.items()}
    assert v["Total assets"] == v["Total non-current assets"] + v["Total current assets"]
    assert v["Total equity and liabilities"] == v["Total equity"] + v["Total liabilities"] == v["Total assets"]
    return {"doc_type": "unknown_or_non_statutory", "language": "en", "rows": truth,
            "expected": "classified as non-statutory layout; values matched by English label without line codes"}


def build_samples(seed_root: Path, out: Path) -> None:
    rng = np.random.default_rng(777)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    bundles = {
        "farovon_loan_file.zip": ("hero_farovon", ["Ariza_FarovonSavdo.pdf", "Balans_2025.pdf", "Balans_1H2026.pdf",
                                                    "Forma2_2025.pdf", "Forma2_1H2026.pdf", "vypiska_2026.xlsx"]),
        "navroz_owner_docs.zip": ("hero_navroz", ["bank_vypiska_2026-01_09.xlsx", "Forma2_1yarim_2026.pdf",
                                                  "Balans_2025_skan.pdf", "schet-faktura_0917.jpg"]),
        "zilola_monitoring.zip": ("hero_zilola", ["forma1_Q2-2026.pdf", "forma2_Q2-2026.pdf", "forma1_Q3-2026.pdf",
                                                  "forma2_Q3-2026.pdf", "vypiska_2026-07_09.xlsx"]),
    }
    manifest = {"note": "Synthetic demonstration documents (declared). Ground truth lives in data/seed/*/truth.json.",
                "files": {}}
    for zname, (src, files) in bundles.items():
        with zipfile.ZipFile(out / zname, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(seed_root / src / f, arcname=f)
        manifest["files"][zname] = {"source": f"data/seed/{src}", "contains": files}
    far = seed_root / "hero_farovon"
    shutil.copy(far / "Forma2_1H2026.pdf", out / "form2_clean.pdf")
    scan_pdf(far / "Forma2_2025.pdf", out / "form2_scan_150dpi.pdf", rng, dpi=150, skew=1.8, blur=0.6, jpeg_q=60)
    shutil.copy(seed_root / "hero_zilola" / "vypiska_2026-07_09.xlsx", out / "statement.xlsx")
    shutil.copy(seed_root / "hero_navroz" / "schet-faktura_0917.jpg", out / "photo_invoice.jpg")
    photo_jpg(far / "Forma2_1H2026.pdf", out / "photo_form2.jpg", rng, long_side=1800, blur=0.35, jpeg_q=72, warp=0.02, skew=1.5)
    ifrs = english_ifrs(out / "english_ifrs.pdf")
    manifest["files"].update({
        "form2_clean.pdf": {"source": "hero_farovon/Forma2_1H2026.pdf", "expected": "form2, text layer, H1-2026"},
        "form2_scan_150dpi.pdf": {"source": "hero_farovon/Forma2_2025.pdf", "expected": "form2 via OCR, FY2025, 150 dpi, skew 1.8°"},
        "statement.xlsx": {"source": "hero_zilola/vypiska_2026-07_09.xlsx", "expected": "bank_statement, Jul-Sep 2026, recurring loan:L-2025-0417 (Sep paid 2 days late)"},
        "photo_invoice.jpg": {"source": "hero_navroz/schet-faktura_0917.jpg", "expected": "quality gate fails: 640x480, blurred"},
        "photo_form2.jpg": {"source": "hero_farovon/Forma2_1H2026.pdf page 1", "expected": "form2 via OCR from a phone photo"},
        "english_ifrs.pdf": ifrs,
    })
    (seed_root / "samples_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    total = sum(p.stat().st_size for p in out.iterdir())
    assert total < 15 * 1024 * 1024, total
    print("samples", {p.name: p.stat().st_size for p in sorted(out.iterdir())}, "total", total)
