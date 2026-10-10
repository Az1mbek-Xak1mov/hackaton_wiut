# 00 — Strategy

Team **10x engineers** · Product **Converza** · Repo `converza` · Site https://converza.uz · Project language: English.
Planned 2026-10-10 17:00 (Asia/Tashkent, UTC+5). All times in this plan are UTC+5.

## Timebox (one-day hackathon)

| Milestone | Time | Meaning |
|---|---|---|
| Plan accepted, build starts | 2026-10-10 17:15 | tracks claim tasks in `04-TASKS.md` |
| M1 live skeleton (HTTPS, CI deploy) | 18:30 | |
| M2 document → evidence (jury path works) | 20:00 | a legitimate live demo on its own |
| M3 loan file review (fully from the pipeline) | 21:30 | lead surface done |
| M4 monitoring + AI CFO + metrics | 22:30 | **feature freeze** |
| **Code freeze**: last deploy, tag `v1.0` | **23:15** | after this, only presentation work |
| Submission (deadline assumed at the earliest edge of the 7–8 h window) | **2026-10-11 00:00** | repo + URL + deck + video |
| Defence (7 min) | date/time set by the organisers | not given at planning time; 05-DEMO is time-independent |

`docs/BRIEF.md` was not in the repo at planning time. The criteria below come from the brief summary in the planning prompt. If the brief's wording differs, update the criteria table and leave the plan as it is.

## Product

| | |
|---|---|
| Mode | Partner product |
| Partner | MKBANK, SME Lending Department. Co-partner: Central Bank of Uzbekistan (explainability, audit, human-in-the-loop) |
| Primary user | SME loan officer (application review and post-disbursement monitoring) |
| Secondary user | SME owner, through the AI CFO. Framed as the **data channel** that feeds continuous monitoring |
| Process changed | (1) loan-file preparation: documents → verified figures → contradictions → ratios → narrative. (2) monitoring: monthly statements → indicators → status with reasons |
| One sentence | **Converza is a document-to-evidence engine for Uzbek SME financials: every number can be clicked back to the page it came from, and the model is not allowed to state a number that isn't in the records.** |
| Not | a credit score, an approval engine, or a chatbot over PDFs |

## Two surfaces, one engine

```mermaid
flowchart LR
  subgraph Inputs
    J[Jury / any user<br>/analyse]:::pub
    O[Owner uploads<br>/owner]:::own
    B[Officer attaches<br>application bundle]:::bank
  end
  J & O & B --> E[Converza engine<br>classify → parse → extract → normalise → reconcile → ratios → grounded text]
  E --> F[(facts store<br>every value has doc·page·bbox)]
  F --> L[Loan review<br>/bank/applications/:id]:::bank
  F --> M[Monitoring<br>/bank/borrowers]:::bank
  F --> C[AI CFO<br>/owner/cfo]:::own
  classDef pub fill:#E6ECF7; classDef own fill:#E8F1EF; classDef bank fill:#FBEFD9
```

## How we score

