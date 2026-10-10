# Evaluation results

> **Measured on our synthetic generator's test split and hand-made hard cases; overstates real-document accuracy; real-document evaluation is pilot month 1.**

Source: `eval/results/2026-10-10_1834_283cd8d.json` · generated 2026-10-10T18:34:53+05:00 · git `283cd8d-dirty`  
Dataset: synthetic test split: 40 bundles (b0160–b0199), 275 documents; hard cases: 20  
Pipeline functions called directly (no database, LLM off). Borrower STIR and application date are given as known to the bank. Definitions: eval/metrics.py and docs/EVAL.md.

Regenerate: `uv run python -m eval.run --split test` then `uv run python -m eval.report`. Definitions: `eval/metrics.py`; failure list: [KNOWN-FAILURES.md](KNOWN-FAILURES.md).

## Notes on this run

- First test-split run (eval/results/superseded/2026-10-10_1824_283cd8d.json) exposed a gap that the dev split shows too: Uzbek-Cyrillic opening/closing balance labels on layout-B statements were not read, so month-end balances were missing for those statements. Fixed (transliteration before matching), checked on dev and train (100% month-end balances there), categoriser retrained on the regenerated train split, then this run. Nothing was tuned on the test split or the hard cases.
- The extraction stage (track D1) may still be landing column and period fixes for scanned forms; the Form 1 / Form 2 figures for scans in this run reflect the code at git 283cd8d plus uncommitted changes (-dirty).
- Hard case H13 (loan repaid to a microfinance organisation under an abbreviation) fails: the abbreviated purpose ('Kr. qayt. sh.') is not categorised as a loan repayment. It is a test-only case and was deliberately not patched.

## Headline

| metric | value |
|---|---:|
| Form 1 field F1 | 0.9443 |
| Form 2 field F1 | 0.9495 |
| Loan application field F1 | 0.914 |
| Wrong values shown without a low-confidence flag | 196 |
| Document type accuracy | 0.9964 |
| Contradiction detection precision (micro) | 0.6029 |
| Contradiction detection recall (micro) | 0.7736 |
| Categoriser accuracy (production: rules then model) | 0.9903 |
| Categoriser macro-F1 (production) | 0.9597 |
| Recurring payment detection precision | 0.9872 |
| Recurring payment detection recall | 0.9585 |
| Template narratives passing the citation verifier | 40 of 40 |
| Hard cases passed | 18 of 20 |
| Latency p50 per document, laptop (ms) | 1 011 |
| Latency p95 per document, laptop (ms) | 31 348 |

## Field extraction (statutory forms and application form)

Unit = (document, line code, column). A wrong value counts as one FP and one FN; a *silent error* is a wrong value shown with confidence ≥ 0.80, i.e. without the "needs clarification" flag.

| doc type | variant | documents | cells | tp | fp | fn | precision | recall | f1 | silent errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| form1 | all | 80 | 5 023 | 4 634 | 158 | 389 | 0.967 | 0.9226 | 0.9443 | 128 |
| form1 | text layer | 43 | 2 699 | 2 699 | 0 | 0 | 1 | 1 | 1 | 0 |
| form1 | scan 300 dpi | 18 | 1 134 | 1 103 | 4 | 31 | 0.9964 | 0.9727 | 0.9844 | 1 |
| form1 | scan 150 dpi | 19 | 1 190 | 832 | 154 | 358 | 0.8438 | 0.6992 | 0.7647 | 127 |
| form2 | all | 80 | 2 616 | 2 443 | 87 | 173 | 0.9656 | 0.9339 | 0.9495 | 68 |
| form2 | text layer | 45 | 1 473 | 1 473 | 0 | 0 | 1 | 1 | 1 | 0 |
| form2 | scan 300 dpi | 9 | 292 | 261 | 21 | 31 | 0.9255 | 0.8938 | 0.9094 | 15 |
| form2 | scan 150 dpi | 16 | 523 | 433 | 49 | 90 | 0.8983 | 0.8279 | 0.8617 | 40 |
| form2 | phone photo | 10 | 328 | 276 | 17 | 52 | 0.942 | 0.8415 | 0.8889 | 13 |
| loan_application | all | 40 | 200 | 170 | 2 | 30 | 0.9884 | 0.85 | 0.914 | 0 |
| loan_application | text layer | 16 | 80 | 80 | 0 | 0 | 1 | 1 | 1 | 0 |
| loan_application | scan 300 dpi | 9 | 45 | 35 | 0 | 10 | 1 | 0.7778 | 0.875 | 0 |
| loan_application | scan 150 dpi | 6 | 30 | 21 | 1 | 9 | 0.9545 | 0.7 | 0.8077 | 0 |
| loan_application | phone photo | 9 | 45 | 34 | 1 | 11 | 0.9714 | 0.7556 | 0.85 | 0 |

By label language (Form 1 / Form 2):

