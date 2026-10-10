# 09 — API contract (frontend ↔ backend)

Base `/api/v1`, JSON snake_case, errors per blueprint `{code, i18n_key, params, message}`. Money values are numbers in **kUZS** (thousand UZS, as printed in the statutory forms). Each fact has a `display` string pre-formatted by the backend (`"9 842.3"` mln UZS, 1 decimal, space thousands). The frontend shows `display` and never formats or computes figures.

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
type Job = { uuid: string; status: "queued"|"running"|"done"|"failed"; stage: string; progress: number; error: string };
```

`GET /facts?keys=a,b,c` returns `{facts: Fact[]}` (any user with read access). Evidence chips carry a fact key; the evidence store fetches missing keys in batches.

## Public

| Method | Path | Response |
|---|---|---|
| GET | `/version` | `{git_sha, built_at, deployed_at, llm_provider, llm_enabled}` |
| POST | `/analyse` multipart `file` | `201 {uuid, job}` |
| GET | `/analyse/{uuid}` | `{document: DocumentOut, job: Job, facts: Fact[], unmapped: [{page_n, text, value_printed, bbox}], findings: Finding[], transactions_preview: {count, by_category:[{category, count, inflow_display, outflow_display}], recurring:[{group, label, count, amount_display, day_of_month, evidence:[fact key]}]}, readable: {pages, language, ocr_mean_conf, numbers:[{text, label, page_n, bbox}], dates:[string], stirs:[string], text_excerpt: string}, description: {text, mode:"llm"|"none"} }` |
| GET | `/documents/{uuid}/pages/{n}.png` | image (public docs readable by uuid) |
| GET | `/metrics/eval` | latest `eval/results/*.json` content or `{status:"not_measured"}` |
| POST | `/auth/demo` `{role:"officer"\|"owner"}` | token pair like login |

## Officer

| Method | Path | Response |
|---|---|---|
| GET | `/portfolio/summary` | `{as_of, run:{uuid, finished_at}, monitored, exposure_display, applications_awaiting, beyond_target, warning:{n, exposure_display, pct}, status_distribution:[{status, label, means, n, exposure_display, pct}], thresholds:{…}, queue:[{kind:"application"\|"borrower", ref, name, reason, severity, action}], status_changes:[{borrower_uuid, name, outstanding_display, from, to, date, reason}]}` |
| GET | `/applications` | `{items:[{uuid, number, name, industry, requested_display, term_months, received_on, docs:"5/6", status, issues_count, issues_label}]}` |
| GET | `/applications/{number}/review` | `{application:{uuid, number, status, sla_day, sla_days, received_on, analysed_at}, applicant:{name, industry, region, stir, since, employees}, request:{amount_display, term_months, installment_display, purpose, collateral}, issues: Finding[], figures:[{label, indent, cells:{fy2025: factKey\|null, h1_2026: factKey\|null}, source, confidence, flag}], ratios:[{label, value_display, note, flag, fact_key}], indicator:{label, supports:[string], weighs_against:[string], disclaimer}, narrative:{mode:"llm"\|"template", markdown, accepted_at, attempts}, documents:[{title, filename, uuid\|null, status, note}], review_trail:[{at, text}], facts: Record<string, Fact>}` |
| POST | `/applications/{number}/decision` | `{outcome, reasoning, evidence_reviewed:[keys]}` → 201 |
| POST | `/facts/{uuid}/review` | `{action:"verify"\|"correct"\|"flag", value?, note?}` → Fact |
| GET | `/borrowers?status=` | `{counts:{all, stable, watch, attn}, items:[{uuid, loan_id, name, industry, region, outstanding_display, trend_pct, coverage_display, latest_period, status, reason, updated}]}` |
| GET | `/borrowers/{loan_id}` | `{business, loan, status:{current, since, history}, alerts: Finding[], quarterly:{…}, narrative, timeline, documents, facts: Record<string, Fact>}` |
| GET/PUT | `/settings/llm` | `{enabled: boolean, provider, model}` |

Narrative markdown cites facts as `[f_xxxxxx]`. The frontend replaces each cite with an EvidenceChip whose text is the cited fact's `display`.

## Owner

| Method | Path | Response |
|---|---|---|
| GET | `/owner/files` | `{items: DocumentOut[]}` |
| POST | `/owner/files` multipart | `{uuid, job}` |
| POST | `/cfo/messages` `{question}` | `{answer:{direct_answer, table:[{label, fact_key}], cant_see, next_steps:[string]}, citations:[key], tool_trace:[{tool, args, result_key}], mode:"llm"\|"facts_only", facts: Record<string, Fact>}` |
| GET | `/cfo/messages` | thread history |
