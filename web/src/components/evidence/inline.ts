// Splits text into plain runs and evidence chips. A chip replaces the first occurrence of the
// fact's display (or printed) string in the text; if the value is not in the text, the chip is
// appended where the citation stood. Nothing here computes a number.
import type { Fact } from '@/api/types'

export type InlineNode =
  | { type: 'text'; text: string; bold?: boolean }
  | { type: 'chip'; key: string; text?: string; bold?: boolean; compact?: boolean; long?: boolean }
  | { type: 'rule'; id: string; bold?: boolean }

function esc(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function candidates(f: Fact | undefined): string[] {
  if (!f) return []
  const out = new Set<string>()
  const add = (s: string | null | undefined) => {
    if (!s) return
    const t = s.trim()
    if (!t) return
    out.add(t)
    out.add(t.replace(/^-/, '−'))
    out.add(t.replace(/^−/, '-'))
    out.add(t.replace(/ /g, ' '))
    out.add(t.replace(/ /g, ' '))
  }
  add(f.display)
  add(f.printed)
  return [...out].filter(Boolean).sort((a, b) => b.length - a.length)
}

function findIn(text: string, cand: string): number {
  // the value must not be part of a longer number
  const re = new RegExp(`(?<![\\d.,])${esc(cand)}(?![\\d]|[.,]\\d)`)
  const m = re.exec(text)
  return m ? m.index : -1
}

/** Place chips for `keys` inside `nodes` (text runs), mutating a copy. */
/** Trailing chips (value not found in the text): 'compact' for narrative cites, 'long' for evidence lists. */
export function placeChips(nodes: InlineNode[], keys: string[], facts: Record<string, Fact>, trailing_: 'compact' | 'long' | 'plain' = 'plain'): InlineNode[] {
  let out = nodes.slice()
  const trailing: InlineNode[] = []
  for (const key of keys) {
    const f = facts[key]
    let placed = false
    for (const cand of candidates(f)) {
      for (let i = out.length - 1; i >= 0 && !placed; i--) {
        const n = out[i]
        if (n.type !== 'text') continue
        const idx = findIn(n.text, cand)
        if (idx < 0) continue
        const before = n.text.slice(0, idx)
        const after = n.text.slice(idx + cand.length)
        const repl: InlineNode[] = []
        if (before) repl.push({ type: 'text', text: before })
        repl.push({ type: 'chip', key, text: cand })
        if (after) repl.push({ type: 'text', text: after })
        out = [...out.slice(0, i), ...repl, ...out.slice(i + 1)]
        placed = true
      }
      if (placed) break
    }
    if (!placed) trailing.push({ type: 'chip', key, compact: trailing_ === 'compact', long: trailing_ === 'long' })
  }
  if (trailing.length) {
    out.push({ type: 'text', text: ' ' })
    trailing.forEach((t, i) => {
      if (i) out.push({ type: 'text', text: ' ' })
      out.push(t)
    })
  }
  return out
}

const CITE_RE = /\[((?:[A-Za-z]{1,3}_[A-Za-z0-9]+|R\d{2}(?:-\d+)?|M\d{2}(?:-\d+)?)(?:\s*[,;]\s*(?:[A-Za-z]{1,3}_[A-Za-z0-9]+|R\d{2}(?:-\d+)?|M\d{2}(?:-\d+)?))*)\]/g

/** Parse a line of narrative text with [f_…] citations into inline nodes (bold handled after). */
export function parseCited(text: string, facts: Record<string, Fact>): InlineNode[] {
  const nodes: InlineNode[] = []
  let segment: InlineNode[] = []
  let last = 0
  const matches = [...text.matchAll(CITE_RE)]
  // merge citation groups separated only by whitespace: "[f_a][f_b]" or "[f_a] [f_b]"
  const groups: { start: number; end: number; ids: string[] }[] = []
  for (const m of matches) {
    const ids = m[1].split(/\s*[,;]\s*/)
    const start = m.index!
    const end = start + m[0].length
    const prev = groups[groups.length - 1]
    if (prev && /^\s*$/.test(text.slice(prev.end, start))) {
      prev.end = end
      prev.ids.push(...ids)
    } else groups.push({ start, end, ids })
  }
  for (const g of groups) {
    const chunk = text.slice(last, g.start).replace(/\s+$/, '')
    if (chunk) segment.push({ type: 'text', text: chunk })
    const factIds = g.ids.filter((id) => !/^[RM]\d{2}/.test(id))
    const ruleIds = g.ids.filter((id) => /^[RM]\d{2}/.test(id))
    segment = placeChips(segment, factIds, facts, 'compact')
    for (const r of ruleIds) segment.push({ type: 'text', text: ' ' }, { type: 'rule', id: r })
    nodes.push(...segment)
    segment = []
    last = g.end
  }
  const rest = text.slice(last)
  if (rest) nodes.push({ type: 'text', text: rest })
  return applyBold(nodes)
}

/** Text with an explicit list of evidence keys (e.g. a finding's detail + evidence). */
export function parseWithKeys(text: string, keys: string[], facts: Record<string, Fact>): InlineNode[] {
  return applyBold(placeChips(text ? [{ type: 'text', text }] : [], keys, facts, 'long'))
}

export function applyBold(nodes: InlineNode[]): InlineNode[] {
  let bold = false
  const out: InlineNode[] = []
  for (const n of nodes) {
    if (n.type !== 'text') {
      out.push({ ...n, bold })
      continue
    }
    const parts = n.text.split('**')
    parts.forEach((p, i) => {
      if (i > 0) bold = !bold
      if (p) out.push({ type: 'text', text: p, bold })
    })
  }
  return out
}

export function citedKeys(text: string): string[] {
  const keys: string[] = []
  for (const m of text.matchAll(CITE_RE)) {
    for (const id of m[1].split(/\s*[,;]\s*/)) if (!/^[RM]\d{2}/.test(id)) keys.push(id)
  }
  return keys
}
