# Converza

**Converza is a document-to-evidence engine for Uzbek SME financials. Every number can be clicked back to the page it came from, and the model is not allowed to state a number that isn't in the records.**

Team **10x engineers**. Partner product for MKBANK's SME Lending Department, with the Central Bank as co-partner (explainability, audit trail, human-in-the-loop). It changes two processes: preparing a loan file, and monitoring the borrower after disbursement.

Live: **https://converza.uz**

| Route | Who | What it shows |
|---|---|---|
| `/analyse` | anyone, no login | Upload a PDF, XLSX or JPG. Converza classifies it, extracts what it can, and always returns something true, including "not a recognised statutory form; here is what I could read". Click any value to see its page with the cell highlighted. |
| `/login` → **Enter as bank officer** | demo officer | `/bank` portfolio overview, `/bank/applications/APP-2026-0931` loan review (issues, extracted figures, ratios, grounded narrative, evidence pane, decision record), `/bank/borrowers` monitoring statuses with reasons |
| `/login` → **Enter as business owner** | demo owner | `/owner/cfo` AI CFO answers with evidence chips; `/owner/upload` the owner's documents |
| `/metrics` | anyone | the newest evaluation results JSON, rendered as is |
| `/api/v1/version` | anyone | the deployed git SHA and build/deploy time (see **Deployment**) |

## Try it with the sample bundles

All documents are **synthetic and declared**. Companies, tax IDs, banks and figures are generated (see `eval/generator/`).

