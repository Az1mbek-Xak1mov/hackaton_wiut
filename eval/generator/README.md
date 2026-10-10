# Synthetic data generator

All data is synthetic and declared. Company names, STIRs, banks and lenders are fictional.

```bash
uv run python -m eval.generator synth --n 200 --seed 0 --out data/synth   # train 0-119 / dev 120-159 / test 160-199 (git-ignored)
uv run python -m eval.generator heroes      # data/seed/hero_{farovon,navroz,zilola}   (pinned to design/demo-data.json)
uv run python -m eval.generator portfolio   # data/seed/loan_book.csv + portfolio/<loan_id>/ + applications/ + applications.csv
uv run python -m eval.generator samples     # web/public/samples/* (zips + single files)
uv run python -m eval.generator hard        # data/hard/H01..H20
uv run python -m eval.generator all         # everything above, in this order
uv run pytest -q tests/eval                 # invariants
```

## Truth files

- `truth.json` per bundle. `documents[].fields[code] = {cur, prev, page, printed_cur, printed_prev}`. Values are in kUZS, as printed. `null` or a code listed in `blank_cells` means the cell was printed blank or `-` and is not expected to be extracted.
- `documents[].extra_rows`: official rows that are not in the dictionary, plus unofficial rows (`unofficial: true`). They are expected to be **unmapped**.
- Column convention (statutory, annual and interim alike): Form 1 runs "На начало / Hisobot davri boshiga" (31.12 of the prior year) then "На конец / Hisobot davri oxiriga". Form 2 runs "Соответствующий период прошлого года / O'tgan yilning shu davri" (the same period last year) then "Отчетный период / Hisobot davri". Quarterly monitoring bundles ship the Q2 **and** Q3 forms (Q1 and Q2 for late uploaders), so a quarter-over-quarter comparison takes the current columns of two documents. Quarterly Form 2 covers a standalone quarter ("за 3 квартал 2026 г." / "2026 yil 1 iyuldan 30 sentyabrgacha"). The footer date is labelled "Дата подписания / Imzolangan sana".
- `columns_left_to_right`: `["prev","cur"]`, or `["cur","prev"]` in the `software_export` layout, where the columns are reversed and the headers say which is which.
- `transactions.rows[]`: `{row (Excel 1-based), date, amount (UZS, + inflow), category, recurring_group, counterparty_stir}`. `recurring_group` is set only when the plan's definition holds: at least 3 payments, day-of-month std ≤ 3, and amount CV ≤ 0.15.
- `planted[]`: contradictions with their parameters. `expected_clean_rules` lists the rules that must not fire.
- Portfolio `truth.json`: `scenario`, `expected_indicators` (M01–M06) and `params`. The status itself is never stored; the monitoring run computes it.

## Line codes

Every form follows `app/pipeline/dictionary/forms.yaml`. That means the official codes: finance costs are 170/180, profit tax is 250, and total liabilities + equity is 780. The design artboards used 120 and 240 for the first two.
