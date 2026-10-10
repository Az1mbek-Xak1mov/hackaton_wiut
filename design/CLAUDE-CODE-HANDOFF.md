# Handing this design to Claude Code

## 0. What to put in the repo

```
your-repo/
  CLAUDE.md                 ← add the snippet below
  design/
    DESIGN.md               tokens, type, components, rules
    SCREENS.md              routes, layout, data, states, journeys
    demo-data.json          the synthetic dataset (numbers reconcile)
    reference/*.dc.html     10 artboards — real markup, read-only reference
    reference/exports/*.png optional: Share › Export from the canvas, one PNG per artboard
```

Commit `design/` first, then start Claude Code in the repo. Markup beats screenshots: Claude Code reads exact paddings, class names, SVG geometry and copy from the `.dc.html` files. PNGs are a secondary check for "does it look like this".

## 1. CLAUDE.md snippet

```md
## Design source of truth
- Read design/DESIGN.md and design/SCREENS.md before touching any UI.
- design/reference/*.dc.html are reference artboards (HTML+inline CSS+SVG) from the design canvas.
  They use a canvas runtime (<x-dc>, <sc-for>, {{holes}}) — do NOT copy them in; re-implement with our components,
  matching their structure, spacing values, copy and chart geometry.
- design/demo-data.json is the only demo dataset. Never invent numbers; render "n/a — upload X" states when data is absent.
- Status pills always carry a reason. No numeric credit score anywhere. The system never approves/rejects.
- Fonts: IBM Plex Sans (UI), IBM Plex Mono (quoted document values only). Tabular numerals everywhere.
- Palette is tokenised in design/DESIGN.md → put it in one CSS-variables file; no other colours.
- Charts: inline SVG components, ≤2 series, one axis, legend + latest-value labels; see DESIGN.md "Charts".
- Avoid: gradients, glows, glassmorphism, icon-per-heading, KPI card grids, chat bubbles, emoji.
```

## 2. Stack suggestion

Vue 3 + Vite + TypeScript (matches your other projects) or Next.js — either is fine; the design is framework-neutral.
Styling: plain CSS variables + small component CSS (the reference already is). Tailwind is OK if tokens are mapped in `tailwind.config` — don't let defaults leak (no `rounded-xl`, no `shadow-lg`, no `text-gray-500`).
Charts: hand-rolled SVG components (`BarGroupChart`, `LineChart`, `WaterfallRows`, `StackedBar`) — the reference geometry is simple and a charting library will fight the look.

## 3. Prompt sequence (one Claude Code session, phased)

**Phase 1 — foundation**
> Read design/DESIGN.md, design/SCREENS.md and skim design/reference/Main.dc.html and LoanReview.dc.html. Set up [stack]. Create `src/styles/tokens.css` from DESIGN.md tokens, load IBM Plex Sans/Mono, and build the shell: PrototypeStrip, TopBar(role), SideNav(role), AppLayout with the wrap-at-720px behaviour. Then the primitives: Panel, Pill (stable/watch/attn/neutral/info), Button (primary/secondary/sm), EvidenceChip, DataTable (th/td/.r/sum rows), Eyebrow, FigureStrip. Add a `/kit` route rendering every primitive (mirror design/reference/DesignSystem.dc.html). Stop and show me `/kit`.

**Phase 2 — data + evidence**
> Load design/demo-data.json via a typed `useDemoData()` store. Build `EvidencePane` (title, doc, confidence pill, Mono passage with highlighted hit, interpretation, related rows, actions) and a `useEvidence()` store so any EvidenceChip anywhere sets the selected key. Copy evidence texts from the `items` objects in reference/AICFO.dc.html, LoanReview.dc.html, BorrowerProfile.dc.html.

**Phase 3 — officer screens first (jury weight)**
> Build `/bank/applications/:id` from reference/LoanReview.dc.html and SCREENS.md §06, then `/bank`, `/bank/borrowers` (working status filter + `?status=` param), `/bank/borrowers/:id`. Charts as SVG components with the geometry from the reference files.

**Phase 4 — owner screens**
> Build `/owner`, `/owner/upload` (all five file states), `/owner/health`, `/owner/cfo` (scripted thread from reference/AICFO.dc.html; chips drive EvidencePane). Then the phone layout for `/owner` per reference/OwnerMobile.dc.html — a different composition at ≤480px, not a shrunk desktop.

**Phase 5 — journeys & QA**
> Wire journeys A and B from SCREENS.md end-to-end. Run through both at 1440 and 390 wide; screenshot each route with Playwright and compare against design/reference/exports (if present). Check: every status pill has reason text; no number appears that isn't in demo-data.json or computed from it; evidence chips open the pane; tab order and aria-labels on icon buttons.

**Later (real product)** — replace demo-data.json with the API: document upload → extraction service → records with (doc, page, line, passage, confidence) → every rendered figure carries its record id. The EvidenceChip/EvidencePane contract already assumes that shape.

## 4. Alternatives, ranked

1. **Repo folder + CLAUDE.md (this)** — best. Exact values, copy and structure; versioned with the code.
2. **Export PNGs/PDF from the canvas (Share › Export)** and attach to prompts — good for visual QA, poor as a build spec (Claude Code guesses px values).
3. **Paste the canvas link** — Claude Code can't open claude.ai artifact links in the terminal; don't rely on it.
4. **Describe it in prose** — the slowest and least faithful.

Tip: keep `design/` even after screens exist — when you ask Claude Code for a new screen later, point it at the folder and it will stay on-system.
