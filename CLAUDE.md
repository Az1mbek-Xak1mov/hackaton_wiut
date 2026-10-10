# Converza: team 10x engineers

Document-to-evidence engine for Uzbek SME financials (partner: MKBANK SME Lending; co-partner: Central Bank). Every number can be clicked back to the page it came from, and the model is not allowed to state a number that isn't in the records. Project language: English. Live: https://converza.uz.

## Plan
- The plan lives in `docs/plan/`: 00-STRATEGY, 01-ARCHITECTURE, 02-PIPELINE, 03-DATA, 04-TASKS, 05-DEMO, 06-DEPLOY, 07-RISKS, 08-BUSINESS. Read 00 and 04 before starting work.
- **When a task in `docs/plan/04-TASKS.md` is done, tick its checkbox and append the date and time** (`✅ 2026-10-10 19:05`). Done = its acceptance criteria hold on https://converza.uz (or in CI for non-UI tasks).
- When behind schedule, apply the cut list in 04 in order. Never cut: the `/analyse` jury path, the evidence pane, the citation verifier, the LLM-off toggle, Actions deploy, the eval JSON behind any stated metric.
- Code freeze 2026-10-10 23:15 (UTC+5): tag `v1.0`, no deploys after it.

## Honesty rules (binding)
- **No scripted outputs in the deployed demo.** Every figure, finding, status, ratio and AI sentence is produced by the pipeline. Demo data is seeded by pushing files through the pipeline (`app/seed_demo.py`), never by inserting results.
- `design/demo-data.json` is a **design reference and generator target**, not a data source. Never import it in `web/src` or `app/`. If the computed value differs from the design, show the computed value.
- **No invented metrics.** Any number in the README, deck or UI about accuracy, latency, cost or time saved comes from `eval/results/*.json`, `jobs` timings, `llm_calls` or `docs/plan/trial.csv`, with n and dataset stated. Otherwise write "not measured".
- **No numeric credit score anywhere.** Status = Stable / Watch / Attention from disclosed rules, always with its reason and the label "calibration against bank history is pilot month 1".
- The system never approves or rejects; only an officer writes a decision.
- Synthetic data is declared on the prototype strip. Assumptions (10-working-day baseline, 50 apps/month, officer-hour cost, FX, token prices) are labelled where they are used.

## Backend
- Follow `ARCHITECTURE.md` (FastAPI + PostgreSQL + JWT + Alembic + uv blueprint) exactly: modules in `app/modules/<feature>/{models,schemas,service,router}.py`, services own transactions plus audit, scopes not role names, `AppException` errors, `/api/v1`, snake_case, uuid in URLs.
- Pipeline code is pure functions in `app/pipeline/`; the worker (`app/worker.py`) consumes the Postgres `jobs` table (`SKIP LOCKED`). No Redis.
- LLM only through `app/modules/llm/provider.py` (`LLM_PROVIDER=openai|anthropic|ollama|none`). Every generated text goes through `app/pipeline/verify.py`. The LLM never does arithmetic; derived numbers come from the `compute` tool or `app/pipeline/ratios.py`.
- With LLM off, extraction, reconciliation, ratios and monitoring must behave identically (none of them call the LLM).
- Tests: `uv run pytest -q` (SQLite in memory). Frontend: `cd web && npm run build`.

## Design source of truth
- Read `design/DESIGN.md` and `design/SCREENS.md` before touching any UI. The design says "Sarhisob"; the product name is **Converza** (wordmark, titles, copy).
- `design/reference/*.dc.html` are reference artboards (HTML + inline CSS + SVG) from the design canvas. They use a canvas runtime (`<x-dc>`, `<sc-for>`, `{{holes}}`). Do NOT copy them in; re-implement with our components, matching their structure, spacing values, copy and chart geometry.
- Render "n/a — upload X" states when data is absent.
- Status pills always carry a reason.
- Fonts: IBM Plex Sans (UI), IBM Plex Mono (quoted document values only). Tabular numerals everywhere.
- The palette is tokenised in `design/DESIGN.md` → `web/src/styles/tokens.css`; no other colours.
- Charts: inline SVG components, ≤ 2 series, one axis, legend + latest-value labels.
- Avoid: gradients, glows, glassmorphism, icon-per-heading, KPI card grids, chat bubbles, emoji.
- Prototype strip text: "Synthetic demonstration documents. All figures are computed live from them."

## Deploy
- Push to `main` → GitHub Actions → ssh `deploy@159.195.213.245` → `/srv/converza/repo/deploy/deploy.sh`. Details in `docs/plan/06-DEPLOY.md`.
- The server is shared with other production sites: always `sudo nginx -t` before reload; ports 127.0.0.1:8050 (api) and 8051 (web) only.
