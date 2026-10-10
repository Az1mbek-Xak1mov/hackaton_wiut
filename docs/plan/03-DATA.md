# 03 — Data, ground truth and metrics

All data is **synthetic and declared**. No real borrower data is used.

## Generator: `eval/generator/` (run: `uv run python -m eval.generator --n 200 --seed 0 --out data/synth`)

| Part | Library | Output |
|---|---|---|
| Company | own lists: 120 Uzbek business names (`MChJ`, `XK`, `AJ`), regions, industries; STIR `[2-3]\d{8}` | `company.json` |
| Financial model | scenario params → monthly sales, COGS %, opex, receivables days, cash; FY and H1 rolled up; F1 balanced by construction (equity plug, then checked) | numbers |
| Form 1 / Form 2 PDF | `reportlab` + IBM Plex Sans/Mono TTF (Cyrillic coverage); 3 layout templates (MoF-style grid, accounting-software export, typed-in variant); label language uz_latn / uz_cyrl / ru per bundle | `form1_FY2025.pdf`, `form1_H1-2026.pdf`, `form2_*.pdf` |
| Bank statement | `openpyxl`; 2 bank layouts (single-row and two-row header); 300–2 500 transactions; purpose texts from a template grammar (RU/UZ mix, abbreviations, typos) | `statement_2026-01_08.xlsx` |
| Application form | `reportlab`; requested amount, term, purpose, declared revenue, declared debts | `application.pdf` |
| Noise | `Pillow` + `opencv` + `pypdfium2` + `img2pdf`: render → rotate ±0.5–3°, Gaussian blur σ 0.4–1.2, JPEG q 35–70, downsample to 150 dpi, salt noise, a stamp overlay, perspective warp (photo) → image-only PDF/JPG | `*_scan.pdf`, `*_photo.jpg` |
| Planted contradictions | per bundle 0–3 drawn from: undeclared loan (R06), application revenue ≠ F2 (R07), F1 not balancing (R01), net profit ≠ ΔRE (R04), inflows ≪ revenue (R05), missing tax declaration (R10), wrong STIR on one document (R09) | recorded in the truth file |

### Hero bundles (pinned to `design/demo-data.json`; the pipeline must re-derive these figures)

| Bundle | Pinned inputs | Expected pipeline output |
|---|---|---|
| `hero_farovon` (APP-2026-0931) | F2 010 FY2025 = 9 842 316 kUZS, H1 = 5 316 400; F1 390/600/140/400 as in demo-data; statement Jan–Aug 2026 with a recurring 18.5 mln repayment on the 20th from contract 2024-1177 (8 payments); application declares revenue 10 400.0 mln (diff 557.7 → 5.7%) and no debts; tax declaration absent; F1 FY2025 as a 150-dpi scan | findings R06 attn, R07 watch, R10 neutral; DSCR 1.47 → 1.04; current ratio 1.48 |
| `hero_navroz` (owner) | statement Jan–Sep 2026 (2 418 txns), F2 H1 2026, F1 2025 scan with 3 low-confidence cells, a 640×480 blurred invoice JPG | owner overview figures; JPG → failed with cause; 3 clarification cards |
| `hero_zilola` (L-2025-0417) | Q2/Q3 F2 with revenue 1 790 → 1 289; statement Jul–Sep with the late 15 Sep installment paid 17 Sep; chain customer receipts falling | M01 + M02 triggered, M04 1.4×, M05 → Attention |
| `portfolio_*` ×148 | loan book CSV (declared synthetic) + Q3 F1/F2 + Jul–Sep statement per borrower; scenario mix targeted at roughly 121/18/9 | statuses **computed** by monitoring; the UI shows whatever the run produces |

## Ground-truth format: `data/synth/<split>/<bundle_id>/truth.json`

```json
{
  "bundle_id": "b0173", "seed": 173, "company": {"name": "…", "stir": "302447118"},
  "documents": [
    {"file": "form2_FY2025.pdf", "doc_type": "form2", "language": "ru", "layout": "mof_grid",
     "variant": {"scan": true, "dpi": 150, "skew_deg": 1.8, "blur": 0.7},
     "period": {"start": "2025-01-01", "end": "2025-12-31"},
     "fields": {"010": {"cur": 9842316, "prev": 9120044, "page": 1}, "020": {…}}}
  ],
  "transactions": {"file": "statement_2026-01_08.xlsx",
     "rows": [{"row": 7, "category": "loan_repayment", "recurring_group": "loan:2024-1177"}]},
  "planted": [{"rule": "R06", "evidence_docs": ["statement_2026-01_08.xlsx", "application.pdf"]}],
  "expected_clean_rules": ["R01", "R02", "R03"]
}
```

## Noise variants (share of test documents)

