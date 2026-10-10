# 02 — Pipeline

Code in `app/pipeline/` (pure functions, no DB). The `jobs` runner in `app/modules/jobs/runner.py` persists each stage's output. Common internal type:

```python
Word = (text, x0, y0, x1, y1, conf)   # conf = 1.0 for text layer
Row  = (page_n, y, words[])           # words clustered by y-centre, tolerance 0.45 × median word height
```

## Stage overview

| # | Stage | Input → Output | Method / libs | Measured |
|---|---|---|---|---|
| 1 | Classify | file → `doc_type`, `type_confidence`, `language` | magic bytes; first-page text keyword scoring | type accuracy (eval) |
| 2 | Parse | file → `pages[]` with `words`, page PNG | pdfplumber / Tesseract / openpyxl | p50/p95 ms per page; OCR mean conf |
| 3 | Statutory extraction | Form 1/2 rows → `facts(kind=extracted)` | line-code dictionary + rapidfuzz; LLM fallback for unmapped rows | field P/R per doc type |
| 4 | Statement normalisation | xlsx → `transactions` | header detection, regex, rules + TF-IDF/LR, recurrence | categoriser accuracy, macro-F1; recurring P/R |
| 5 | Reconciliation | facts + transactions → `findings` | rule library R01–R12 | contradiction P/R per rule |
| 6 | Ratios + monitoring | facts → `facts(kind=computed)`, `monitoring_results` | deterministic formulas, disclosed thresholds | unit-tested exact |
| 7 | Grounded narrative | fact JSON → text with cites | LLM + citation verifier + template fallback | acceptance rate; regenerations; tokens |
| 8 | AI CFO Q&A | question → answer with cites | tool calls over the facts store + the same verifier | same as 7 |

## 1. Classification

| Item | Spec |
|---|---|
| Input | original bytes, filename |
| Routing | `%PDF` → has a text layer if pdfplumber yields ≥ 40 chars/page on page 1, else scan; `PK` + `xl/` → xlsx; JPEG/PNG → image; anything else → `unknown` + "unsupported format" |
| Scoring | normalise text (NFKC, lowercase, `ʻ ' ‘ ’ ʼ` → `'`, Cyrillic/Latin homoglyph fold for matching only). Weighted keywords per type, e.g. form1: `бухгалтерский баланс`, `buxgalteriya balansi`, `бухгалтерия баланси`, line codes `400` + `770` present; form2: `отчет о финансовых результатах`, `moliyaviy natijalar to'g'risida hisobot`, codes `010` + `270`; bank_statement: `выписка`, `ko'chirma`, header has date + debit/credit columns; loan_application: `заявка на кредит`, `kredit olish uchun ariza`; tax_declaration, invoice (`счет-фактура`, `hisob-faktura`) and sales_ledger are **recognised only** |
| Decision | top score ≥ 3.0 and ≥ 1.5× the runner-up → type; else `unknown` |
| Language | char-script ratio (Cyrillic vs Latin) + Uzbek-specific letters (`ў қ ғ ҳ`, `o' g'`) → uz_cyrl / uz_latn / ru / en / mixed |
| Failure modes | multilingual cover page; a statement exported as PDF |
| Fallback | `unknown` still runs stage 2 and returns the "what I could read" summary (see §Unknown documents) |

## 2. Parsing

| Path | Method | Failure modes | Fallback |
|---|---|---|---|
| Text PDF | `pdfplumber.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])`; page PNG via `pypdfium2` at 150 dpi | ligature/encoding garbage (CID fonts) → < 60% dictionary hits | re-route the page to OCR |
| Scan PDF / image | render 300 dpi → OpenCV: grayscale, deskew (Hough on text lines, ±15°; 90° rotations via `tesseract --psm 0` OSD), Otsu binarise, upscale ×2 if source < 200 dpi → `pytesseract.image_to_data(lang="uzb+uzb_cyrl+rus+eng", config="--psm 6 --oem 1")` | blur, low resolution, stamps over numbers, perspective (phone photo) | quality gate: `blur_score` = variance of Laplacian < 80, or mean conf < 55, or short side < 900 px → document `failed` with a human cause + exits (Re-upload / Enter manually), **but still return the text we read** |
| Digit pass | second Tesseract pass on numeric column crops with `tessedit_char_whitelist=0123456789()-., ` | — | keep the higher-conf reading per cell |
| XLSX | `openpyxl` read-only, values not formulas (`data_only=True`); header row = first row with ≥ 3 of {date, debit, credit, purpose, counterparty} synonyms | merged headers; several sheets | scan the first 30 rows of each sheet; choose the best header score |
| Tables | rows from y-clustering; columns from x-gaps (gap > 2.5 × median char width); numeric cell regex `^\(?-?\d{1,3}([  .]\d{3})*([.,]\d+)?\)?$` | merged/wrapped labels | a label that wraps to 2 lines is joined if the next row has no code and no number |
| Budget | public job: max 10 pages OCR'd; deadline 55 s | | partial result with `summary.partial=true` |