| Download | Contents | What to look for |
|---|---|---|
| [`farovon_loan_file.zip`](https://converza.uz/samples/farovon_loan_file.zip) | loan application, Form 1 balance sheet ×2 (one is a scan), Form 2 income statement ×2, bank statement | an undeclared recurring loan, application vs income-statement revenue contradiction, missing tax declaration, OCR on a scan |
| [`navroz_owner_docs.zip`](https://converza.uz/samples/navroz_owner_docs.zip) | bank statement, Form 2, scanned balance sheet with a stamp, blurred invoice photo | categorised cash flow, clarification of low-confidence cells, a photo rejected with the reason |
| [`zilola_monitoring.zip`](https://converza.uz/samples/zilola_monitoring.zip) | Form 1 and Form 2 for two consecutive quarters, three-month bank statement | monitoring indicators: revenue drop, receivables growth, cash coverage of the installment, a late installment |

Single files: [`form2_clean.pdf`](https://converza.uz/samples/form2_clean.pdf), [`form2_scan_150dpi.pdf`](https://converza.uz/samples/form2_scan_150dpi.pdf), [`photo_form2.jpg`](https://converza.uz/samples/photo_form2.jpg), [`photo_invoice.jpg`](https://converza.uz/samples/photo_invoice.jpg), [`statement.xlsx`](https://converza.uz/samples/statement.xlsx), [`english_ifrs.pdf`](https://converza.uz/samples/english_ifrs.pdf).

## How it works

It is a pipeline of separate stages, not a single prompt. Deterministic stages come first; the language model is used only where text has to be written. Details are in [`docs/plan/02-PIPELINE.md`](docs/plan/02-PIPELINE.md).

| # | Stage | Method |
|---|---|---|
| 1 | Classify | file type, then keyword scoring over the first page in UZ-Latin, UZ-Cyrillic, RU and EN; language detection |
| 2 | Parse | `pdfplumber` text layer; Tesseract (`uzb`, `uzb_cyrl`, `rus`, `eng`) with deskew/binarise for scans and photos; `openpyxl` for XLSX; a quality gate that explains why a file is unreadable |
| 3 | Statutory extraction | Form 1 / Form 2 line-code dictionary ([`app/pipeline/dictionary/forms.yaml`](app/pipeline/dictionary/forms.yaml), checked against the official templates on lex.uz) plus fuzzy label matching. Every value keeps its page, bounding box and passage. The LLM is only a schema-validated fallback for unmapped lines |
| 4 | Statement normalisation | counterparty / STIR / account regexes; purpose-text categoriser (rules first, then a TF-IDF + logistic regression model trained on our labelled synthetic set); recurring-payment detection for loans, salaries and taxes |
| 5 | Reconciliation | rule library R01–R12: the balance sheet balances, P&L ↔ equity change, revenue ↔ bank inflows, declared ↔ detected loans, application ↔ statements, periods, tax IDs, missing documents. Each finding cites its evidence |
| 6 | Ratios and monitoring | deterministic formulas stored with their inputs; monitoring indicators M01–M06 with disclosed thresholds → Stable / Watch / Attention, always with the reason |
| 7 | Grounded narrative | the LLM receives only a JSON of facts with ids and must cite them. A **citation verifier** ([`app/pipeline/verify.py`](app/pipeline/verify.py)) checks every number in the output against the fact it cites; failing drafts are regenerated, then replaced by a labelled template summary. Rejected drafts stay visible in the review trail |
| 8 | AI CFO Q&A | tool calls over the facts store. The model cannot do arithmetic: it calls `compute`, which registers a citable derived fact. Answers go through the same verifier |

**LLM off.** Officers can switch the LLM off in the top bar. Extraction, reconciliation, ratios and monitoring don't use the LLM, so they stay exactly the same; narratives become template summaries. `LLM_PROVIDER=openai|anthropic|ollama|none`. In the bank deployment the same prompts run on a local 7B model (Qwen2.5-7B-Instruct via ollama) with no external calls. The demo server has no GPU, so production uses the OpenAI API and sends redacted facts JSON only.

**Human in the loop.** Low-confidence values go to clarification. The officer can verify, correct or flag any fact; a correction re-runs the rules and ratios. Findings are resolved or dismissed with a note. Only an officer records a decision, and the reasoning plus the evidence they opened are stored with it. Fact reviews, finding changes, decisions, uploads, monitoring runs and the LLM switch are written to the audit log.

## Run locally

Requirements: [uv](https://docs.astral.sh/uv/), Docker, Node 22, and Tesseract with the `uzb`, `uzb_cyrl`, `rus` and `eng` language packs to run OCR outside Docker (the Docker image installs them).

```bash
cp .env.example .env                 # set JWT_SECRET (openssl rand -hex 32); OPENAI_API_KEY optional, LLM_PROVIDER=none works
docker compose up -d db              # Postgres on localhost:5462
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8020      # API + in-process worker, http://localhost:8020/docs
uv run python -m app.seed_demo       # pushes data/seed through the real pipeline (users, loan book, documents, monitoring)
cd web && npm ci && npm run dev      # http://localhost:5173 (proxies /api to :8020)
```

API and database in Docker instead: `docker compose --profile full up -d --build`, then start the web dev server as above. Tests: `uv run pytest -q` and `cd web && npm run build`.

## Evaluation

```bash
uv run python -m eval.generator all              # synthetic bundles (data/synth), hero/demo seed (data/seed), samples, hard cases (data/hard)
uv run python -m eval.run --split test           # real pipeline vs ground truth → eval/results/<date>_<time>_<sha>.json
uv run python -m eval.latency_prod               # production job timings (read-only) merged into the newest results JSON
```

Results, definitions and per-document-type tables are in [`docs/EVAL.md`](docs/EVAL.md). Known failure classes, each with an example file, are in [`docs/KNOWN-FAILURES.md`](docs/KNOWN-FAILURES.md). The `/metrics` page renders the same JSON. This README quotes no accuracy, latency or cost figures; see `docs/EVAL.md`.

## Honesty statement

- **Synthetic, declared data.** Every demo document is generated and labelled as such on the site. The loan book (amounts, terms, repayments) is a declared synthetic input.
- **No scripted outputs.** Every figure, finding, status, ratio and AI sentence on the site is produced by the pipeline from uploaded files. The demo seed uploads files through the same services the UI uses; no results are inserted.
- **No credit score.** Status is Stable / Watch / Attention from disclosed rules and always carries its reason. Thresholds are illustrative; calibration against bank history is pilot month 1. The system never approves or rejects.
- **No invented metrics.** Every accuracy, latency or cost number we state comes from `eval/results/*.json`, production job timings or LLM call logs, with n and the dataset named. These are measured on our generator's test split and hand-made hard cases, which overstates real-document accuracy. Real-document evaluation is pilot month 1.

## Data sources and licences

| Item | Source | Licence |
|---|---|---|
| Form 1 / Form 2 templates and line codes | official templates on lex.uz (exact act recorded in `forms.yaml`) | public legal acts |
| Tesseract + `uzb`, `uzb_cyrl`, `rus`, `eng` traineddata | Debian packages `tesseract-ocr-*` | Apache-2.0 |
| IBM Plex Sans / Mono | IBM / Google Fonts | SIL OFL 1.1 |
| pdfplumber, rapidfuzz | PyPI | MIT |
| pypdfium2 | PyPI | Apache-2.0 / BSD-3 |
| OpenCV, scikit-learn, openpyxl, reportlab, Pillow, img2pdf | PyPI | Apache-2.0, BSD-3, MIT, BSD, HPND, LGPL-3.0 (img2pdf: generator only, not in the image) |
| Qwen2.5-7B-Instruct (on-prem path) | Hugging Face | Apache-2.0 |
| All company names, tax IDs, banks, figures | generated by `eval/generator` | ours, synthetic |

## Deployment

Pushing to `main` runs GitHub Actions: tests, then an ssh deploy to the server (`deploy/deploy.sh`), then a check that `/api/v1/version` returns the pushed SHA. Every deploy is listed in the repository's **Deployments** tab (environment `production`) and in the server's `deploys.log`. Details: [`docs/plan/06-DEPLOY.md`](docs/plan/06-DEPLOY.md).

## Documentation

| | |
|---|---|
| [`docs/plan/00-STRATEGY.md`](docs/plan/00-STRATEGY.md) | mode, partner, user, scoring, honesty rules |
| [`docs/plan/01-ARCHITECTURE.md`](docs/plan/01-ARCHITECTURE.md) | components, data model, job queue, LLM switch, perimeter, human-in-the-loop |
| [`docs/plan/02-PIPELINE.md`](docs/plan/02-PIPELINE.md) | stages, rule catalogue, ratios, verifier spec |
| [`docs/plan/03-DATA.md`](docs/plan/03-DATA.md) | generator, ground truth, hard cases, metrics, recorded deviations |
| [`docs/plan/04-TASKS.md`](docs/plan/04-TASKS.md) | build plan and cut list |
| [`docs/plan/05-DEMO.md`](docs/plan/05-DEMO.md) | 7-minute defence script and jury-input contingencies |
| [`docs/plan/06-DEPLOY.md`](docs/plan/06-DEPLOY.md) | server, compose, nginx, CI, rollback |
| [`docs/plan/07-RISKS.md`](docs/plan/07-RISKS.md) | pre-mortem |
| [`docs/plan/08-BUSINESS.md`](docs/plan/08-BUSINESS.md) | pilot cost model, assumptions labelled |
| [`docs/plan/09-API.md`](docs/plan/09-API.md) | API contract |
| [`docs/EVAL.md`](docs/EVAL.md), [`docs/KNOWN-FAILURES.md`](docs/KNOWN-FAILURES.md) | evaluation results and known failures |
| [`ARCHITECTURE.md`](ARCHITECTURE.md), [`design/`](design/) | backend blueprint; UI design system and screens |
