# Data sources, external services and licences

Checked 2026-10-11 against `uv.lock`, `web/package-lock.json`, the installed package metadata (`*.dist-info/METADATA`), the Dockerfiles and the code. Versions are the locked ones. Where a licence could not be confirmed from metadata, the table says "see package".

## 1. Data

No public dataset and no real company data are used, for training, evaluation or the demo. Every document on the site is synthetic and declared.

| Data | Where | How it is made | Licence / status |
|---|---|---|---|
| Synthetic loan bundles (Form 1, Form 2, loan application, tax declaration, XLSX bank statement, with ground truth) | `eval/generator/` → `data/synth/` (git-ignored, regenerated) | `uv run python -m eval.generator synth --n 200 --seed 0`. Each bundle `b{seed:04d}` uses `numpy.random.default_rng(seed)`. Splits: seeds 0–119 train, 120–159 dev, 160–199 test. A monthly P&L model (`finmodel.py`) produces Form 1/2 that balance by construction. Contradictions are planted with labels (`truth.json → planted[]`). Scan and photo noise comes from `noise.py`. Company names, STIRs, banks and accounts are fictional (`company.py`). | ours, synthetic |
| Hero / demo bundles (Farovon, Navroz, Zilola) | `data/seed/hero_*` | `eval.generator heroes`. Leaf values are pinned to the design reference `design/demo-data.json` (the design is a generator target). The pipeline re-derives every figure from the files. | ours, synthetic |
| Loan book and monitoring bundles (148 borrowers) | `data/seed/loan_book.csv`, `data/seed/portfolio/` | `eval.generator portfolio`. Seeds start at 10 000. Each bundle stores the scenario parameters it was generated from; the status itself is not stored and is computed by the monitoring run. | ours, synthetic |
| Hard cases H01–H20 | `data/hard/` | `eval.generator hard`, built by hand. Used only for testing, never for tuning. | ours, synthetic |
| Public sample files | `web/public/samples/` | `eval.generator samples`, built from the hero bundles | ours, synthetic |
| Statement categoriser training data | `data/synth/train/*` (120 bundles, 48 861 rows; from `app/pipeline/statements/model_metrics.json`) | The labels are the generator's own ground-truth categories, so no human labelling was done. `uv run python -m eval.train_categoriser` fits TF-IDF (char 2–5-grams) + logistic regression, evaluates on dev, and writes `app/pipeline/statements/model.joblib` and `model_metrics.json`. The test split is never read. | ours, synthetic |
| Form 1 / Form 2 line-code dictionary | `app/pipeline/dictionary/forms.yaml` | Codes, formulas and the RU / UZ-Cyrillic labels come from MoF order No. 140 of 27.12.2002 (reg. No. 1209 of 24.01.2003), appendices 1 and 2, as amended by MoF order No. 10 of 23.01.2019 (reg. No. 1209-10 of 15.02.2019), text at https://lex.uz/docs/771825. They were checked against that page on 2026-10-10. The UZ-Latin labels are our transliteration and the EN labels are our own. | The Law of the Republic of Uzbekistan "On copyright and related rights" (No. ZRU-42 of 20.07.2006, https://lex.uz/docs/1022944), art. 8, lists "official documents (laws, resolutions, decisions and the like) and their official translations" among materials that are not objects of copyright. We did not review lex.uz's own site terms of use. |
| Fonts embedded in generated PDFs | `eval/generator/fonts/` (IBM Plex Sans / Mono, with `OFL.txt`) | copied from IBM Plex | SIL OFL 1.1 |

## 2. External services

| Service | Used for | What is sent | Paid | Terms |
|---|---|---|---|---|
| **OpenAI API**, model `gpt-4.1-mini` (`LLM_MODEL` in `app/core/config.py`) | live demo server only (`LLM_PROVIDER=openai`) | **Loan narrative / borrower explanation** (`app/modules/llm/narrative.py`, `borrower.py`): a JSON of facts (id, label, value, unit, period) and findings (rule id, title, evidence ids). With `LLM_REDACT=true` (the default) the borrower's name becomes "the borrower" and the STIR becomes `[STIR]`. No document files and no page images are sent. **Unmapped Form 1/2 line** (`unmapped.py`): the row's text, its printed amount and up to 5 candidate dictionary labels. **AI CFO** (`app/modules/cfo/service.py`): the owner's question, the list of document types on file, and tool results (figures, labels, and transaction counterparties when asked about), with the borrower's name and STIR redacted. **Public `/analyse`** (`describe.py`), used only for documents that are not a recognised form, statement or application: the type guess, the language, the page count, the first 1 200 characters of the text that was read, and the numbers that were read with their labels. STIRs found in the document are redacted. | yes: per token. Its cost is in [`docs/plan/08-BUSINESS.md`](plan/08-BUSINESS.md) (p9, p10) | https://openai.com/policies/business-terms/ (plus the API data-usage policies listed at https://openai.com/policies/) |
| Google Fonts (IBM Plex Sans / Mono) | `web/index.html` loads the web fonts in the viewer's browser | a normal font request from the browser (the viewer's IP address, user agent) | no | https://developers.google.com/fonts/faq/privacy |

