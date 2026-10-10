# 09 — API contract (frontend ↔ backend)

Base `/api/v1`, JSON snake_case, errors per blueprint `{code, i18n_key, params, message}`. Money values are numbers in **kUZS** (thousand UZS, as printed in the statutory forms). Each fact has a `display` string pre-formatted by the backend (`"9 842.3"` mln UZS, 1 decimal, space thousands; true minus `−`). The frontend shows `display` and never formats or computes figures. `pct` facts hold percent values (`6.0` → `"6.0%"`). Period labels: flows `FY2025`, `H1-2026`, `Q3-2026`, `2026-09`; balance-sheet points `2025-12-31`.

## Shared shapes

```ts
type Fact = {
  key: string; uuid: string; field: string; label: string;
  value: number; unit: "kUZS"|"UZS"|"ratio"|"pct"|"days"|"count";
  display: string;            // "9 842.3" | "1.48" | "6.0%" | "31"
  display_unit: string;       // "mln UZS" | "" | "days"
  printed: string;            // "9 842 316" (Mono)
  period_label: string; line_code: string|null;
  kind: "extracted"|"computed"|"aggregate";
  page_n: number|null; bbox: [number,number,number,number]|null;
  page_width: number|null; page_height: number|null;   // coordinate space of bbox
  page_image_url: string|null;                          // /api/v1/documents/{uuid}/pages/{n}.png
  passage: string; confidence: number; method: string;
  formula: string; inputs: string[]; note: string;
  status: "auto"|"verified"|"corrected"|"flagged";
  document: {uuid: string; filename: string; doc_type: string} | null;
};
type Finding = { uuid: string; rule_id: string; severity: "attn"|"watch"|"neutral"|"info";
  label: string; title: string; detail: string; evidence: string[]; state: "open"|"resolved"|"dismissed" };
type DocumentOut = { uuid: string; filename: string; mime: string; size_bytes: number; doc_type: string;
  type_confidence: number; type_reason: string; language: string; status: "queued"|"processing"|"analyzed"|"clarification"|"failed";
  failure_cause: string; period_start: string|null; period_end: string|null; page_count: number; text_layer: boolean;
  summary: Record<string, any>; created_at: string };
type Job = { uuid: string; kind: string; status: "queued"|"running"|"done"|"failed"; stage: string; progress: number;
  error: string; stage_timings: Record<string, number> };   // stage names: parse, readable, extract, normalise, reconcile, describe
// DocumentOut also has owner_kind and stir; Finding also has state_note.
```

`GET /facts?keys=a,b,c` returns `{facts: Fact[]}` (signed-in users with read access; anonymous callers get only facts of public /analyse documents). Evidence chips carry a fact key; the evidence store fetches missing keys in batches.

Page images of bank/owner documents need auth: `<img>` cannot send headers, so append `?token=<access token>` (also accepted on `/documents/{uuid}/original`). Public documents need nothing. `GET /jobs/{uuid}` returns `Job` (no auth; poll it or `/analyse/{uuid}`).

## Auth — two apps, two surfaces

