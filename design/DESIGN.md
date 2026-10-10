# Sarhisob — design system (handoff for implementation)

Source of truth: `reference/*.dc.html` (one file per screen, self-contained HTML + inline styles + inline SVG).
These are **reference markup, not runnable pages** — they use a canvas runtime (`<x-dc>`, `<sc-for>`, `{{ }}` holes).
Read them for structure, spacing, copy and exact values; re-implement with real components.

## Tokens

```css
:root{
  /* ground & surfaces */
  --bg:#F6F4EF; --surface:#FFFFFF; --surface-2:#FBFAF7;
  --border:#E3DFD6; --border-row:#EEEBE4; --border-strong:#D8D3C8;
  /* ink */
  --ink:#1B1A17; --ink-2:#44403A; --ink-muted:#66615A;   /* muted = 5.6:1 on bg */
  /* accent */
  --accent:#0F6E63; --accent-hover:#0B5A51; --accent-tint:#E8F1EF; --accent-border:#8FB5AE;
  --accent-panel-border:#C9DDD9; --accent-panel-bg:#FBFDFC;
  /* chart */
  --series-1:#0F6E63; --series-compare:#A39B8B; --series-compare-mid:#5E9B92;
  /* status (bg / text / chart mark) */
  --stable-bg:#E8F1EF; --stable-fg:#0B5A51; --stable-mark:#0F6E63;
  --watch-bg:#FBEFD9;  --watch-fg:#8A4B06;  --watch-mark:#D9A441;
  --attn-bg:#FBE5E1;   --attn-fg:#9B2318;   --attn-mark:#C2410C;
  --neutral-bg:#EFECE5; --neutral-fg:#44403A;
  --info-bg:#E6ECF7;   --info-fg:#2B4C8C;      /* workflow state, not risk */
  /* callouts */
  --note-bg:#FBF7EE; --note-border:#E8D8B5;     /* "what I can't see", estimates */
  --highlight:#FFF1B8; --highlight-underline:#D9A441; /* matched passage in evidence */
  /* radii */
  --r-panel:6px; --r-control:5px; --r-pill:4px; --r-chip:3px; --r-phone-card:8px;
}
```

Fonts (Google Fonts): `IBM Plex Sans` 400/500/600 for all UI; `IBM Plex Mono` 400/500 **only** for values quoted from a source document (passages, extracted raw numbers, file names).
All numerals: `font-variant-numeric: tabular-nums`.

## Type scale

| Role | Size / weight | Notes |
|---|---|---|
| Page title | 22 / 600, letter-spacing −.01em (officer: 20) | one per screen |
| Section heading | 15 / 600 (officer: 14) | phrased as the question the panel answers |
| Key figure | 26 / 500, −.01em (phone hero: 34) | unit in 14/400 muted after it |
| Body | 14 (owner) / 13 (officer) | line-height 1.45 |
| Table | 12.5–13 | header 11/600 uppercase .05em muted |
| Eyebrow | 11 / 600 uppercase .06em muted | |
| Source passage | Mono 12, lh 1.55, `white-space: pre-wrap` | on surface-2 with border |

## Spacing & layout

- Scale 4 · 8 · 12 · 16 · 20 · 24 · 28. Panel padding 16–20 (owner) / 12–14 (officer). Grid gap 20 / 16.
- Shell: prototype strip 28px (amber) → top bar 52px (white, bottom border) → body = side nav 220px (surface-2, right border) + main (padding 24px 28px owner / 20px 24px officer). Page width 1280–1440.
- Side nav collapses above content at ≤720px (`flex-wrap`, `flex: 999 1 560px` on main). Never sticky / 100vh.
- Two-pane review (LoanReview, BorrowerProfile, AICFO): analysis column `flex:1 1 520px`, evidence pane `flex:0 1 400–420px`, `position:sticky; top:16px`, wraps underneath on narrow.
- Owner phone: single column, hero figure first, cards radius 8, 44px targets, bottom tab bar (Overview · Upload · Health · AI CFO). No fake status bar.
- Officer is desktop-first; wide tables live in an `overflow-x:auto` box with `min-width`.

## Number & language formatting

- Currency UZS. Thousands separator = space. Headline/table values in **mln UZS, 1 decimal** ("1 284.5"), unit shown once per panel or in column header.
- Raw document values keep full digits as printed ("9 842 316", thousand UZS) and are Mono.
- Deltas: `+6.2%` / `−27.0%` (true minus sign). Colour only when meaningful: up-good `--stable-fg`, up-bad/warning `--watch-fg`, down-bad `--attn-fg`, flat muted.
- Dates `15 Oct 2026`, short `15 Oct`. Periods `Sep 2026`, `Q3 2026`, `H1 2026`.
- UI language switch UZ | RU | EN (segmented control in top bar, 28px). Interface language is independent of document language; document passages stay in their original Uzbek/Russian.

## Components

