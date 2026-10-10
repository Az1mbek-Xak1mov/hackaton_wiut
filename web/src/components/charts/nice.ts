// Axis helpers for the hand-rolled SVG charts (presentation only).
export function niceMax(v: number): number {
  if (!(v > 0)) return 1
  const exp = Math.pow(10, Math.floor(Math.log10(v)))
  const f = v / exp
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10
  return nf * exp
}

export function fmtAxis(v: number): string {
  const abs = Math.abs(v)
  const s = abs >= 100 ? Math.round(abs).toString() : abs >= 10 ? (Math.round(abs * 10) / 10).toString() : (Math.round(abs * 100) / 100).toString()
  const [i, d] = s.split('.')
  const grouped = i.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return (v < 0 ? '−' : '') + (d ? `${grouped}.${d}` : grouped)
}
