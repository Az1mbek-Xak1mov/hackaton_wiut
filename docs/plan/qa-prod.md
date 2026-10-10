# Production QA: jury contingency matrix (API level)

Run 2026-10-10 20:33 (UTC+5) against https://converza.uz/api/v1/analyse from a laptop. Each row is a real upload, polled until the job finished. Time = end to end (upload accepted → result ready, incl. queue). Phone uploads (Android/iOS) are still to be done by people (T-037).

| File | Branch (05-DEMO) | Time | Type | Status | Facts | What the user sees |
|---|---|---|---|---|---|---|
| `samples/form2_scan_150dpi.pdf` | statutory form, scan | 15.3 s | form2 | analyzed | 51 | extracted lines with page highlights |
| `samples/photo_form2.jpg` | photo, passes quality gate | 10.4 s | form2 | analyzed | 52 | extracted lines |
| `samples/photo_invoice.jpg` | photo, fails quality gate | 4.9 s | unknown | failed | 0 | "Could not analyse reliably: the image is 640×480 px (minimum 900 px…)" + what was read |
| `samples/english_ifrs.pdf` | English document | 3.1 s | form1 | clarification | 36 | matched by label, low-confidence cells to clarify |
| `samples/statement.xlsx` | bank statement | 2.2 s | bank_statement | analyzed | 46 | transactions, categories, recurring groups |
| `hard/H01/form2_rotated.pdf` | rotated page | 8.1 s | form2 | analyzed | 52 | OSD rotation, lines extracted |
| `hard/H16/form2_encrypted.pdf` | encrypted | 1.3 s | unknown | failed | 0 | "The PDF is encrypted (password-protected)…" |
| `hard/H20/letter.pdf` | unknown PDF | 1.2 s | unknown | analyzed | 0 | "Not a recognised statutory form or statement…" + readable text |

All 8 branches return a true answer in under 60 s (max 15.3 s).
