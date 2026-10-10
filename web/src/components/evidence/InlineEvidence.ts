import { defineComponent, h, computed, type PropType, type VNode } from 'vue'
import EvidenceChip from './EvidenceChip.vue'
import { useEvidence } from '@/stores/evidence'
import { parseCited, parseWithKeys, type InlineNode } from './inline'

function renderNodes(nodes: InlineNode[]): (VNode | string)[] {
  return nodes.map((n) => {
    let v: VNode | string
    if (n.type === 'text') v = n.text
    else if (n.type === 'chip') v = h(EvidenceChip, { factKey: n.key, text: n.text, compact: n.compact, long: n.long })
    else v = h('span', { class: 'rule-tag', title: `Reconciliation rule ${n.id}` }, n.id)
    return n.bold ? h('strong', v) : v
  })
}

/** Inline text that may contain [f_…] citations and/or an explicit evidence key list. */
export default defineComponent({
  name: 'InlineEvidence',
  props: {
    text: { type: String, default: '' },
    keys: { type: Array as PropType<string[]>, default: () => [] },
    tag: { type: String, default: 'span' },
  },
  setup(props) {
    const ev = useEvidence()
    const nodes = computed(() => {
      const base = parseCited(props.text, ev.facts)
      if (!props.keys.length) return base
      // explicit keys (finding evidence): place inside the text, else trail
      const textOnly = base.every((n) => n.type === 'text')
      if (textOnly) return parseWithKeys(props.text, props.keys, ev.facts)
      return [...base, { type: 'text', text: ' ' } as InlineNode, ...props.keys.map((k) => ({ type: 'chip', key: k, long: true }) as InlineNode)]
    })
    return () => h(props.tag, renderNodes(nodes.value))
  },
})
