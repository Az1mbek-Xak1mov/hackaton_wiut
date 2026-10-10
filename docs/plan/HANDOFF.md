# Handoff: state at 2026-10-10 22:00 (UTC+5)

Production: https://converza.uz on `e03aaba`, deployed by GitHub Actions (repo `Az1mbek-Xak1mov/hackaton_wiut`). It was seeded through the real pipeline: 777 documents, 6 applications, a monitoring run with 123 stable / 15 watch / 10 attention.

## Done
- T-001 to T-034 and T-036 are ticked (see `04-TASKS.md`).
- Eval: `eval/results/2026-10-10_2042_cd93dff.json` (incl. `latency_production`) → `docs/EVAL.md`, `docs/KNOWN-FAILURES.md`, served on `/metrics`.
- Jury contingency matrix, API level: `docs/plan/qa-prod.md`. 8 of 8 branches answer truthfully, max 15.3 s.
- Deck (12 slides, numbers from the eval JSON, production timings and labelled assumptions): https://claude.ai/artifact/TpRsjdWLEmNMeBA6a7aKie. It is private; share it from its Share menu, or export it as PDF/PPTX.

## Remaining
| Task | Who | Notes |
|---|---|---|
| OpenAI key | done 21:55 | Live on prod (`llm_configured: true`). Hero narrative accepted on attempt 2 (attempt 1 rejected; visible in the review trail). 60 borrower explanations accepted. CFO answers via tools in ~6 s. Measured ~71 UZS LLM cost per application. |
| T-035 timed trial | 2 people | 3 bundles, manual vs Converza → `docs/plan/trial.csv` → replace the ROI slide's scenarios with the measured median |
| T-037 phone tests | people | Android + iOS uploads on /analyse; tick the table in `05-DEMO.md` |
| T-038 backup video | people | 3-min recording of the 05-DEMO click path on prod |
| T-040 freeze | lead | 23:15: `git tag v1.0 && git push --tags`; `gh workflow disable deploy -R Az1mbek-Xak1mov/hackaton_wiut` |

## Facts to remember
- Dictionary codes (lex.uz/docs/771825) differ from the design: finance costs 170, profit before tax 240, profit tax 250, total equity + liabilities 780.
- Seeded documents were processed with the pre-`e03aaba` extractor. New uploads use the improved one.
- The worker runs each job in a child process (pdfium is not thread-safe), 2 at a time.
- Page images are served as grayscale JPEG at the PNG's pixel size, cached next to the PNG.
