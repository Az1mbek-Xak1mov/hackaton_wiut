# Evaluation results

> **Measured on our synthetic generator's test split and hand-made hard cases; overstates real-document accuracy; real-document evaluation is pilot month 1.**

Source: `eval/results/2026-10-10_2042_cd93dff.json` · generated 2026-10-10T20:42:56+05:00 · git `cd93dff-dirty`  
Dataset: synthetic test split: 40 bundles (b0160–b0199), 275 documents; hard cases: 20  
Pipeline functions called directly (no database, LLM off). Borrower STIR and application date are given as known to the bank. Definitions: eval/metrics.py and docs/EVAL.md.

Regenerate: `uv run python -m eval.run --split test` then `uv run python -m eval.report`. Definitions: `eval/metrics.py`; failure list: [KNOWN-FAILURES.md](KNOWN-FAILURES.md).

## Notes on this run

- Previous run: eval/results/2026-10-10_1834_283cd8d.json. Changes since (extraction track D1): column headers lost by full-page OCR are re-read from an upscaled crop of the header band; small spurious value columns (OCR debris inside labels) are dropped; values whose current/prior order could not be confirmed are capped at confidence 0.80; layout-B Uzbek-Cyrillic statements are classified from title/header rows only; declared-debt lines of the application are extracted as facts; '(2025)' year prefixes and OCR unit spellings ('Tbic. cym', 'min so'm') in application amounts are handled. Tuned on dev and train only, never on test or hard cases.
- An intermediate run (eval/results/superseded/2026-10-10_2033_cd93dff.json) showed the application F1 dropping to 0.825 from a new colon-less label fallback that mistook the form number for the requested amount; fixed on dev before this run.
- Hard case H13 (loan repaid to a microfinance organisation under an abbreviation) still fails: the abbreviated purpose ('Kr. qayt. sh.') is not categorised as a loan repayment. It is test-only and deliberately not patched.

## Headline

| metric | value |
|---|---:|
| Form 1 field F1 | 0.9747 |
| Form 2 field F1 | 0.9756 |
| Loan application field F1 | 0.9485 |
| Wrong values shown without a low-confidence flag | 33 |
| Document type accuracy | 1 |
| Contradiction detection precision (micro) | 0.7143 |
| Contradiction detection recall (micro) | 0.9434 |
| Categoriser accuracy (production: rules then model) | 0.9904 |
| Categoriser macro-F1 (production) | 0.96 |
| Recurring payment detection precision | 0.9833 |
| Recurring payment detection recall | 0.9751 |
| Template narratives passing the citation verifier | 40 of 40 |
| Hard cases passed | 18 of 20 |
| Latency p50 per document, laptop (ms) | 672 |
| Latency p95 per document, laptop (ms) | 19 316 |

## Field extraction (statutory forms and application form)

Unit = (document, line code, column). A wrong value counts as one FP and one FN; a *silent error* is a wrong value shown with confidence ≥ 0.80, i.e. without the "needs clarification" flag.

| doc type | variant | documents | cells | tp | fp | fn | precision | recall | f1 | silent errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| form1 | all | 80 | 5 023 | 4 817 | 44 | 206 | 0.9909 | 0.959 | 0.9747 | 14 |
| form1 | text layer | 43 | 2 699 | 2 699 | 0 | 0 | 1 | 1 | 1 | 0 |
| form1 | scan 300 dpi | 18 | 1 134 | 1 103 | 4 | 31 | 0.9964 | 0.9727 | 0.9844 | 1 |
| form1 | scan 150 dpi | 19 | 1 190 | 1 015 | 40 | 175 | 0.9621 | 0.8529 | 0.9042 | 13 |
| form2 | all | 80 | 2 616 | 2 518 | 28 | 98 | 0.989 | 0.9625 | 0.9756 | 19 |
| form2 | text layer | 45 | 1 473 | 1 473 | 0 | 0 | 1 | 1 | 1 | 0 |
| form2 | scan 300 dpi | 9 | 292 | 292 | 0 | 0 | 1 | 1 | 1 | 0 |
| form2 | scan 150 dpi | 16 | 523 | 477 | 11 | 46 | 0.9775 | 0.912 | 0.9436 | 6 |
| form2 | phone photo | 10 | 328 | 276 | 17 | 52 | 0.942 | 0.8415 | 0.8889 | 13 |
| loan_application | all | 40 | 200 | 184 | 4 | 16 | 0.9787 | 0.92 | 0.9485 | 0 |
| loan_application | text layer | 16 | 80 | 80 | 0 | 0 | 1 | 1 | 1 | 0 |
| loan_application | scan 300 dpi | 9 | 45 | 42 | 1 | 3 | 0.9767 | 0.9333 | 0.9545 | 0 |
| loan_application | scan 150 dpi | 6 | 30 | 24 | 2 | 6 | 0.9231 | 0.8 | 0.8571 | 0 |
| loan_application | phone photo | 9 | 45 | 38 | 1 | 7 | 0.9744 | 0.8444 | 0.9048 | 0 |

By label language (Form 1 / Form 2):

| doc type | label language | documents | tp | fp | fn | precision | recall | f1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| form1 | ru | 28 | 1 648 | 13 | 113 | 0.9922 | 0.9358 | 0.9632 |
| form1 | uz_cyrl | 10 | 630 | 6 | 6 | 0.9906 | 0.9906 | 0.9906 |
| form1 | uz_latn | 42 | 2 539 | 25 | 87 | 0.9902 | 0.9669 | 0.9784 |
| form2 | ru | 28 | 903 | 1 | 5 | 0.9989 | 0.9945 | 0.9967 |
| form2 | uz_cyrl | 10 | 328 | 1 | 1 | 0.997 | 0.997 | 0.997 |
| form2 | uz_latn | 42 | 1 287 | 26 | 92 | 0.9802 | 0.9333 | 0.9562 |

## Document type and period

| truth type | documents | correct | accuracy | most common error |
|---|---:|---:|---:|---|
| bank_statement | 40 | 40 | 1 | — |
| form1 | 80 | 80 | 1 | — |
| form2 | 80 | 80 | 1 | — |
| loan_application | 40 | 40 | 1 | — |
| tax_declaration | 35 | 35 | 1 | — |

| doc type | documents | correct | accuracy |
|---|---:|---:|---:|
| bank_statement | 40 | 40 | 1 |
| form1 | 80 | 80 | 1 |
| form2 | 80 | 80 | 1 |

## Contradiction detection (rules R01–R12)

Unit = (bundle, rule). Planted = contradictions the generator put into the documents. A rule that fires on figures that were mis-extracted counts as a false positive.

| rule | planted | fired | tp | fp | fn | precision | recall | f1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R01 | 7 | 7 | 7 | 0 | 0 | 1 | 1 | 1 |
| R02 | 0 | 6 | 0 | 6 | 0 | 0 | — | — |
| R03 | 0 | 6 | 0 | 6 | 0 | 0 | — | — |
| R04 | 11 | 10 | 9 | 1 | 2 | 0.9 | 0.8182 | 0.8571 |
| R05 | 6 | 6 | 6 | 0 | 0 | 1 | 1 | 1 |
| R06 | 11 | 11 | 10 | 1 | 1 | 0.9091 | 0.9091 | 0.9091 |
| R07 | 7 | 9 | 7 | 2 | 0 | 0.7778 | 1 | 0.875 |
| R08 | 0 | 0 | 0 | 0 | 0 | — | — | — |
| R09 | 6 | 8 | 6 | 2 | 0 | 0.75 | 1 | 0.8571 |
| R10 | 5 | 5 | 5 | 0 | 0 | 1 | 1 | 1 |
| R11 | 0 | 2 | 0 | 2 | 0 | 0 | — | — |
| R12 | 0 | 0 | 0 | 0 | 0 | — | — | — |
| micro (all rules) | 53 | 70 | 50 | 20 | 3 | 0.7143 | 0.9434 | 0.813 |

## Bank statements

| mode | rows | accuracy | macro f1 |
|---|---:|---:|---:|
| rules then model (production) | 16 603 | 0.9904 | 0.96 |
| rules only | 16 603 | 0.9871 | 0.9515 |
| model only | 16 603 | 0.991 | 0.9619 |

Most frequent categorisation errors (production mode):

| truth | predicted | rows |
|---|---|---:|
| supplier_payment | other | 150 |
| payroll_tax | tax | 9 |
| bank_fee | supplier_payment | 1 |

Recurring payments (group matched by statement rows, IoU ≥ 0.5):

| metric | value |
|---|---:|
| tp | 235 |
| fp | 4 |
| fn | 6 |
| precision | 0.9833 |
| recall | 0.9751 |
| f1 | 0.9792 |

Month-end balances:

| metric | value |
|---|---:|
| months | 320 |
| exact | 320 |
| accuracy | 1 |

## Latency per document (laptop)

| doc type | path | documents | p50 ms | p95 ms | max ms |
|---|---|---:|---:|---:|---:|
| bank_statement | XLSX | 40 | 158 | 254 | 304 |
| form1 | OCR (scanned PDF) | 37 | 15 885 | 32 919 | 35 109 |
| form1 | PDF text layer | 43 | 671 | 1 212 | 1 521 |
| form2 | OCR (photo/image) | 10 | 5 790 | 6 904 | 6 904 |
| form2 | OCR (scanned PDF) | 25 | 7 033 | 16 005 | 16 262 |
| form2 | PDF text layer | 45 | 344 | 431 | 445 |
| loan_application | OCR (photo/image) | 9 | 5 871 | 6 558 | 6 558 |
| loan_application | OCR (scanned PDF) | 15 | 7 777 | 9 200 | 9 200 |
| loan_application | PDF text layer | 16 | 366 | 782 | 782 |
| tax_declaration | OCR (photo/image) | 3 | 3 821 | 3 884 | 3 884 |
| tax_declaration | OCR (scanned PDF) | 15 | 5 132 | 6 246 | 6 246 |
| tax_declaration | PDF text layer | 17 | 197 | 261 | 261 |
| all documents | all | 275 | 672 | 19 316 | 35 109 |

| metric | value |
|---|---|
| machine | Linux x86_64 |
| cpu_threads | 12 |
| parallel_workers | 6 |
| omp_thread_limit | 1 |
| wall_clock_s | 232.8 |
| note | laptop, documents processed in parallel; production latency comes from server job timings |

## Hard cases

| id | case | expected | result | observed |
|---|---|---|---|---|
| H01 | page rotated 90° | OSD fixes rotation; fields extracted | pass | type form2; field F1 1.0; silent errors 0 |
| H02 | official stamp over 2 value cells | low confidence -> clarification, never a wrong value | fail | field F1 0.8615; wrong values without a low-confidence flag: 1 |
| H03 | negatives in parentheses and with '-' mixed | correct signs on every negative line | pass | sign errors 0; field F1 1.0 |
| H04 | dot thousands separators (9.842.316) | parsed as integers | pass | type form2; field F1 1.0; silent errors 0 |
| H05 | units in mln UZS instead of thousands | unit detected from the header; values x1000 into kUZS | pass | type form2; field F1 1.0; silent errors 0 |
| H06 | prior-year column blank | prev missing with note 'cell blank'; no invented prior values | pass | values invented for the blank prior-year column: 0; recall 1.0 |
| H07 | rows out of order + 2 unofficial extra rows | codes mapped regardless of order; extra rows unmapped | pass | field F1 1.0; values for absent cells 0 |
| H08 | label typos and apostrophe variants o‘ oʻ o' | fuzzy label match still maps every line | pass | type form2; field F1 1.0; silent errors 0 |
| H09 | mixed Cyrillic/Latin homoglyphs in labels | homoglyph fold + match | pass | type form2; field F1 1.0; silent errors 0 |
| H10 | Form 1 split over 2 pages | continuous extraction across pages | pass | type form1; field F1 1.0; silent errors 0 |
| H11 | statement with USD rows | USD rows excluded from UZS aggregates, counted and shown | pass | UZS rows kept 35 of 35; foreign-currency rows kept in UZS aggregates 0 of 5 |
| H12 | purpose text truncated at 60 chars | model categorisation with lower confidence | pass | categoriser accuracy 1.0 on 234 rows |
| H13 | loan repaid to a microfinance org under an abbreviation | R06 still fires (undeclared recurring loan) | fail | rules fired: R10 |
| H14 | salaries paid via a card-project bank without the word 'salary' | categorised as salary | pass | salary rows categorised as salary: 6 of 6 |
| H15 | English IFRS balance sheet | non-statutory layout; matched by English label, lower confidence | pass | classified as form1; 36 values reported, 36 match a printed value, 0 do not; highest confidence 0.85 |
| H16 | password-protected PDF | failed: 'PDF is encrypted' (and nothing invented) | pass | failure cause: The PDF is encrypted (password-protected), so it cannot be read. Upload an unprotected copy. |
| H17 | empty / all-zero Form 2 | analyzed; only zero/dash cells; nothing invented | pass | non-zero values reported on an all-zero form: 0 |
| H18 | same file uploaded twice | R12 duplicate (same sha256) | pass | rules fired: R10, R12 |
| H19 | 640x480 blurred phone photo | failed with cause (resolution, blur score) + whatever text was read | pass | failure cause: Could not analyse reliably: the image is 640×480 px (minimum 900 px on the short side); it is blurred (sharpness 1, minimum 25); text recognition confidence is 38% (minimum 60%). Amounts may be unreadable. Re-upload a sharper scan (≥ 200 dpi) or enter the values manually.; facts 0 |
| H20 | a Word letter saved as PDF (no figures) | unknown + 'what I could read'; no numbers invented | pass | classified as unknown; facts 0 |

Field extraction on hard-case forms:

| doc type | variant | documents | cells | tp | fp | fn | precision | recall | f1 | silent errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| form1 | all | 1 | 64 | 64 | 0 | 0 | 1 | 1 | 1 | 0 |
| form2 | all | 11 | 318 | 314 | 5 | 4 | 0.9843 | 0.9874 | 0.9859 | 1 |

## Not measured in this run

- LLM narrative acceptance and token cost: this run uses the LLM off (template narrative); cost per application in UZS comes from production llm_calls
- Production latency: added from server job timings
- Real-document accuracy: pilot month 1 on anonymised bank files

## LLM tokens and cost (outside this run)

Measured separately on production `llm_calls` (2026-10-10 21:55, recorded in commit `a9e5ee8`; no JSON export in the repo): loan narrative 2.5 attempts × 4 025 input / 422 output tokens (n = 4 generations, 10 calls); borrower explanation 736 / 181 tokens per call (n = 120 calls). At the assumed list price and FX this is 71 UZS per application. Derivation and assumptions: [`docs/plan/08-BUSINESS.md`](plan/08-BUSINESS.md). What is sent to the provider: [`docs/DATA-SOURCES.md`](DATA-SOURCES.md).