**Panel** — surface, 1px border, r-panel. Header row: heading left, muted 12px context right (`justify-content: space-between; align-items: baseline; flex-wrap`).

**Figure strip** — one panel, `grid-template-columns: repeat(auto-fit, minmax(220px,1fr))`, cells divided by 1px `--border-row` left border (becomes top border when stacked). Cell = eyebrow, big number + unit, delta line. A flagged cell gets `--note-bg` background and a status pill in the eyebrow row.

**Pill** — inline-flex, 2px 8px (officer 1px 7px), r-pill, 12/500, lh 18, nowrap. Variants stable / watch / attn / neutral / info. **Rule: a status pill is never shown without its reason text directly beneath or beside it.** Statuses are "illustrative monitoring indicators" — never a numeric score.

**Button** — h36 (sm h30 / officer h34, sm h28), 0 14px, r-control, 13/500. Secondary: white + `--border-strong`. Primary: accent bg + white. Disabled: opacity .5. One primary per screen. Real `<button>`/`<a>`; icon-only buttons need `aria-label`.

**Evidence chip (`.ev`)** — the signature element. Inline-flex, 0 6px, r-chip, white bg, **1px dashed `--accent-border`**, text `--stable-fg`, inherits font size; hover `--accent-tint`. Used on any figure or claim that can be traced to a record. Click → evidence pane shows: document · page/line · matched passage (Mono, matched text highlighted `--highlight` with 2px underline `--highlight-underline`) · interpretation · related rows table · actions (Open source document / Mark verified / Correct value / Flag incorrect). Plain numbers without a chip are computed from chipped ones.

**Table (`.tbl`)** — collapse, 12.5–13px; th 11/600 uppercase muted, padding 8–10px, bottom border; td padding 8–11px, `--border-row`; last row no border; `.r` right-aligned numerics; sum rows 600 weight, `--border-strong` top, surface-2 bg; officer rows hover surface-2.

**Side nav** — items h36–38, 0 12px, r-control, 13/500, icon 16px stroke-2 inline SVG; active = accent-tint bg + stable-fg; officer items carry a count badge (11/600, neutral bg, r 9).

**Top bar** — logo mark (22px square, accent on owner side / ink on officer side, chart-line glyph) + wordmark 15/600 + role pill; right: language segmented control, role-switch text link, 30px avatar circle.

**Prototype strip** — 28px, `--watch-bg`/`--watch-fg`, 12/500, info icon + sentence stating what is scripted vs interactive. Keep in the demo build; remove for production.

**Ranked attention item** — grid `22px 1fr auto`; rank square 22px ink bg white 12/600; title 500, muted 13 detail, row of evidence chips; status pill right.

**Waterfall row (`.wf`)** — grid `150px 1fr 90px`; 14px track with proportional bar (ink for opening/closing, series-1 for inflow, series-compare for outflows); value right-aligned tabular.

**Timeline (`.tl`)** — grid `84px 14px 1fr`; 10px dot with status colour, 2px connector `--border-row`.

**Upload** — dropzone 1.5px dashed `--border-strong`, surface-2, 32px padding, centered; real `<input type=file>` behind a labelled button. File row: 32×38 file-type badge, Mono filename, size/time muted. Statuses: Analyzed (stable) · progress bar 6px (processing, with step text) · Needs clarification (watch, "3 fields <80%") · Could not analyze (attn, cause + two exits: Re-upload / Enter manually).

**Clarification card** — bordered box, title + source ref, muted question, row of small buttons (candidate values) or select + apply.

**AI message** — 28px round avatar "AI" accent bg; answer panel: 1) bold one-sentence direct answer with key figure, 2) supporting table/bridge with a Record column of chips, 3) optional amber `--note-bg` box "**What I can't see.** …" naming missing data, 4) numbered next steps (20px numbered squares), cheapest first. User turn: 28px grey avatar with initials, 500 weight text. No bubbles, no greeting, no emoji. Composer: 40px input + primary Ask; suggestion chips h30–32 r16.

**Charts** (inline SVG, `role="img" aria-label` with the data in words):
- ≤2 series: series-1 for "ours/now", series-compare for the comparison. One y-axis. Grid lines `--border-row` only. Axis labels 11px muted. Direct labels on latest values only (ink), legend above right.
- Bars rx 3, width 32 (6 groups) / 48 (4 groups), 4px gap in a group. Lines 2px, points r4 white-filled, latest point r5 filled.
- Thresholds: dashed 1px `--attn-mark` with label. Status colours appear only as thresholds / status counts, never as a third series.
- Every chart heading is the business question it answers.

## Rules the jury will notice

1. No invented data: unavailable → explicit "n/a — upload X to include" row.
2. Every AI statement traces to a chip; "what I can't see" box when records are insufficient.
3. The system never approves/rejects: footer line "The officer's decision and reasoning are recorded with the evidence reviewed."
4. Colour = meaning. Default state is unmarked.
5. No gradients, glows, glassmorphism, icon-per-heading, KPI-card grids, floating chat bubbles.