| Criterion (weight) | What the jury must see | Where in the demo | Proof artefact |
|---|---|---|---|
| Technology: complexity (25%) | Multi-stage pipeline with real OCR across 4 scripts/languages, line-code dictionary, statement categoriser trained on our labelled set, 10 reconciliation rules, a citation verifier that rejects the LLM, a Postgres job queue | live upload of the jury's file; "LLM off" toggle; rejected-generation log | `02-PIPELINE.md`, `/metrics` page, `docs/EVAL.md` |
| Technology: originality (25%) | (1) Number-level provenance: chip → page image with bbox. (2) **The model cannot do arithmetic.** It calls `compute`, which registers a citable derived fact. (3) Verifier: any number in generated text that is not in the fact set means regenerate, then fall back to a template. (4) Uzbek statutory line-code dictionary in UZ-Latin, UZ-Cyrillic and RU | click a number in the narrative; show a rejected draft in the audit trail | `narrative_runs` rows with `verifier_report` |
| Problem / user fit (inferred from the defence's "problem/user" minute) | officer workflow, 10-working-day baseline (assumed, to be confirmed with MKBANK) | minute 0–1 | `08-BUSINESS.md` |
| Business viability / budget (inferred from "budget/ROI" 1.5 min) | pilot cost, cost per application in UZS measured from real token logs, officer-minutes measured in a timed trial | minute 5–6.5 | `08-BUSINESS.md` |
| Partner integration / next steps (inferred) | on-prem path, local 7B model with the same prompts, CB audit requirements | minute 6.5–7 | `01-ARCHITECTURE.md` §Perimeter |

## Replication test: why a weekend clone doesn't get this

| Layer | Our asset | Why it is hard to copy |
|---|---|---|
| Data | Synthetic Uzbek SME bundle generator with ground truth (Форма 1/2 layouts, xlsx statements, applications, scan noise) + hand-made hard cases | the generator encodes statutory layouts, Uzbek/RU payment-purpose vocabulary and planted contradictions with labels |
| Domain | Line-code dictionary (codes ↔ UZ-Lat/UZ-Cyr/RU/EN labels ↔ sum relations); reconciliation rule library with tolerances (VAT-adjusted revenue ↔ inflows) | needs reading of real Форма 1/2 and Uzbek banking conventions (STIR, MFO, 20-digit accounts) |
| Pipeline | deterministic first, LLM only as validated fallback; provenance (page, bbox) kept through OCR; verifier | most "AI for credit" demos are one prompt over raw text, which cannot show page/line evidence |
| Integration | job queue in Postgres (no extra infra), on-prem compose, provider switch to a local model, audit log + officer decisions | fits a bank perimeter with no external calls (local-model path) |

## Honesty rules (binding; also in `CLAUDE.md`)

1. **No scripted outputs in the deployed demo.** Every figure, finding, status, ratio and AI sentence on screen is produced by the pipeline from uploaded files at runtime or at seed time. Seed = files pushed through the same pipeline, never SQL inserts of results.
2. **The demo dataset is synthetic and declared** on the prototype strip: "Synthetic demonstration documents. All figures are computed live from them." Loan-book attributes (loan amount, term, installment) are declared synthetic inputs.
3. **No invented metrics.** Every number on a slide comes from `eval/results/*.json`, `jobs` timings, `llm_calls` token logs or the timed trial. Each is stated with n and dataset ("synthetic test split, n=…"). Any metric not yet run says "not measured".
4. **No numeric credit score anywhere.** Status = Stable / Watch / Attention from disclosed rules, labelled "Thresholds are illustrative; calibration against bank history is pilot month 1".
5. **The system never approves or rejects.** The officer's decision is recorded with the evidence reviewed.
6. **Assumptions are labelled at the point of use**: 10-working-day baseline, 50 applications/month, officer-hour cost, FX rate, token prices.
7. **Synthetic-on-synthetic caveat** goes on the metrics slide: "measured on our generator's test split and hard cases, which overstates real-document accuracy; real-document evaluation is pilot month 1".
8. **Known-failure-cases list** (`docs/KNOWN-FAILURES.md`) is shipped and linked from `/metrics`.

## Scope decisions forced by the timebox and server

| Decision | Reason |
|---|---|
| Local 7B model: **documented, not live** | server 159.195.213.245 has no GPU, 4 vCPU, 7.8 GiB RAM shared with 4 production apps. Live demo uses OpenAI (`LLM_PROVIDER=openai`); the switch and the ollama client are implemented and unit-tested against a fake |
| OCR = Tesseract only (PaddleOCR dropped) | image size and RAM; Tesseract has `uzb`, `uzb_cyrl`, `rus`, `eng` Debian packages |
| UI language EN; UZ/RU switch renders but is cut-list item #2 | project language is English; documents stay UZ/RU |
| Owner Health page and phone layout are cut-list items | jury weight sits on the officer surface |
| Generator scale 200 bundles, eval on the test split (40) + hard cases | generation is cheap; OCR eval time on 4 cores is the limit |