`converza.uz` = business-owner app (surface `owner`); `app.converza.uz` = bank-officer app (surface `bank`). No demo logins.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/auth/register` (public) | JSON `{email, password (8–128), full_name, company_name, stir? ("302447118" or "302 447 118"; blank = none), industry?, region?}` | `201 TokenPair` (surface `owner`). `409 email_taken` / `409 stir_taken`, `422` on validation |
| POST | `/auth/login?surface=owner\|bank` (default `owner`) | **form** `username=<email>&password=…` (OAuth2 form, `application/x-www-form-urlencoded`) | `TokenPair`. `401 invalid_credentials`; `403 wrong_surface` with `message` "This is a business-owner account; sign in at converza.uz" / "This is a bank officer account; sign in at app.converza.uz" and `params:{surface, role}` |
| POST | `/auth/refresh` | `{refresh_token}` | `TokenPair` on the same surface |
| GET | `/auth/me` | — | `{user, scopes}` |

`TokenPair = {access_token, refresh_token, token_type:"bearer", expires_in, user:{uuid, email, full_name, role, is_active}, scopes:[…], surface:"owner"|"bank"}`. Surface `owner` accepts role `owner`; `bank` accepts `officer`, `admin`, `demo_viewer`. Owner tokens carry no bank scopes, so every officer endpoint answers 403 to them (and owner endpoints answer 403 to officers). Seeded accounts: `owner@converza.uz` (business Farovon Savdo MChJ, STIR 302447118; password `SEED_OWNER_PASSWORD`) and `officer@converza.uz` (G. Abdullayeva; `SEED_OFFICER_PASSWORD`).

## Public

| Method | Path | Response |
|---|---|---|
| GET | `/version` | `{git_sha, built_at, deployed_at, llm_provider, llm_enabled}` |
| POST | `/analyse` multipart `file` | `201 {uuid, job}` |
| GET | `/analyse/{uuid}` | `{document: DocumentOut, job: Job\|null, partial: boolean, facts: Fact[] (extracted + derived facts cited by findings — filter on kind), unmapped: [{page_n, text, value_printed, bbox}], findings: Finding[], transactions_preview: null \| {count, unit:"mln UZS", by_category:[{category, count, inflow_display, outflow_display}], recurring:[{group, label, count, amount_display, day_of_month, evidence:[fact key]}]}, readable: null \| {pages, language, ocr_mean_conf, numbers:[{text, label, page_n, bbox}], dates:[string], stirs:[string], text_excerpt: string} (shape owned by app/pipeline/readable.py), description: {text, mode:"llm"|"none"} }`. Unsupported formats come back at once with `document.status="failed"` and a `failure_cause`. |
| GET | `/documents/{uuid}/pages/{n}.png` | image (public docs readable by uuid; others `?token=`) |
| GET | `/documents/{uuid}` · `/documents/{uuid}/facts` · `/documents/{uuid}/transactions?category=` | `DocumentOut` · `{facts}` · `{items:[{row_n, booked_on, amount (UZS), counterparty, counterparty_stir, account, purpose, category, category_source, category_conf, recurring_group}]}` |
| GET | `/metrics/eval` | latest `eval/results/*.json` content or `{status:"not_measured"}` |
| POST | `/auth/demo` | **404** unless `DEMO_LOGIN_ENABLED=true` (off in production) |

## Officer

| Method | Path | Response |
|---|---|---|
| GET | `/portfolio/summary` | `{as_of, run:{uuid, status, as_of, started_at, finished_at}\|null, monitored, exposure_display, exposure_unit:"bn UZS", applications_awaiting, beyond_target, requested_display (bn), warning:{n, exposure_display, pct}, status_distribution:[{status, label, means, n, exposure_display, exposure_unit, pct}], thresholds:{values:{…}, rules:[{id, indicator, rule}], note}, calibration_note, queue:[{kind:"application"\|"borrower", ref (number or loan_id), name, reason, severity, action}], status_changes:[{loan_id, name, outstanding_display, from, to, date, reason}], trend:[{as_of, watch_plus_attn}] (one point per real run)}` |
| GET | `/applications` | `{items:[{uuid, number, name, industry, requested_display, term_months, received_on, docs:"5/6", status, issues_count, issues_label}]}` |
| GET | `/applications/{number}/review` | `{application:{uuid, number, status, sla_day, sla_days, received_on, analysed_at}, applicant:{name, industry, region, stir, since, employees}, request:{amount_display, amount_unit, term_months, rate_pct, installment_display, installment_key\|null, purpose, collateral}, columns:[{key, label}] (2 periods, e.g. fy2025 "FY 2025", h1_2026 "H1 2026"), issues: Finding[] (attn/watch/neutral, open first), findings: Finding[] (all incl. info), figures:[{label, indent, cells:{<column key>: factKey\|null}, source, confidence (0–100)\|null, flag\|null}], ratios:[{label, value_display, note, period, flag, fact_key, fact_keys}], indicator:{label, supports:[string], weighs_against:[string], disclaimer, rule}, narrative:{mode:"llm"\|"template"\|null, markdown, accepted_at, attempts, verified, rejected:[{attempt, mode, at, unmatched, uncited_sentences, unknown_ids}]}, documents:[{title, filename, uuid\|null, doc_type, status:"processed"\|"processing"\|"queued"\|"needs clarification"\|"failed"\|"missing", note}], review_trail:[{at, text}], facts: Record<string, Fact>}` |
| POST | `/applications` | `{borrower:{name, stir, industry, region, employees?, since?}, number?, requested_amount? (kUZS), term_months?, rate_pct?, purpose?, collateral?, declared?:{declared_revenue_fy, declared_debts…}, received_on?}` → `201 {uuid, number, status}` |
| POST | `/applications/{number}/documents` multipart `file` | `201 {uuid, job}`; when the last document finishes, the application analysis starts by itself |
| POST | `/applications/{number}/analyse` · `/applications/{number}/narrative/regenerate` | `202 Job` |
| GET | `/applications/{number}/findings` · `/applications/{number}/ratios` · `/applications/{number}/narrative` | `{items}` · `{facts}` · narrative object |
| PATCH | `/findings/{uuid}` | `{state:"open"\|"resolved"\|"dismissed", note}` → Finding (audited, H2) |
| POST | `/applications/{number}/decision` | `{outcome, reasoning, evidence_reviewed:[keys]}` → 201 |
| POST | `/facts/{uuid}/review` | `{action:"verify"\|"correct"\|"flag", value?, note?}` → Fact |
| GET | `/borrowers?status=stable\|watch\|attn\|unknown\|not_monitored` | includes businesses without a loan: `loan_id:null, status:"not_monitored", reason:"Not monitored — no loan with the bank"`; `counts` has a `not_monitored` key. Every officer endpoint answers on an empty database (zeros, empty lists, `run:null`). Previous shape: |
| GET | `/borrowers?status=` | `{counts:{all, stable, watch, attn}, items:[{uuid, loan_id, name, industry, region, outstanding, outstanding_display, trend_pct, trend_display, coverage_display, latest_period, status, reason, updated}] (sorted by severity, then exposure), run, thresholds, calibration_note}` |
| GET | `/borrowers/{loan_id or borrower uuid}` | a borrower without a loan is opened by its uuid; then `loan:null`, `status.current:"not_monitored"` |
| GET | `/borrowers/{loan_id}` | `{business:{uuid, name, industry, region, stir, since, employees}, loan:{loan_id, type, purpose, disbursed_on, original_display, outstanding_display, installment_display, due_day, term_months, paid, left, maturity_on, collateral, coverage_display, repayments:[{n, due_on, paid_on, state:"on_time"\|"late"\|"overdue"\|"upcoming", days_late}], unit}, status:{current, since, history:[{status, from}], reason, indicators:{M01…M06:{value, display, threshold, triggered, evidence, reason}}}, alerts: (Finding & {date})[], quarterly:{periods, period_labels, revenue:[key\|null], opex, net_profit}, narrative, timeline:[{date, title, status}], documents:[{uuid, filename, doc_type, status, uploaded, note}], run, calibration_note, facts: Record<string, Fact>}` |
| POST | `/borrowers` · `/loans` · `/borrowers/{loan_id}/review-outcome` | create borrower (by STIR) · loan with repayments · officer's monitoring review outcome (H6) |
| POST | `/monitoring/runs` `{as_of?}` · GET `/monitoring/runs/latest` | `202 {run, job}` · `{run}` |
| GET/PUT | `/settings/llm` | `{enabled: boolean, provider, model, configured}` (PUT body `{enabled}`; audited) |

Narrative markdown cites facts as `[f_xxxxxx]` **after** the number it states ("Net revenue was 7 548.4 mln UZS in FY 2025 [f_gznf0q]."). The frontend turns each cite into a compact EvidenceChip (the number is already in the text; do not insert `display` a second time). Show the narrative only when `verified` is true; `mode:"template"` is labelled "Template summary".

## Owner

| Method | Path | Response |
|---|---|---|
| GET | `/owner/me` | `{user:{uuid, email, full_name, role, is_active}, business:{uuid, name, stir\|null, industry, region}}` |
| GET | `/owner/files` | `{business:{uuid, name, stir, industry, region}, items: DocumentOut[]}` (own documents only) |
| POST | `/owner/applications` JSON `{requested_amount_mln (>0), term_months (1–360), purpose?, document_uuids?: [uuid]}` — default documents = own analysed (or clarification) uploads not yet in an application → `201 {uuid, number:"APP-2026-0001", status:"processing", job}`; `422 no_documents` when nothing is analysed yet; `404 document_not_found` for a uuid that is not yours. The analysis (rules, ratios, narrative) runs in the worker; the application appears in the officer's `/applications` |
| GET | `/owner/applications` | `{items:[{uuid, number, status, status_label, requested_display, requested_unit:"mln UZS", term_months, purpose, received_on, documents, analysed_at}]}` (no officer findings) |
| POST | `/owner/files` multipart | `{uuid, job}` |
| POST | `/cfo/messages` `{question}` | `{answer:{direct_answer, table:[{label, fact_key}], cant_see, next_steps:[string]}, citations:[key], tool_trace:[{tool, args, result_key}], mode:"llm"\|"facts_only", facts: Record<string, Fact>}` |
| GET | `/cfo/messages` | `{business:{name}, messages:[{role:"user", content, created_at} \| {role:"assistant", uuid, answer, citations, tool_trace, mode, created_at, facts}]}` |

CFO answers: `mode:"llm"` = tool loop (search_facts, sum_transactions, cash_balance_series, upcoming_obligations, compute, missing_data; ≤ 6 tool calls / 20 s) and the final JSON passed the citation verifier; `mode:"facts_only"` = LLM off, or two answers rejected (then `direct_answer` says it cannot answer with verified numbers and the table lists the matching records). `tool_trace[].result` holds a short tool output; a `{tool:"verifier"}` entry records a rejected answer. Numbers in `direct_answer`/`next_steps` carry `[f_…]` cites like the narrative.

`/analyse/{uuid}.description` is `{text, mode:"llm", verified:true}` only when a ≤ 3-sentence description of an unrecognised document passed the verifier (its numbers are registered as facts with `method:"readable"`); otherwise `{text:"", mode:"none"}`. Facts with `method:"llm_fallback"` (confidence 0.75) are statutory lines the dictionary could not map and the LLM mapped among 5 candidates under the sum checks.

## Backend service entry points (for `app.seed_demo` and scripts; no HTTP needed)

```python
from app.core.db import get_db_context
from app.modules.borrowers.service import BorrowerService        # upsert_borrower(dict, actor=None) · create_loan(borrower, dict incl. repayments=[{n, due_on, paid_on, amount}], None)
from app.modules.applications.service import ApplicationService  # create_application({"borrower": {...}, "number", "requested_amount", ...}, None) · attach_upload(app, bytes, filename, None)
from app.modules.documents.service import DocumentService        # upload(bytes, filename, owner_kind="bank"|"owner"|"public", borrower_id=..., actor=None) -> (doc, job)
from app.modules.monitoring.service import start_run             # start_run(db, None, as_of=date) -> (run, job)
```
Uploading enqueues `analyse_document`; when all documents of an application are done, `analyse_application` is enqueued automatically. Monitoring statuses come only from `start_run` → worker. Hooks for wave 2 (looked up lazily, optional): `app.modules.llm.narrative.generate(db, application=, ctx=, findings=, ratio_facts=, facts=, generation=) -> NarrativeRun | None` (accepted run or None → template), `app.modules.llm.describe.describe_document(db, doc) -> {text, mode}` (public uploads), `app.pipeline.readable.readable_summary(parsed) -> dict`.