## 3. Statutory-form extraction

### Line-code dictionary: `app/pipeline/dictionary/forms.yaml`

Scope v1: **Form 1 (balance sheet) 26 lines, Form 2 (financial results) 19 lines**. Source: the current templates published on lex.uz. T-010 records the exact source document and revision in the YAML header. The codes used by the design are in scope and must match: Form 1 `140, 390, 400, 490, 600`; Form 2 `010, 020, 030, 040, 120, 240, 270`. If the official template's meaning for a code differs from the design label, the dictionary wins, and the UI label comes from the dictionary.

```yaml
- form: form1
  code: "390"
  field: current_assets_total
  labels:
    uz_latn: ["II bo'lim bo'yicha jami", "Joriy aktivlar jami"]
    uz_cyrl: ["II бўлим бўйича жами"]
    ru: ["Итого по разделу II", "Итого текущие активы"]
    en: ["Total current assets"]
  sum_of: ["140", "210", "320", ...]   # completed from the official template in T-010
  sign: +1
```

### Algorithm

| Step | Detail |
|---|---|
| Code column | in each row, a token matching `^\d{3}$` in the leftmost 45% of the page that ≥ 60% of rows share by x (±12 pt) |
| Value columns | the two right-most numeric columns. Header text decides current vs prior (`на конец`, `hisobot davri oxiri`, `отчетный период` → cur; `на начало`, `o'tgan yil` → prev); default right-most = cur |
| Match | (a) code exact + label fuzzy ≥ 70 (`rapidfuzz.token_set_ratio` over all languages) → `dictionary`, conf 0.99; (b) code exact, label < 70 → conf 0.90; (c) no code, label ≥ 88 → `fuzzy`, conf 0.85; (d) unmapped row with a number → LLM fallback |
| LLM fallback | input: row label text + candidate dictionary entries (top 5 by fuzzy). Output must match the JSON schema `{code: one of candidates or null, reason}`. Accepted only if the code is not already taken and the sum check (step "Arithmetic") still holds; conf 0.75. LLM off → row stays unmapped and is listed under "Unmapped lines" |
| Units | header text `тыс. сум`, `ming so'm` → kUZS; `млн` → ×1000; default kUZS (flagged neutral if no unit text found) |
| Negatives | `(1 234)` and `-1 234` → negative |
| Arithmetic | the dictionary `sum_of` relations are evaluated; a mismatch > 1 kUZS lowers conf by 0.15 for the parent and children and emits R02/R03 |
| OCR conf | final conf = min(match conf, mean Tesseract conf of the value's words / 100 + 0.1) |
| Period | from the header: `на 31.12.2025`, `2026 yil 1 yanvardan 30 iyungacha` → dates; H1 / FY labels derived |
| STIR | `\b[2-7]\d{8}\b` near `ИНН`, `STIR`, `СТИР` |

### Confidence → UI
`≥ 0.95` no pill · `0.80–0.95` neutral pill with the reason · `< 0.80` watch pill "needs clarification" (H1) · contradiction from a rule → attn pill "Contradicts statement".

### Unknown documents ("always return something true")
Output, LLM on or off: detected type + reason ("no statutory line codes found; top keyword score 1.2"), language, page count, OCR quality numbers, up to 30 detected numeric values with their row label and page (each is an evidence chip), dates, STIRs, accounts. With LLM on: a ≤ 3-sentence description generated from that JSON only, passed through the verifier. English IFRS-style statements: dictionary `en` labels match without codes → `fuzzy` facts labelled "non-statutory layout, matched by label".

## 4. Bank-statement normalisation

| Step | Method |
|---|---|
| Columns | header synonyms (RU/UZ/EN) → date, doc_no, debit, credit, counterparty, counterparty_stir, account, mfo, purpose |
| Amount | credit − debit; UZS; reject rows with neither |
| Counterparty | STIR `\b[2-7]\d{8}\b`; account `\b\d{20}\b`; MFO `\b\d{5}\b` after `МФО`/`MFO`; name = column, else the text before the STIR |
| Categories | `sales_receipt, supplier_payment, salary, payroll_tax, tax, loan_repayment, loan_disbursement, rent_utilities, own_transfer, cash_withdrawal, bank_fee, other` |
| Rules (first) | ordered regex list `app/pipeline/statements/rules.yaml`, e.g. `заработн\|ish haqi\|oylik` → salary; `погашение (основного долга\|кредита)\|kredit(ni)? qaytarish\|asosiy qarz` → loan_repayment; `проценты по кредиту\|foiz` → loan_repayment(interest); `НДС\|QQS\|налог\|soliq\|ИНПС` → tax; `аренд\|ijara` → rent_utilities; `комиссия банка\|bank xizmati` → bank_fee; counterparty STIR = own STIR → own_transfer. Rule conf 0.98 |
| Model (second) | TF-IDF char 2–5-grams over the normalised purpose + direction sign token → `LogisticRegression(C=4, class_weight="balanced")`, trained on the generator **train split** (`eval/train_categoriser.py` → `app/pipeline/statements/model.joblib`, committed with the metrics JSON). Used when no rule fires; prob < 0.6 → `other` + counted as "uncategorised" (clarification card) |
| Recurring | group outflows by (counterparty_stir or normalised name, category); recurring if ≥ 3 occurrences, day-of-month std ≤ 3, amount CV ≤ 0.15 → `recurring_group`, next expected date and amount (feeds upcoming obligations) |
| Loan detection | recurring `loan_repayment` group → aggregate fact `statement.loan_repayment.monthly` with contract no. parsed `№\s?([\d\-/]+)` and first-payment date |
| Aggregates | monthly inflow by category, monthly outflow, end-of-month balance (from the balance column, else cumulative + opening) → `facts(kind=aggregate)` whose evidence = row range |

Failure modes: a bank-specific layout (two-row headers), purpose text truncated, foreign currency. Fallback: unparsed rows are counted and shown; never silently dropped.

## 5. Reconciliation rule catalogue (`app/pipeline/rules/`)

Every rule is a function `(facts, txns, ctx) -> list[Finding]`. Titles and details are templates filled only from fact values. Each finding cites the fact keys it used.

| id | Inputs | Check | Tolerance | Severity | Evidence emitted |
|---|---|---|---|---|---|
| R01 | F1 400, 770 (assets / liabilities+equity totals) | equal | ≤ 1 kUZS | attn | both totals |
| R02 | F1 section children / totals (`sum_of`) | Σ children = total | ≤ 1 kUZS | watch | total + children |
| R03 | F2 010−020=030; chain to 270 | arithmetic chain | ≤ 1 kUZS | watch | the lines involved |
| R04 | F2 270 (period) vs Δ F1 retained earnings (prev→cur) | Δ RE ≈ net profit | ±5% or ±10 000 kUZS (dividends not visible) | watch | 270, RE cur, RE prev |
| R05 | F2 010 vs Σ `sales_receipt` inflows over the overlapping months | inflows / 1.12 (VAT 12%) ÷ revenue ∈ [0.85, 1.20] | band | watch (attn if < 0.70) | 010 + aggregate inflow fact |
| R06 | F1 490 long-term + application "existing debts" vs detected recurring `loan_repayment` groups not matching a declared contract | undeclared recurring loan | ≥ 3 payments | **attn** "Undeclared obligation" | 490 fact, loan aggregate, application field |
| R07 | application form "revenue last FY" vs F2 010 FY | equal | ≤ 2% | watch "Contradiction" | both |
| R08 | all document periods vs application date | statements cover ≥ 6 of the last 8 months; forms are the latest FY and the latest half-year | — | neutral "Period gap" | document facts |
| R09 | STIR on every document | all equal to the borrower STIR | exact | attn | STIR facts |
| R10 | required document set (application, F1 ×2, F2 ×2, statement, tax declaration) | present | — | neutral "Missing document" | none (names the type) |
| R11 | H1 vs FY revenue | H1 ÷ (FY/2) ∈ [0.5, 1.6] | band | info | both |
| R12 | sha256 duplicates; same period uploaded twice with different values | duplicate / conflicting | — | watch | both documents |

Monitoring indicators (`M*`, run per borrower per period; thresholds disclosed in the UI side nav):

| id | Indicator | Triggered when | Source |
|---|---|---|---|
| M01 | Revenue vs prior period | ≤ −15% | F2 010 or monthly sales_receipt aggregates |
| M02 | Receivables growth vs sales | receivables +25% while revenue ≤ 0% | F1 receivables line |
| M03 | Payables growth | +40% over two periods | F1 payables line |
| M04 | Cash coverage of next installment | month-end cash ÷ installment < 1.5× | statement balance fact ÷ loan installment |
| M05 | Payment punctuality | any installment > 0 days late in the last 3 | repayments / statement match |
| M06 | Statement timeliness | latest statement > 10 days past the covenant date | documents |

Status: **Stable** = none triggered in the last 2 periods · **Watch** = exactly one triggered, or M06 · **Attention** = two or more, or M05. Label: "Illustrative thresholds; calibration against bank history is pilot month 1."

## 6. Ratios (`facts kind=computed`, formula and inputs stored)

| Ratio | Formula |
|---|---|
| Current ratio | F1 390 / F1 600 |
| Quick ratio | (F1 390 − F1 140) / F1 600 |
| Net margin | F2 270 / F2 010 |
| Debt to equity | (F1 490 + F1 600) / F1 equity total |
| Est. DSCR (new loan) | ((F2 270 + F2 120) / months_in_period) / requested installment |
| Est. DSCR (incl. undeclared) | same ÷ (installment + detected undeclared monthly) |
| Receivable days | F1 receivables / F2 010 × days_in_period |
| Installment vs revenue | installment / avg monthly sales_receipt inflows |

Annuity installment = `P·r/(1−(1+r)^−n)` with the rate from the application (declared input).

## 7. Grounded narrative + citation verifier

**Fact set sent to the LLM**: `[{id:"f_7k2m9q", label:"Net revenue FY2025", value:9842316, unit:"kUZS", display:"9 842.3 mln UZS"}, …]` + findings `[{id:"R06-1", severity, title, evidence:[ids]}]`. No raw document text. Borrower name/STIR are redacted when `LLM_REDACT=true`.

**Prompt contract** (`prompts/narrative.md`): 3 paragraphs (repayment capacity, issues, before a decision); every sentence that contains a number ends with `[f_…]` cites; numbers are copied from `display` or `value`; no new arithmetic (if needed, it must already be a computed fact); no recommendation to approve or reject; no score.

**Verifier** (`app/pipeline/verify.py`), deterministic:

| Step | Rule |
|---|---|
| Tokenise numbers | regex for `−`/`-`, space or NBSP thousands, `,`/`.` decimals, `%`, `×`, `mln`, `bn`, `thousand`; dates and years parsed separately |
| Allowed set | each fact value rendered in kUZS, mln (÷1000), bn (÷1e6); pct ×100; with tolerance = half a unit of the last printed digit |
| Whitelist | years appearing in any fact's period; line codes of cited facts; list ordinals at line start |
| Citation | every sentence containing a non-whitelisted number cites ≥ 1 id, and that number matches a value of a **cited** fact (not just any fact) |
| Unknown ids | any `[f_x]` not in the set → reject |
| Forbidden | regex for `approve`, `reject`, `score`, `rating` (EN/RU/UZ) → reject |
| Result | `{ok, numbers:[{text, value, matched_fact}], unmatched:[…], uncited_sentences:[…], unknown_ids:[…]}` |
| On reject | regenerate with the report appended as feedback ("These numbers are not in the facts: …"), max 3 attempts; then **template fallback** (`mode=template`) assembled from findings and ratios, labelled "Template summary — AI draft rejected by the verifier" |

Measured: acceptance at attempt 1/2/3, template rate, tokens, latency. Every attempt is stored in `narrative_runs` and visible in the review trail.

## 8. AI CFO Q&A

Tool loop (max 6 tool calls, 20 s budget), same provider abstraction:

| Tool | Returns |
|---|---|
| `search_facts(query, period?)` | matching facts (id, label, value, display) |
| `sum_transactions(period, category?, counterparty?, direction?)` | registers an `aggregate` fact, returns its id and value |
| `cash_balance_series(from, to)` | month-end balance facts |
| `upcoming_obligations(days)` | recurring groups → expected payments (aggregate facts) |
| `compute(expression, inputs:[ids])` | safe arithmetic (`+ − × ÷`, parentheses) over fact values; registers a `computed` fact with its formula; **the only way the model gets a new number** |
| `missing_data(topic)` | which document types would answer it, for the "What I can't see" box |

Final answer JSON schema `{direct_answer, table?:[{label, fact_id}], cant_see?, next_steps:[…]}` → verifier → render. Rejected twice → "I can't answer that from the records" + the matching facts.