| doc type | label language | documents | tp | fp | fn | precision | recall | f1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| form1 | ru | 28 | 1 557 | 55 | 204 | 0.9659 | 0.8842 | 0.9232 |
| form1 | uz_cyrl | 10 | 630 | 6 | 6 | 0.9906 | 0.9906 | 0.9906 |
| form1 | uz_latn | 42 | 2 447 | 97 | 179 | 0.9619 | 0.9318 | 0.9466 |
| form2 | ru | 28 | 872 | 22 | 36 | 0.9754 | 0.9604 | 0.9678 |
| form2 | uz_cyrl | 10 | 328 | 1 | 1 | 0.997 | 0.997 | 0.997 |
| form2 | uz_latn | 42 | 1 243 | 64 | 136 | 0.951 | 0.9014 | 0.9255 |

## Document type and period

| truth type | documents | correct | accuracy | most common error |
|---|---:|---:|---:|---|
| bank_statement | 40 | 39 | 0.975 | unknown ×1 |
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
| R01 | 7 | 8 | 7 | 1 | 0 | 0.875 | 1 | 0.9333 |
| R02 | 0 | 7 | 0 | 7 | 0 | 0 | — | — |
| R03 | 0 | 7 | 0 | 7 | 0 | 0 | — | — |
| R04 | 11 | 12 | 9 | 3 | 2 | 0.75 | 0.8182 | 0.7826 |
| R05 | 6 | 5 | 5 | 0 | 1 | 1 | 0.8333 | 0.9091 |
| R06 | 11 | 5 | 5 | 0 | 6 | 1 | 0.4545 | 0.625 |
| R07 | 7 | 6 | 4 | 2 | 3 | 0.6667 | 0.5714 | 0.6154 |
| R08 | 0 | 0 | 0 | 0 | 0 | — | — | — |
| R09 | 6 | 8 | 6 | 2 | 0 | 0.75 | 1 | 0.8571 |
| R10 | 5 | 6 | 5 | 1 | 0 | 0.8333 | 1 | 0.9091 |
| R11 | 0 | 4 | 0 | 4 | 0 | 0 | — | — |
| R12 | 0 | 0 | 0 | 0 | 0 | — | — | — |
| micro (all rules) | 53 | 68 | 41 | 27 | 12 | 0.6029 | 0.7736 | 0.6777 |

## Bank statements

| mode | rows | accuracy | macro f1 |
|---|---:|---:|---:|
| rules then model (production) | 16 175 | 0.9903 | 0.9597 |
| rules only | 16 175 | 0.987 | 0.951 |
| model only | 16 175 | 0.9909 | 0.9616 |

Most frequent categorisation errors (production mode):

| truth | predicted | rows |
|---|---|---:|
| supplier_payment | other | 147 |
| payroll_tax | tax | 9 |
| bank_fee | supplier_payment | 1 |

Recurring payments (group matched by statement rows, IoU ≥ 0.5):

| metric | value |
|---|---:|
| tp | 231 |
| fp | 3 |
| fn | 10 |
| precision | 0.9872 |
| recall | 0.9585 |
| f1 | 0.9726 |

Month-end balances:

| metric | value |
|---|---:|
| months | 320 |
| exact | 312 |
| accuracy | 0.975 |

## Latency per document (laptop)

| doc type | path | documents | p50 ms | p95 ms | max ms |
|---|---|---:|---:|---:|---:|
| bank_statement | XLSX | 40 | 286 | 491 | 681 |
| form1 | OCR (scanned PDF) | 37 | 24 771 | 55 057 | 58 753 |
| form1 | PDF text layer | 43 | 1 017 | 1 686 | 1 700 |
| form2 | OCR (photo/image) | 10 | 8 954 | 13 937 | 13 937 |
| form2 | OCR (scanned PDF) | 25 | 12 100 | 24 341 | 30 344 |
| form2 | PDF text layer | 45 | 661 | 878 | 1 012 |
| loan_application | OCR (photo/image) | 9 | 10 191 | 12 455 | 12 455 |
| loan_application | OCR (scanned PDF) | 15 | 13 259 | 15 116 | 15 116 |
| loan_application | PDF text layer | 16 | 508 | 813 | 813 |
| tax_declaration | OCR (photo/image) | 3 | 6 320 | 6 829 | 6 829 |
| tax_declaration | OCR (scanned PDF) | 15 | 8 241 | 11 759 | 11 759 |
| tax_declaration | PDF text layer | 17 | 390 | 549 | 549 |
| all documents | all | 275 | 1 011 | 31 348 | 58 753 |

| metric | value |
|---|---|
| machine | Linux x86_64 |
| cpu_threads | 12 |
| parallel_workers | 6 |
| omp_thread_limit | 1 |
| wall_clock_s | 384.8 |
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
| H19 | 640x480 blurred phone photo | failed with cause (resolution, blur score) + whatever text was read | pass | failure cause: Could not analyse reliably: the image is 640×480 px (minimum 900 px on the short side); it is blurred (sharpness 1, minimum 50); text recognition confidence is 38% (minimum 60%). Amounts may be unreadable. Re-upload a sharper scan (≥ 200 dpi) or enter the values manually.; facts 0 |
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
