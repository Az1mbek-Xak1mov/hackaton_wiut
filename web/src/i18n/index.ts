// Interface language (UZ | RU | EN). Strings are keyed by their English text, so a missing
// translation falls back to English. Document text and backend-generated titles are never translated.
import { ref } from 'vue'
import ru from './ru'
import uz from './uz'

export type Lang = 'en' | 'ru' | 'uz'
const LS_KEY = 'converza.lang'
const DICTS: Record<Lang, Record<string, string>> = { en: {}, ru, uz }

function initial(): Lang {
  try {
    const v = localStorage.getItem(LS_KEY)
    if (v === 'en' || v === 'ru' || v === 'uz') return v
  } catch {
    /* storage unavailable */
  }
  return 'en'
}

export const lang = ref<Lang>(initial())
if (typeof document !== 'undefined') document.documentElement.lang = lang.value === 'uz' ? 'uz-Latn' : lang.value

export function setLang(l: Lang) {
  lang.value = l
  try {
    localStorage.setItem(LS_KEY, l)
  } catch {
    /* keep in memory only */
  }
  document.documentElement.lang = l === 'uz' ? 'uz-Latn' : l
}

/** Translate an English UI string; `{name}` placeholders are filled from params. */
export function t(en: string, params?: Record<string, string | number | null | undefined>): string {
  const s = DICTS[lang.value][en] ?? en
  if (!params) return s
  return s.replace(/\{(\w+)\}/g, (m, k) => (params[k] == null ? m : String(params[k])))
}

/** Plural helper: picks the English singular/plural key, translated (RU/UZ forms live in the dictionaries). */
export function tn(n: number, one: string, many: string, params: Record<string, string | number> = {}): string {
  if (lang.value === 'ru') {
    const n10 = n % 10
    const n100 = n % 100
    const form = n10 === 1 && n100 !== 11 ? one : n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14) ? `${many}#few` : many
    const s = DICTS.ru[form] ?? DICTS.ru[many] ?? (form.endsWith('#few') ? many : form)
    return s.replace(/\{(\w+)\}/g, (m, k) => (k === 'n' ? String(n) : params[k] == null ? m : String(params[k])))
  }
  return t(n === 1 ? one : many, { n, ...params })
}

const MONTHS: Record<Lang, string[]> = {
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  ru: ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
  uz: ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'],
}

export function monthName(i: number): string {
  return MONTHS[lang.value][i] ?? MONTHS.en[i]
}
