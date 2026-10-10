# Screens — routes, layout, data, states, interactions

Two roles share one engine and one design system. Reference file per screen in `reference/`.
Demo dataset: `demo-data.json` (all figures reconcile — keep them, do not re-invent).

## Shared shell
`PrototypeStrip` → `TopBar(role)` → `[SideNav(role) | Main]`. SideNav items:
- owner: Overview `/owner`, Upload & analyze `/owner/upload`, Financial health `/owner/health`, AI CFO `/owner/cfo` (+ "Data coverage" card: period, n of m documents analyzed)
- officer: Portfolio overview `/bank`, Applications (12) `/bank/applications`, Borrowers (148) `/bank/borrowers`, Alerts (9) `/bank/borrowers?status=attention` (+ "Monitoring run" card)
TopBar role-switch link: owner ↔ officer (demo only).

---

## 01 `/owner` — Business overview (`reference/Main.dc.html`)
Header: "Overview — September 2026", meta line (as-of date, comparison, sources). Right: period `<select>`, primary "Upload documents".
1. **Figure strip** (4): Revenue 1 284.5 (+6.2%), Expenses 1 071.3 (+9.1% watch colour), Net profit 213.2 (16.6% margin · Aug 18.8%), Cash balance 318.2 (−27.0%, flagged cell, pill "Falling").
2. Row `auto-fit minmax(420px)`:
   - Panel "Cash in vs cash out" — grouped bars Apr–Sep (in/out), then divider + "Cash balance, end of month" line chart. Data `owner.cashflow.monthly`.
   - Panel "Needs attention" — 3 ranked items (`owner.attention`), each with evidence chips → `/owner/cfo` and pill (Act now / Watch / Explained).
3. Row: "What changed in September" (3 bullets w/ chips → health anchors) · "Upcoming payments · next 30 days" table (`owner.obligations`, total row 632.2).
4. Ask panel (accent-tinted): input + primary Ask → `/owner/cfo`; 3 suggestion chips (prefill question).
States: period select changes dataset (only Sep 2026 populated in demo; others show empty state "No statements for this period — upload").

## 02 `/owner/upload` — Upload & analyze (`reference/Upload.dc.html`)
Header + primary "Continue to financial health →".
Row: **Upload panel** (dropzone, supported formats chips, recognised document types list) · **Needs your clarification** (3 cards: low-confidence value with candidate buttons; 14 uncategorised transactions with select + "Apply to all"; missing Q3 statements notice).
**Uploaded files** table (`owner.files`): file (badge, mono name, size/time) · recognised as · period · status · extracted summary · actions. Five rows cover: Analyzed, Analyzed, Processing 68% (progress bar + step text + Cancel), Needs clarification (Resolve), Could not analyze (cause + Re-upload / Enter manually).
**Extracted from Forma2_1yarim_2026.pdf** table (`owner.extracted.forma2_h1_2026`): line · field as printed (Uzbek) · interpreted as · current · prior · confidence pill (one at 84% with "2025 cell blank").
Interactions: drag/drop + file input (real upload in app; demo seeds the list). Clarification choices write back to the figure and raise confidence to 100%.

## 03 `/owner/health` — Financial health (`reference/Health.dc.html`)
Header: "Financial health", compare-with select, secondary "Ask about these figures". SideNav gets an "On this page" anchor list.
Panels (questions as headings):
- `#trend` "Is revenue growing faster than expenses?" grouped bars Apr–Sep + 3 summary figures (+16.5% / +14.9% / margin). Jul–Sep marked **estimate**.
- `#profit` "Am I actually profitable?" P&L table Sep vs Aug vs Δ with indented opex lines and sum rows; net profit flagged "Q3 profit tax not yet accrued".
- `#cash` "Where did the cash go in September?" waterfall rows opening → collections → 6 outflows → closing; footer sentence + link to CFO.
- `#ar` "Who owes me, and whom do I owe?" receivables aging stacked bar + table (bucket · amount · largest counterparty, Dilshod row has chip); payables paragraph.
- `#debt` "Debt & obligations" 4 figures + 24-cell repayment strip (12 paid teal / 12 upcoming grey) + note.
- `#changes` "Significant changes, explained" — 4 rows `90px 1fr` (delta · explanation with chip), last one is the **n/a Inventory** row.

## 04 `/owner/cfo` — AI CFO workspace (`reference/AICFO.dc.html`)
Two panes: conversation (`flex:1 1 520px`) · **Evidence** aside (sticky). SideNav shows earlier conversations.
Conversation (`owner.cfo.thread`): context line (which records, data to date) → Q1 "Why is my cash balance falling even though I'm profitable?" → answer with **profit→cash bridge table** (7 rows, sums to −117.9, Record column of chips) + 3 next steps → Q2 "Will I have enough cash…" → two-scenario table (+206.4 / −31.6), "Tightest day" mini bars, amber **What I can't see** box, 3 options cheapest first. Composer + 3 suggestion chips.
Evidence pane: title, badge (source type), source line, Mono passage (Uzbek/Russian), rows table, interpretation, actions; "Cited in this conversation" list. Clicking any chip sets `selectedEvidence` (`owner.cfo.evidence[key]`).
App behaviour: answers are generated from extracted records only; every number in an answer must map to an evidence key or be computed from mapped ones; missing data → explicit "What I can't see".

