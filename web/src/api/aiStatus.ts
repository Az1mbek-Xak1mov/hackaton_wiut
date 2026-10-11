// Why an AI summary is not shown (backend `llm_status`): switched off, no key, key rejected, no credits, error.
// The English texts match app/modules/llm/provider.py STATUS_TEXT so the backend text translates by key.
import { t } from '@/i18n'

export type LlmStatus = 'ok' | 'off' | 'no_key' | 'no_credits' | 'error'

const TAIL = ' All figures, checks and ratios above are still computed from the documents.'
export const AI_STATUS_TEXT: Record<string, string> = {
  off: 'AI summary is switched off.' + TAIL,
  no_key: 'AI summary is off: no AI key is configured.' + TAIL,
  bad_key: 'AI summary is off: the AI service rejected the API key.' + TAIL,
  no_credits: 'AI summary is off: the AI service has no credits left (API key quota used up).' + TAIL,
  error: 'AI summary is unavailable: the AI service did not answer.' + TAIL,
}

/** Translated plain message for a non-ok status; '' when the AI is working (or the status is unknown). */
export function aiStatusMessage(code?: string | null, text?: string | null): string {
  if (!code || code === 'ok') return ''
  return t(text || AI_STATUS_TEXT[code] || AI_STATUS_TEXT.error)
}