| Variant | Share | Purpose |
|---|---|---|
| clean text-layer PDF | 40% | baseline |
| uz_cyrl labels | 15% | script coverage |
| scan 300 dpi, skew ≤ 1° | 15% | OCR |
| scan 150 dpi, skew 1–3°, blur | 15% | hard OCR |
| phone photo JPG (perspective + JPEG) | 10% | jury photo path |
| two-row-header statement | 5% (of statements: 50%) | layout robustness |

## Hard cases (hand-made by editing generator outputs; `data/hard/`, test-only)

| # | Case | Expected behaviour |
|---|---|---|
| H01 | page rotated 90° | OSD fixes it; fields extracted |
| H02 | official stamp over 2 value cells | low conf → clarification, not a wrong value |
| H03 | negatives in parentheses + `-` mixed | correct signs |
| H04 | dot thousands `9.842.316` | parsed |
| H05 | units in mln, not thousands | unit detected; ×1000 |
| H06 | prior-year column blank | `prev` missing, conf note "cell blank" |
| H07 | rows out of order + 2 unofficial extra rows | codes mapped, extras unmapped |
| H08 | label typo / apostrophe variants `o‘ oʻ o'` | fuzzy match |
| H09 | mixed Cyrillic/Latin homoglyphs in a label | fold + match |
| H10 | Form 1 split over 2 pages | continuous extraction |
| H11 | statement with USD rows | USD rows excluded, counted, shown |
| H12 | purpose text truncated at 60 chars | model categorisation, lower conf |
| H13 | loan repaid to a microfinance org under an abbreviation | R06 still fires |
| H14 | salaries paid via a card-project bank | categorised as salary |
| H15 | English IFRS balance sheet | label match, "non-statutory layout" |
| H16 | password-protected PDF | failed: "PDF is encrypted" |
| H17 | empty / all-zero form | analyzed, R03 info, nothing invented |
| H18 | same file uploaded twice | R12 |
| H19 | 640×480 blurred phone photo | failed with cause + what was read |
| H20 | a Word doc saved as PDF (letter, no figures) | unknown + "what I could read" |

## Splits

| Split | Seeds | Use |
|---|---|---|
| train | 0–119 | categoriser training, dictionary label tuning |
| dev | 120–159 | threshold tuning |
| test | 160–199 | **reported metrics only**; never inspected while tuning |
| hard | H01–H20 | reported separately |
| hero / portfolio | fixed seeds 9001–9003, 10000–10147 | demo seed, not in metrics |

## Metrics: definitions (`eval/run.py`, `eval/metrics.py`)

| Metric | Definition |
|---|---|
| Field extraction P/R/F1 per doc type | unit = (document, line_code, column). TP: extracted with \|value − truth\| ≤ 1 kUZS. FP: extracted value wrong, or a code not in the truth. FN: truth cell not extracted. Reported per doc type × variant |
| Document type accuracy | over all test documents incl. unknowns |
| Contradiction detection P/R | unit = (bundle, rule_id). TP: planted and fired; FP: fired, not planted, and not in `expected_clean_rules` violation; FN: planted, not fired. Per rule + micro |
| Categoriser | accuracy and macro-F1 over test transactions; rule-only vs model-only vs combined; confusion matrix |
| Recurring detection P/R | unit = recurring group |
| Latency | p50/p95 of `jobs.stage_timings` total per doc type, measured **on the production server** (4 vCPU) for the jury-path number; laptop numbers labelled as such |
| Narrative | verifier acceptance at attempt 1, ≤ 3; template-fallback rate; mean prompt/completion tokens |
| Cost per application (UZS) | Σ `llm_calls` tokens per application × price (08 §params) × FX; infrastructure excluded here (in 08) |
| Officer-minutes | timed trial T-035 (see 08) |

Script outputs: `eval/results/2026-10-10_<git-sha>.json` (machine) → `eval/report.py` → `docs/EVAL.md` (tables) and `GET /api/v1/metrics/eval` (served by the `/metrics` page). Every number on the metrics slide is copied from that JSON. `docs/KNOWN-FAILURES.md` lists each FN/FP class seen on test + hard with an example file.

## Data sources and licences (for README)

| Item | Source | Licence |
|---|---|---|
| Form 1 / Form 2 templates and line codes | official templates on lex.uz (exact document recorded in `forms.yaml` header) | public legal acts |
| Tesseract + `uzb`, `uzb_cyrl`, `rus`, `eng` traineddata | Debian packages `tesseract-ocr-*` | Apache-2.0 |
| IBM Plex Sans / Mono | Google Fonts | SIL OFL 1.1 |
| pdfplumber, rapidfuzz | PyPI | MIT |
| pypdfium2 | PyPI | Apache-2.0 / BSD-3 |
| OpenCV, scikit-learn, openpyxl, reportlab, Pillow, img2pdf | PyPI | Apache-2.0, BSD-3, MIT, BSD, HPND, LGPL-3.0 (img2pdf; used only in the generator, not shipped in the image) |
| Qwen2.5-7B-Instruct (on-prem path) | Hugging Face | Apache-2.0 |
| All company names, STIRs, figures | generated | ours; synthetic |
