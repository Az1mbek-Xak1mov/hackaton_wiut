// One build, two apps: the bank officer app on app.converza.uz, the business owner app everywhere else.
// Local development can switch with localStorage `converza.surface` = "bank" | "owner".
export type Surface = 'owner' | 'bank'

function detect(): Surface {
  if (typeof window === 'undefined') return 'owner'
  if (window.location.hostname.startsWith('app.')) return 'bank'
  try {
    const o = localStorage.getItem('converza.surface')
    if (o === 'bank' || o === 'owner') return o
  } catch {
    /* storage unavailable */
  }
  return 'owner'
}

export const surface: Surface = detect()
export const OTHER_SURFACE_URL = surface === 'bank' ? 'https://converza.uz' : 'https://app.converza.uz'