## 05 `/bank` — Portfolio overview (`reference/Portfolio.dc.html`)
Officer density (13px). Header: date, as-of, primary "Review alerts", secondary "Next application in queue".
Figure strip: Businesses monitored 148 · Outstanding exposure 86.4 bn · Applications awaiting review 12 (4 beyond 5-day target) · Emerging warning signs 9 (flagged cell, 6.2 bn, 7.2%).
Row: **Needs attention today** queue (`bank.queue`, 7 of 21; grid `110px 1fr auto`; type tag Application/Borrower coloured info/attn/watch; name → detail route; reason; action button) · right column: **Monitoring status** (stacked bar 79.6/13.2/7.2% + table Status · Means · Borrowers · Exposure) and **Portfolio trend** (exposure line chart; Watch+Attention count bars — two separate single-axis charts).
Row: **New applications** table (6 of 12, `bank.applications`) · **Status changes, last 7 days** table (`bank.statusChanges`, pill → pill).

## 06 `/bank/applications/:id` — Loan application review (`reference/LoanReview.dc.html`)
Breadcrumb. Header: applicant + pills (In review · day 4 of 5, 3 issues) + meta; actions: Request missing documents, Add note, **Record officer decision** (primary).
**Request summary** panel (kv grid: requested, term & repayment, purpose, collateral, installment vs revenue, received).
Tabs (anchors): Summary · Issues · Figures · Ratios · AI analysis · Documents.
Left column:
- **Issues to resolve** (3; pill type + title + explanation with chips + action): Undeclared obligation (attn) · Contradiction (watch) · Missing document (neutral).
- **Extracted figures** table: figure · FY2025 · H1 2026 · source line · confidence pill; cells that are traceable are chips. Long-term liabilities row confidence pill = "Contradicts statement" (attn).
- **Ratios** grid of 6 boxes (label, value 20/500, derivation); DSCR box amber "1.47 → 1.04".
- **Preliminary repayment-capacity indicator** header ("Adequate, with two unresolved issues" + disclaimer) → Supports / Weighs against two-column lists → **AI analysis** paragraphs with chips → "Before a decision" paragraph.
- **Documents** list (6 received w/ status pills, 1 missing dashed).
- Footer line: system does not approve/reject.
Right: **Evidence** aside (sticky): title, doc, confidence pill, where, Mono passage with highlighted hit, Interpretation, optional related-rows table, actions, **Review trail** list.
State: `selectedEvidence` default `debt`. Keys in `bank.application.evidence`.

## 07 `/bank/borrowers` — Borrower portfolio (`reference/Borrowers.dc.html`)
Header + actions (Export table, Request statements from 17 late uploaders). SideNav explains how statuses are set.
Filter bar: status chips All 148 / Stable 121 / Watch 18 / Attention 9 (active = ink bg) · industry select · region select · search.
Table (min-width 1080, scroll box): Business (link + loan id) · Industry · region · Outstanding · Revenue vs prior period (coloured) · Cash coverage · Latest period · **Status · reason** (pill + muted reason, max-width 320) · Updated. Footer: "Showing n of N … sorted by status severity, then exposure" + definition of cash coverage.
Interactions: chips filter rows; URL `?status=`; row click → `/bank/borrowers/:id`.

## 08 `/bank/borrowers/:id` — Borrower profile (`reference/BorrowerProfile.dc.html`)
Breadcrumb. Header: name + pill "Attention · since 02 Oct 2026" + history ("previously Watch (18 Aug)"); actions Contact borrower, Request documents, **Record review outcome**.
**Loan details** panel: kv grid (loan, original/outstanding, installment + next due, term 11 paid/25 left, collateral, cash coverage 1.4× red with threshold) + 36-cell repayment strip (10 on time, 1 late red, 25 upcoming) with legend.
Left: **Why this borrower is under Attention** (4 alert rows: pill category · title · explanation with chip · date) → **Quarterly revenue and operating expenses** grouped bars Q4'25–Q3'26 + divider + **Cash coverage** line with dashed 1.5× threshold → **AI explanation** (bold lead sentence = the brief's example; 2 paragraphs with chips; amber "What the records don't show"; 4 numbered next steps).
Right: **Evidence** aside (default `rev`) · **How it developed** timeline (6 entries Jun→Today) · **Documents & previous assessments** list.

## 01m `/owner` at ≤480px — phone (`reference/OwnerMobile.dc.html`)
Order: strip → header (eyebrow business, title period, calendar button 44px) → **Cash balance hero** (34px, delta, "Why is it falling? →") → key figures list (3 rows) → Needs attention cards (3, tappable) → Cash in vs out mini chart → Ask panel (44px input + square accent button; horizontally scrolling chips) → bottom tab bar.
Not a shrunk desktop: no sidebar, no figure strip, one hero number, lists instead of tables.

## Journeys to keep clickable in the demo
A: `/owner` → Upload documents → `/owner/upload` → Continue → `/owner/health` → Ask → `/owner/cfo` → click chip → evidence pane.
B: `/bank` → Farovon Savdo → `/bank/applications/APP-2026-0931` → click 9 842.3 → evidence → SideNav Borrowers → `/bank/borrowers` → filter Attention → Zilola Mebel → `/bank/borrowers/L-2025-0417` → click chip → evidence.
