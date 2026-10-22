import i18n from '../../i18n';

export const API_BASE = '/api';

/** Error code the AI-advisor routes return when no LLM API key is configured. */
export const LLM_NOT_CONFIGURED = 'llm_not_configured';

export async function safeReadError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    // Rule 12 envelope: {"error": {"code", "message"}}; FastAPI default: {"detail"}.
    const envelope = (data as { error?: { code?: string; message?: string } }).error;
    if (envelope?.code === LLM_NOT_CONFIGURED) return i18n.t('errors:aiAdvisor.llmNotConfigured');
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
    return envelope?.message || fallback;
  } catch {
    return fallback;
  }
}
