import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import { getAuth } from '@/api/client'

/**
 * Page images may need the bearer token (bank documents). <img> cannot send headers,
 * so fetch the image and hand the browser a blob URL. Falls back to the plain URL.
 */
export function useAuthedImage(url: Ref<string | null | undefined>) {
  const src = ref<string | null>(null)
  const loading = ref(false)
  const failed = ref(false)
  let current: string | null = null
  let inflight: AbortController | null = null

  function revoke() {
    if (current) URL.revokeObjectURL(current)
    current = null
  }

  watch(
    url,
    async (u) => {
      revoke()
      inflight?.abort() // a page image can be several hundred KB: don't let a stale one hold the connection
      inflight = null
      failed.value = false
      if (!u) {
        src.value = null
        return
      }
      loading.value = true
      try {
        const headers: Record<string, string> = {}
        const a = getAuth()
        let target = u
        if (a?.access) {
          headers.Authorization = `Bearer ${a.access}`
          target = `${u}${u.includes('?') ? '&' : '?'}token=${encodeURIComponent(a.access)}`
        }
        inflight = new AbortController()
        const res = await fetch(target, { headers, signal: inflight.signal })
        if (!res.ok) throw new Error(String(res.status))
        const blob = await res.blob()
        if (url.value !== u) return
        current = URL.createObjectURL(blob)
        src.value = current
      } catch {
        if (url.value === u) {
          failed.value = true
          src.value = null
        }
      } finally {
        if (url.value === u) loading.value = false
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    inflight?.abort()
    revoke()
  })
  return { src, loading, failed }
}
