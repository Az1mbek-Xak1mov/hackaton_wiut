import { defineComponent, h, computed, type VNode } from 'vue'
import InlineEvidence from './InlineEvidence'

interface Block {
  kind: 'p' | 'ul' | 'ol' | 'h'
  lines: string[]
}

const LI_RE = /^\s*[-*•]\s+/
const OL_RE = /^\s*\d+[.)]\s+/
const H_RE = /^#{1,4}\s+/

function parseBlocks(md: string): Block[] {
  const blocks: Block[] = []
  const paras = md.replace(/\r\n/g, '\n').split(/\n\s*\n/)
  for (const raw of paras) {
    const lines = raw.split('\n').map((l) => l.trimEnd()).filter((l) => l.trim())
    // group consecutive lines of the same kind inside a paragraph block
    let cur: Block | null = null
    const flush = () => {
      if (cur) blocks.push(cur)
      cur = null
    }
    for (const line of lines) {
      if (H_RE.test(line)) {
        flush()
        blocks.push({ kind: 'h', lines: [line.replace(H_RE, '')] })
      } else if (LI_RE.test(line)) {
        if (!cur || cur.kind !== 'ul') { flush(); cur = { kind: 'ul', lines: [] } }
        cur.lines.push(line.replace(LI_RE, ''))
      } else if (OL_RE.test(line)) {
        if (!cur || cur.kind !== 'ol') { flush(); cur = { kind: 'ol', lines: [] } }
        cur.lines.push(line.replace(OL_RE, ''))
      } else {
        if (!cur || cur.kind !== 'p') { flush(); cur = { kind: 'p', lines: [''] } }
        cur.lines[0] = cur.lines[0] ? `${cur.lines[0]} ${line.trim()}` : line.trim()
      }
    }
    flush()
  }
  return blocks
}

/** Renders the verified narrative markdown; every [f_…] citation becomes an EvidenceChip. */
export default defineComponent({
  name: 'NarrativeText',
  props: { markdown: { type: String, default: '' } },
  setup(props) {
    const blocks = computed(() => parseBlocks(props.markdown || ''))
    return () =>
      h(
        'div',
        { class: 'narrative' },
        blocks.value.map((b): VNode => {
          if (b.kind === 'h') return h('div', { class: 'eyebrow' }, b.lines[0])
          if (b.kind === 'ul' || b.kind === 'ol')
            return h(
              b.kind,
              { class: b.kind === 'ol' ? 'steps' : 'bullets' },
              b.lines.map((l) => h('li', [h(InlineEvidence, { text: l })])),
            )
          return h('p', [h(InlineEvidence, { text: b.lines[0] })])
        }),
      )
  },
})
