# 08 — Pilot cost model and unit economics

Scope: cost and savings only (no price to MKBANK). **Every input is an assumption unless marked "measured"**, and each is one editable parameter. The deck shows this table with the same labels. Only the LLM token counts (p10a, p10b) are measured; officer time saved is not.

## Parameters

| id | Parameter | Value | Status / basis |
|---|---|---|---|
| p1 | Officer cost per hour | **70 000 UZS** | assumption: 9.0 mln UZS gross/month × 1.3 employer cost ÷ 168 h = 69 643 → rounded |
| p2 | Bank IT cost per hour | 100 000 UZS | assumption |
| p3 | Applications per month (pilot office) | **50** | assumption, to be confirmed with MKBANK |
| p4 | Borrowers monitored | **148** | size of the synthetic seeded loan book (`eval/generator/portfolio.py`; the production monitoring run gave 123 Stable / 15 Watch / 10 Attention, `HANDOFF.md`) |
| p5 | Baseline review time | **10 working days**, complete application → recorded decision | assumed baseline, to be confirmed with MKBANK; no external source |
| p6 | Officer-minutes saved per application | scenarios 30 / 60 / 120 min | **assumption, not measured.** The timed trial (T-035) was not run and `docs/plan/trial.csv` does not exist |
| p7 | Officer-minutes saved per borrower per month for monitoring | scenarios 15 / 30 / 45 min | **assumption, not measured** |
| p8 | FX rate | 12 500 UZS/USD | assumption; replace with the cbu.uz rate on the defence day |
| p9 | LLM price (`gpt-4.1-mini`) | USD 0.40 / 1M input tokens, USD 1.60 / 1M output | list price at planning (assumption); not re-checked against the OpenAI pricing page |
| p10a | LLM tokens per application (loan narrative) | 2.5 attempts × 4 025 input / 422 output tokens = **10 063 / 1 055** | **measured**: production `llm_calls`, purpose `narrative`, read 2026-10-10 21:55; n = 4 narrative generations, 10 calls. Recorded in commit `a9e5ee8`; no JSON export of this query is in the repo. Unmapped-line fallback calls are not included (not measured) |
| p10b | LLM tokens per borrower explanation call | **736 input / 181 output** per call | **measured**: same query, n = 120 calls. At most 3 attempts per explanation (`MAX_ATTEMPTS`, `app/modules/llm/narrative.py`) |
| p10c | AI CFO answers, `/analyse` descriptions | — | **not measured** (tokens are logged in `llm_calls`, not summarised here). Owner-side and public use are not in the bank's cost per application |
| p11 | Pilot duration | 3 months, 1 regional office | plan |
| p12 | Engineer cost | 25 mln UZS/month | assumption |
| p13 | Server write-off period | 36 months | assumption |

## Variable cost per unit (API path)

| Item | Formula | Value |
|---|---|---|
| LLM per application | (10 063 × 0.40 + 1 055 × 1.60) / 1e6 USD × p8 | 0.00571 USD → **71 UZS** (measured tokens p10a × list price p9) |
| LLM per borrower explanation call | (736 × 0.40 + 181 × 1.60) / 1e6 USD × p8 | 0.000584 USD → **7.3 UZS** (measured tokens p10b × p9) |
| LLM per monitored borrower-month (upper bound) | 3 attempts × 7.3 UZS, for every borrower | **22 UZS**. In the code, explanations are written only for Watch / Attention borrowers, so the real figure is lower |
| Compute per file set (pilot) | CPU server 43.75 mln ÷ p13 ÷ (50 + 148) file sets/month | **6 138 UZS** (assumptions p3, p13) |

## Pilot cost (3 months)

| Line | Option A: CPU server in the bank + OpenAI API (redacted fact JSON only) | Option B: on-prem local model (no egress) |
|---|---|---|
| Engineers 2 FTE × 3 months × p12 | 150.00 mln | 150.00 mln |
| Analyst 0.5 FTE × 3 × 20 mln (assumption) | 30.00 mln | 30.00 mln |
| Officer time for real-document evaluation (40 h × p1) | 2.80 mln | 2.80 mln |
| Bank IT integration (80 h × p2) | 8.00 mln | 8.00 mln |
| Hardware: 16-core / 64 GB / 2 TB server (USD 3 500 × p8; price is an assumption) | 43.75 mln | — |
| Hardware: same + 1× NVIDIA L4 24 GB for Qwen2.5-7B (USD 9 000 × p8; price is an assumption; local-model quality and speed not measured) | — | 112.50 mln |
| LLM API: 3 × (50 × 71 + 148 × 22) UZS | 0.02 mln | 0 |
| Licences (all open source, see `docs/DATA-SOURCES.md`) | 0 | 0 |
| **Total** | **234.57 mln UZS** | **303.30 mln UZS** |

## Savings model

`monthly saving = p3 × Δmin_app / 60 × p1 + p4 × Δmin_mon / 60 × p1`

**Every row below depends on p6 and p7, which are assumptions and not measured.** No payback figure here is a measured result.

| Scenario (assumed) | Δmin per application (p6) | Δmin per borrower-month (p7) | Applications part | Monitoring part | **Monthly saving** | Payback A | Payback B |
|---|---|---|---|---|---|---|---|
| Low | 30 | 15 | 1.75 mln | 2.59 mln | **4.34 mln** | 54.0 months | 69.9 months |
| Mid | 60 | 30 | 3.50 mln | 5.18 mln | **8.68 mln** | 27.0 months | 34.9 months |
| High | 120 | 45 | 7.00 mln | 7.77 mln | **14.77 mln** | 15.9 months | 20.5 months |
| Measured | not measured: the timed trial (T-035) was not run | | | | | | |

Reading it straight: **at one office, officer time alone pays back slowly.** The platform cost is mostly fixed (people + one server), so payback scales with the number of offices on the same deployment. An illustrative example, which ignores the extra per-office costs: 5 offices at the Mid scenario → 43.4 mln/month → Option A pays back in 5.4 months, Option B in 7.0. The deck states this rather than a single flattering number.

## Unit economics per application (Mid scenario, assumed)

| | UZS | basis |
|---|---|---|
| Officer time saved (60 min × p1) | 70 000 | assumption (p6 Mid, p1) |
| LLM cost | −71 | measured tokens (p10a) × list price |
| Compute cost per file set | −6 138 | assumptions (p3, p13) |
| **Net per application** | **63 791** | depends on the assumed 60 min |

Not monetised (stated qualitatively on the slide, no numbers invented): undeclared obligations caught before disbursement (R06), earlier warning on deteriorating borrowers (M01–M06), audit trail for Central Bank inspection, and shorter time-to-decision against the 10-working-day assumed baseline. The share of those 10 days that is file preparation is measured in pilot month 1.

## Next-steps slide

| Month | Step | Success measure |
|---|---|---|
| 1 | Data-sharing agreement; 100 anonymised MKBANK SME files; real-document eval; officer time-and-motion on 20 applications; calibrate M01–M06 thresholds against 24 months of bank history | field F1 per document type on real files; measured Δmin; thresholds signed off by risk |
| 2 | On-prem install in the bank perimeter (Option B), LDAP/SSO, audit export to the SIEM; Central Bank walkthrough of the explainability and audit trail | zero external calls; CB feedback recorded |
| 3 | Live on one regional office: new applications + monthly monitoring of its SME book | officer-minutes per application, findings confirmed by officers (precision on real files), time-to-decision vs baseline |
| After | Owner-side AI CFO as the borrower data channel (statements uploaded monthly → monitoring) | % borrowers uploading on time |
