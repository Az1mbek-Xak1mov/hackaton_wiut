<script setup lang="ts">
import Panel from '@/components/ui/Panel.vue'
import Pill from '@/components/ui/Pill.vue'
import Btn from '@/components/ui/Btn.vue'
import Eyebrow from '@/components/ui/Eyebrow.vue'
import FigureStrip from '@/components/ui/FigureStrip.vue'
import FigureCell from '@/components/ui/FigureCell.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import Dropzone from '@/components/ui/Dropzone.vue'
import DataTable from '@/components/ui/DataTable.vue'

const SWATCHES = [
  ['ground', '--bg'], ['surface', '--surface'], ['surface-2', '--surface-2'], ['border', '--border'],
  ['ink', '--ink'], ['ink-muted', '--ink-muted'], ['accent', '--accent'], ['series-compare', '--series-compare'],
  ['status-stable', '--stable-bg'], ['status-watch', '--watch-bg'], ['status-attention', '--attn-bg'], ['evidence-highlight', '--highlight'],
]
const cols = [
  { key: 'line', label: 'Line' },
  { key: 'a', label: 'Period A', right: true },
  { key: 'b', label: 'Period B', right: true },
]
const rows = [
  { line: 'Specimen row', a: '1 234.5', b: '1 200.0' },
  { line: 'Another row', a: '67.8', b: '70.1' },
]
</script>

<template>
  <div class="page" style="max-width: 1440px">
    <div class="page-head">
      <div>
        <Eyebrow>Converza · component kit</Eyebrow>
        <h1 style="margin-top: 4px">Calm, evidential, dense where it has to be</h1>
        <p class="meta" style="max-width: 760px">Every primitive used by the app, rendered from the same components. Values on this page are specimens for layout only — they are not data.</p>
      </div>
      <div class="actions"><Btn to="/analyse">Analyse a document</Btn><Btn to="/bank">Officer screens</Btn></div>
    </div>

    <div class="grid-2" style="grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr))">
      <Panel title="Typography — IBM Plex Sans + IBM Plex Mono" pad>
        <div class="stack">
          <div class="spec"><span class="muted">Page title · 22/600</span><span style="font-size: 22px; font-weight: 600; letter-spacing: -.01em">Page title</span></div>
          <div class="spec"><span class="muted">Section · 15/600</span><span style="font-size: 15px; font-weight: 600">Is revenue growing faster than expenses?</span></div>
          <div class="spec"><span class="muted">Key figure · 26/500</span><span class="num" style="font-size: 26px; font-weight: 500">1 234.5 <span class="muted" style="font-size: 14px; font-weight: 400">mln UZS</span></span></div>
          <div class="spec"><span class="muted">Eyebrow · 11/600 caps</span><Eyebrow>Needs attention</Eyebrow></div>
          <div class="spec"><span class="muted">Source passage · Mono 12</span><span class="passage" style="padding: 4px 8px">010 Чистая выручка <span class="hit">1 234 567</span></span></div>
        </div>
      </Panel>

      <Panel title="Color tokens" pad>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 10px 16px">
          <div v-for="[name, v] in SWATCHES" :key="name" class="row" style="flex-wrap: nowrap">
            <span class="sw" :style="{ background: `var(${v})` }"></span>
            <div><div style="font-weight: 500">{{ name }}</div><div class="muted mono" style="font-size: 12px">{{ v }}</div></div>
          </div>
        </div>
      </Panel>

      <Panel title="Buttons & form controls" pad>
        <div class="stack">
          <div class="row"><Btn primary>Primary action</Btn><Btn>Secondary</Btn><Btn sm>Small</Btn><Btn disabled>Disabled</Btn><a href="#kit">Text link →</a></div>
          <div class="row">
            <select class="select"><option>Period</option></select>
            <input class="input" type="search" placeholder="Search borrower, STIR…" style="width: 220px" />
            <div class="seg"><button type="button">UZ</button><button type="button">RU</button><button type="button" class="on">EN</button></div>
          </div>
          <div class="row"><button type="button" class="chip on">All <span class="n">12</span></button><button type="button" class="chip">Watch <span class="n">3</span></button></div>
        </div>
      </Panel>

      <Panel title="Status indicators — always with a reason" pad>
        <table class="tbl">
          <thead><tr><th>Pill</th><th>Used for</th></tr></thead>
          <tbody>
            <tr><td><Pill kind="stable">Stable</Pill> <Pill kind="stable">Analyzed</Pill></td><td class="muted">Within thresholds; document processed</td></tr>
            <tr><td><Pill kind="watch">Watch</Pill> <Pill kind="watch">Needs clarification</Pill></td><td class="muted">One indicator moved; low-confidence field</td></tr>
            <tr><td><Pill kind="attn">Attention</Pill> <Pill kind="attn">Could not analyze</Pill></td><td class="muted">Two indicators moved; failed processing</td></tr>
            <tr><td><Pill kind="info">In review</Pill> <Pill kind="neutral">Missing</Pill></td><td class="muted">Workflow state, absence of data</td></tr>
          </tbody>
        </table>
        <p class="muted" style="margin-top: 8px">No numeric score is shown anywhere in the product.</p>
      </Panel>

      <Panel title="Evidence references & AI conversation" pad>
        <div class="stack">
          <p>A dashed chip marks any figure that can be traced: <button type="button" class="ev num">1 234.5</button> or <button type="button" class="ev">Bank statement · row 18</button>. Clicking opens the evidence pane.</p>
          <div class="msg">
            <span class="av ai">AI</span>
            <div class="ans">
              <p><strong>Direct answer first</strong>, in one sentence with the key figure.</p>
              <p class="muted">Then the supporting table, each row pointing at a record, then "what I can't see", then numbered next steps.</p>
              <div class="note"><strong>What I can't see.</strong> States the missing document and what uploading it would change.</div>
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="Tables, figures & progress" pad>
        <div class="stack">
          <DataTable :columns="cols" :rows="rows" />
          <FigureStrip>
            <FigureCell eyebrow="Specimen figure" value="1 234.5" unit="mln UZS">delta line</FigureCell>
            <FigureCell eyebrow="Flagged cell" value="12.3" unit="mln UZS" flagged>reason under the pill</FigureCell>
          </FigureStrip>
          <div class="row" style="flex-wrap: nowrap"><ProgressBar :value="68" width="120px" /><span class="muted" style="font-size: 12px">Processing — says what step it is on</span></div>
        </div>
      </Panel>

      <Panel title="Upload, empty, error states" pad>
        <div class="stack">
          <Dropzone compact />
          <div class="row"><Pill kind="attn">Could not analyze</Pill><span class="muted" style="font-size: 12px">Names the cause and offers two ways out</span></div>
          <div><span class="num muted" style="font-weight: 600">n/a</span> <span style="font-weight: 500">Inventory</span> <span class="muted" style="font-size: 12px">— upload Форма 1 to include</span></div>
        </div>
      </Panel>
    </div>
  </div>
</template>

<style scoped>
.spec { display: grid; grid-template-columns: 170px 1fr; gap: 12px; align-items: baseline; padding: 6px 0; border-bottom: 1px solid var(--border-row); }
.spec:last-child { border-bottom: 0; }
.sw { width: 32px; height: 32px; border-radius: 4px; border: 1px solid var(--border); flex: none; }
@media (max-width: 720px) { .spec { grid-template-columns: 1fr; gap: 2px; } }
</style>
