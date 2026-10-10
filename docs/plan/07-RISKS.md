# 07 — Pre-mortem

"It is 00:30 on 11 Oct and the submission failed or the demo flopped. Why?"

| # | Risk | Likelihood / impact | Early-warning signal | Mitigation | Owner |
|---|---|---|---|---|---|
| 1 | **DNS not propagated**: converza.uz still points to 77.42.28.135, so no TLS and no public URL | M / critical | `dig +short converza.uz @8.8.8.8` ≠ 159.195.213.245 at 18:00 | T-001 first at 17:15 with TTL 300; until it propagates, test via `curl --resolve`; if not resolved by 19:30, issue certbot for a subdomain we already control and submit that URL + note | C |
| 2 | Breaking neighbour production sites on the shared server (nginx reload, RAM) | L / critical | `nginx -t` warning; `free -m` available < 1 GiB; satstars/goedu non-200 | separate vhost file; always `nginx -t`; compose mem limits (total 3.6 GiB); worker concurrency 2; post-reload curl of neighbours (06) | C |
| 3 | OCR too slow on 4 vCPU → jury path > 60 s | M / high | T-013 per-page time > 6 s on the server | 10-page cap, 300 → 200 dpi for clean scans, digit-only second pass only on numeric columns, partial-result deadline at 55 s, public jobs jump the queue | D |
| 4 | Extraction accuracy poor on real-looking layouts → the jury's file gives garbage | M / high | dev F1 < 0.9 at 19:45 | conf gating (show "needs clarification", never a silent wrong number); unmapped lines listed; the "what I could read" path; known-failures list ready | D |
| 5 | Line-code meanings in the design (e.g. 490 = long-term liabilities) differ from the official template | M / medium | T-010 lex.uz cross-check | dictionary wins; UI labels come from the dictionary; the generator follows the dictionary, so hero figures stay consistent | D |
| 6 | Verifier rejects every LLM draft → only templates shown | M / medium | acceptance at attempt 1 < 50% on 5 runs at 21:00 | `display` strings pre-formatted in the fact set; feedback loop with the unmatched list; the template is a legitimate, labelled outcome | A |
| 7 | OpenAI key or quota fails during the defence | L / medium | 401/429 in `llm_calls` | hard limit set but generous; LLM-off toggle rehearsed as part of the story; narratives for seeded applications already accepted and stored | A |
| 8 | Scope overrun: screens not finished at 22:30 | H / high | any milestone > 20 min late | cut list in order (04); never cut the jury path, evidence pane, verifier, deploy | tech lead (C) |
| 9 | Seed through the pipeline takes too long or fails on deploy | M / high | T-028 run > 15 min locally | seed is resumable/idempotent per bundle; cut list #6 (40 portfolio bundles); seed runs in the background after the api is healthy | C |
| 10 | Someone hard-codes a number to "make the screen match the design" | M / **critical** (disqualifying) | grep in review: numeric literals in `web/src/pages/**`; `demo-data.json` imported anywhere in `web/src` | CLAUDE.md rule; CI step `! grep -rn "demo-data" web/src` and a lint for numeric literals > 99 in `.vue` templates; designs differ → we show the computed value | all |
| 11 | Metrics on the slide not reproducible | M / high | no `eval/results/*.json` by 22:30 | slide numbers only from the JSON; "not measured" otherwise; synthetic caveat on the slide | D |
| 12 | Public endpoint abuse (large files, spam) during judging | L / medium | nginx 429s / disk growth | `limit_req` 10 r/min/IP, 25 MB cap, 24 h purge, 10-page OCR cap | C |
| 13 | Code-freeze violation (a deploy after 23:15) | L / high | Deployments tab | tag `v1.0`; disable the workflow (`gh workflow disable deploy`) at 23:16 | C |
| 14 | Jury file contains real personal data | M / medium | — | public uploads never sent to the LLM with names (`LLM_REDACT`); purged after 24 h; stated on `/analyse` | A |
| 15 | Defence overruns 7 min | M / medium | rehearsal > 6:45 | one rehearsal at 23:20 with a timer; demo click path capped at 2:00; a juror upload that runs long → move on and return at 2:45 | P1 |