**No egress option.** With `LLM_PROVIDER=none`, or with the runtime "LLM off" switch, nothing is sent anywhere. Narratives become template summaries, and extraction, reconciliation, ratios and monitoring work exactly the same, because they never call the LLM. With `LLM_PROVIDER=ollama` and `LLM_BASE_URL` pointing at an Ollama server inside the perimeter, the same prompts go to that server and to no third party. That path uses the same OpenAI-compatible client with a different base URL. It has **not** been run or measured against a local model yet (see `docs/plan/00-STRATEGY.md`). For a bank deployment the fonts would be self-hosted (they are OFL) so that the browser makes no Google request.

`ANTHROPIC_API_KEY` / `LLM_PROVIDER=anthropic` is supported over plain `httpx` (no SDK) and is not used on the demo server.

## 3. Runtime dependencies (in the API image)

The image is built with `uv sync --locked --no-default-groups`, so the `dev` (pytest) and `eval` (reportlab, img2pdf) groups are **not** in the image.

| Package | Version | Licence |
|---|---|---|
| FastAPI | 0.143.0 | MIT |
| Starlette | 1.7.0 | BSD-3-Clause |
| fastapi-pagination | 0.16.1 | MIT |
| uvicorn (+ uvloop, httptools, watchfiles, websockets) | 0.54.0 | BSD-3-Clause (uvloop MIT / Apache-2.0; httptools, watchfiles MIT; websockets BSD-3-Clause) |
| python-multipart | 0.0.32 | Apache-2.0 |
| SQLAlchemy | 2.1.4 | MIT |
| Alembic | 1.20.0 | MIT |
| psycopg2-binary | 2.9.13 | **LGPL** with exceptions (the wheel bundles libpq, OpenSSL and Kerberos libraries; see package) |
| pydantic / pydantic-core / pydantic-settings | 2.14.0 / 2.50.0 / 2.15.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| PyJWT | 2.15.1 | MIT |
| pwdlib (+ argon2-cffi, argon2-cffi-bindings) | 0.3.1 (25.1.0, 26.1.0) | MIT |
| tzdata | 2026.5 | Apache-2.0 |
| pdfplumber (+ pdfminer.six) | 0.11.10 (20260107) | MIT |
| pypdfium2 (bundles PDFium) | 5.14.0 | BSD-3-Clause, Apache-2.0 and bundled dependency licences (see package) |
| pytesseract | 0.3.13 | Apache-2.0 |
| opencv-python-headless | 5.0.0.93 | Apache-2.0. The wheel bundles third-party libraries: see its `LICENSE-3RD-PARTY.txt` |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| Pillow | 12.3.0 | MIT-CMU (HPND) |
| openpyxl (+ et_xmlfile) | 3.1.5 | MIT |
| RapidFuzz | 3.14.6 | MIT |
| scikit-learn (+ scipy, threadpoolctl) | 1.9.1 | BSD-3-Clause (scipy BSD; see package) |
| joblib | 1.6.0 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| openai (Python SDK) | 3.28.0 | Apache-2.0 |
| xlrd (legacy `.xls` statements) | 2.0.2 | BSD |
| anthropic SDK | not a dependency | — |

Generator / eval only (not in the image): reportlab 5.0.1 (BSD), img2pdf 0.6.3 (LGPL-3.0), pytest 9.1.1 (MIT).

## 4. System components and images

| Component | Version | Licence |
|---|---|---|
| Tesseract OCR engine (`tesseract-ocr`, Debian bookworm package in the image) | bookworm package | Apache-2.0 |
| Tesseract language data `uzb`, `uzb_cyrl`, `rus`, `eng` (`tesseract-ocr-*`, Debian source package `tesseract-lang`, upstream `tesseract-ocr/tessdata_fast`) | bookworm package | Apache-2.0 |
| PostgreSQL (`postgres:16-alpine`) | 16 | PostgreSQL License |
| nginx (`nginx:1.27-alpine` serves the SPA; the host nginx terminates TLS) | 1.27 | BSD-2-Clause |
| `python:3.12-slim-bookworm` (runtime base) | 3.12 | Python: PSF-2.0; Debian packages under their own licences |
| `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` (build stage only, not shipped) | — | uv: MIT OR Apache-2.0 |
| `node:22-alpine` (web build stage only, not shipped) | 22 | Node.js: MIT |
| IBM Plex Sans / Mono | — | SIL OFL 1.1 |

## 5. Web dependencies (`web/package-lock.json`)

| Package | Version | Licence | In the shipped bundle |
|---|---|---|---|
| Vue (+ @vue/*) | 3.5.13 | MIT | yes |
| vue-router | 4.4.5 | MIT | yes |
| Pinia (+ @vue/devtools-api, vue-demi) | 2.2.6 | MIT | yes |
| Vite (+ esbuild, rollup) | 5.4.11 | MIT | build only |
| @vitejs/plugin-vue | 5.2.1 | MIT | build only |
| vue-tsc | 2.1.10 | MIT | build only |
| TypeScript | 5.6.3 | Apache-2.0 | build only |

## 6. Models

| Model | Status |
|---|---|
| Statement categoriser `app/pipeline/statements/model.joblib` | ours, trained on synthetic data (see §1) |
| `gpt-4.1-mini` (OpenAI) | external paid API on the demo server (see §2) |
| Qwen2.5-7B-Instruct via Ollama (Apache-2.0 per its model card; not downloaded or run in this project) | the intended on-prem model. Not deployed, not measured |
