# Handoff: state at 2026-10-11 01:00 (UTC+5)

Production: https://converza.uz (business owner app) and https://app.converza.uz (bank officer app), deployed by GitHub Actions from `main` (repo `Az1mbek-Xak1mov/hackaton_wiut`). **No freeze yet: the user decides when to tag `v1.0`.**

## What changed overnight (10 Oct 22:00 → 11 Oct 01:00)
- Plain-language UI on both apps: no raw codes, page subtitles, clear empty states. Every borrower opens, including those with no loan. Application review starts with a summary and has a "Your decision" section.
- Owner app: "What the bank needs" checklist (ticks only real uploads), a 4-step line per application, the bank's decision + message, "request more information" → owner adds documents → back to the officer's queue.
- Landing (converza.uz): what it is, 3 steps, both sides, "Measured, not claimed" read live from the eval JSON (incl. precision and silent errors), what Converza does not do.
- `/analyse` (public, no account): one document **or a whole loan file** (several files or a ZIP) → cross-document checks R01–R12, ratios, verified summary; samples run with one click; public loan files expire in 24 h and never appear in bank views.
- Jury-input robustness: 20-digit account numbers, line codes no longer read as values, statement vs invoice, PDF / XLS / CSV statements, describe stage isolated. HEIC gives a plain message (pillow-heif dropped: GPL wheel).
- Sign-in pages redesigned; the orange strip is now a footer line.
- Old tabs reload automatically after a deploy (stale chunk fix).
- Production reseeded through the pipeline (`app.seed_demo`) after a reset; backup `/srv/converza/backups/pre-reseed-20261010T190019.sql.gz`.
- Docs: `docs/DATA-SOURCES.md` (data, licences, external services), 08-BUSINESS consistent at 71 UZS/application, time saved labelled as an assumption.
- Host nginx updated with the `/api/v1/analyse/bundle` limit (backup in `/srv/converza/backups/`).

## Decisions waiting for the user
| Item | Notes |
|---|---|
| Jury demo sign-in | Button is built, hidden while `DEMO_LOGIN_ENABLED=false`. Turn on in `/srv/converza/.env` and restart api (`docker compose … up -d api`), or give the README logins on a slide. |
| LLM token export | `llm_calls` aggregate → `eval/results/` would give the 71 UZS figure a file source (prod read was not permitted for the agent). |
| T-035 timed trial | Still not run; ROI rests on labelled assumptions. |
| T-037 phone tests, T-038 backup video | People tasks. |
| T-040 freeze | `git tag v1.0 && git push --tags`; `gh workflow disable deploy -R Az1mbek-Xak1mov/hackaton_wiut` |
| Deck | https://claude.ai/artifact/TpRsjdWLEmNMeBA6a7aKie: add the public loan-file check to the demo slide. |

## Facts to remember
- Dictionary codes (lex.uz/docs/771825): finance costs 170, profit before tax 240, profit tax 250, total equity + liabilities 780.
- Worker runs each job in a child process (pdfium is not thread-safe), 2 at a time.
- owner@converza.uz = Farovon Savdo MChJ, whose APP-2026-0931 is the hero file in the bank queue.
