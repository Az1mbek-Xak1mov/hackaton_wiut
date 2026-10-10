import { defineComponent, h, computed, ref, type PropType, type VNode } from 'vue'
import EvidenceChip from './EvidenceChip.vue'
import { useEvidence } from '@/stores/evidence'
import { parseCited, parseWithKeys, type InlineNode } from './inline'
import { t, tn } from '@/i18n'

function renderNodes(nodes: InlineNode[]): (VNode | string)[] {
  return nodes.map((n) => {
    let v: VNode | string
    if (n.type === 'text') v = n.text
    else if (n.type === 'chip') v = h(EvidenceChip, { factKey: n.key, text: n.text, compact: n.compact, long: n.long })
    else v = h('span', { class: 'rule-tag', title: t('Reconciliation rule {id}', { id: n.id }) }, n.id)
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
    maxTrailing: { type: Number, default: 0 }, // 0 = show all chips that could not be placed in the text
  },
  setup(props) {
    const ev = useEvidence()
    const expanded = ref(false)
    const nodes = computed(() => {
      const base = parseCited(props.text, ev.facts)
      if (!props.keys.length) return base
      // explicit keys (finding evidence): place inside the text, else trail
      const textOnly = base.every((n) => n.type === 'text')
      if (textOnly) return parseWithKeys(props.text, props.keys, ev.facts)
      return [...base, { type: 'text', text: ' ' } as InlineNode, ...props.keys.map((k) => ({ type: 'chip', key: k, long: true }) as InlineNode)]
    })
    return () => {
      let list = nodes.value
      let hidden = 0
      if (props.maxTrailing > 0 && !expanded.value) {
        const longIdx = list.map((n, i) => (n.type === 'chip' && n.long ? i : -1)).filter((i) => i >= 0)
        if (longIdx.length > props.maxTrailing) {
          const drop = new Set(longIdx.slice(props.maxTrailing))
          hidden = drop.size
          list = list.filter((_, i) => !drop.has(i))
        }
      }
      const children = renderNodes(list)
      if (hidden)
        children.push(' ', h('button', { type: 'button', class: 'linkbtn more', onClick: (e: Event) => { e.stopPropagation(); expanded.value = true } }, tn(hidden, '+{n} more source', '+{n} more sources')))
      return h(props.tag, children)
    }
  },
})
