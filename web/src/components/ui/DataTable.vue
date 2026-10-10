<script setup lang="ts" generic="T extends Record<string, any>">
/**
 * Thin table wrapper: columns with optional right alignment; cells rendered through slots
 * named `cell-<key>` so pages can drop EvidenceChips into them.
 */
export interface Column {
  key: string
  label: string
  right?: boolean
  width?: string
}
defineProps<{ columns: Column[]; rows: T[]; minWidth?: string; hover?: boolean; rowKey?: (r: T, i: number) => string | number; label?: string }>()
const emit = defineEmits<{ (e: 'row-click', row: T): void }>()
</script>

<template>
  <div class="scrollbox">
    <table class="tbl" :class="{ hover }" :style="minWidth ? { minWidth } : undefined" :aria-label="label">
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key" :class="{ r: c.right }" :style="c.width ? { width: c.width } : undefined">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(r, i) in rows"
          :key="rowKey ? rowKey(r, i) : i"
          :class="{ clickable: hover }"
          @click="emit('row-click', r)"
        >
          <td v-for="c in columns" :key="c.key" :class="{ r: c.right, num: c.right }">
            <slot :name="`cell-${c.key}`" :row="r" :value="r[c.key]">{{ r[c.key] ?? '—' }}</slot>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length" class="muted"><slot name="empty">No rows.</slot></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
