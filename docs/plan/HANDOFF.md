# Handoff: state at 2026-10-10 18:55 (UTC+5)

Work paused at the user's request. Production: https://converza.uz. Deploys: GitHub Actions on push to `main` (the repo is `Az1mbek-Xak1mov/hackaton_wiut`) plus `/srv/converza/deploys.log` on the server.

## Done
- P1–P3 and most of P4 are built; see the ticks in `04-TASKS.md`. Several ticks were verified only locally; production checks are listed below.
- Pipeline: classify → parse (text layer / Tesseract OCR / xlsx) → Form 1/2 extraction by line-code dictionary (checked against lex.uz/docs/771825) → statements (rules + TF-IDF/LR categoriser, recurring payments) → rules R01–R12 → ratios → monitoring M01–M06 → narrative with citation verifier (LLM or template) → AI CFO tool loop.
- First eval: `eval/results/2026-10-10_1834_283cd8d.json` → `docs/EVAL.md`, `docs/KNOWN-FAILURES.md` (38 entries). Laptop, LLM off, synthetic test split + 20 hard cases.
- Seed through the real pipeline (`app/seed_demo.py`): locally 779 documents in ~6 min. Monitoring computed 123 stable / 15 watch / 10 attention.

## Not done / next steps (in order)
1. **Confirm the production deploy of this commit**: the Actions run must be green, `/api/v1/version` must equal the HEAD SHA, and the seed container must finish (`docker compose -p converza --env-file /srv/converza/.env -f compose.prod.yml logs seed`). Then click through `/bank`, `/bank/applications/APP-2026-0931`, `/bank/borrowers`, `/owner/cfo` and `/analyse` on production. Tick T-007.
2. **OpenAI key**: set `OPENAI_API_KEY` in `/srv/converza/.env`, run `docker compose … up -d api worker`, and verify a live narrative and a CFO answer pass the verifier. Until then every narrative is the labelled template.
3. **Extraction weak spots** from the eval:
   - 150-dpi scans swap the current/prior columns when OCR loses the header row (Form 2 150-dpi P 0.72 / R 0.59).
   - `extract_application` doesn't read the contract-number lines for declared debts (R06 recall 5/11).
   - One Uzbek-Cyrillic layout-B statement is classified as unknown (b0172).
   - Then re-run `uv run python -m eval.run --split test` + hard → `eval.report`, then `uv run python -m eval.latency_prod` after the production seed. That completes T-034.
4. **Small integration fix**: pass `filename=` to `parse_document` from the job runner (the filename hint is unused today).
5. **Frontend**: the agent was stopped mid-way through design QA and the UZ/RU/EN switch, though the build is green. Check `/owner/cfo` against the live CFO endpoint (T-033), and check screens at 390 px.
6. **People tasks**: T-035 timed trial (2 people × 3 bundles → `docs/plan/trial.csv`), T-037 phone matrix, T-038 backup video.
7. **Deck** (T-041) from the eval JSON + trial + 08; then code freeze T-040 (tag `v1.0`, disable the deploy workflow).

## Facts to remember
- Dictionary codes differ from the design: finance costs 170, profit before tax 240, profit tax 250, total equity + liabilities 780. The UI uses dictionary labels.
- The worker runs each job in a child process (pdfium is not thread-safe); concurrency 2.
- Local Postgres container `converza-pg` (port 5462) holds dev DBs; `app_seedtime2` has a fully seeded dataset.
