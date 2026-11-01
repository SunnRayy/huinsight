import { useEffect, useState } from 'react';
import { getLlmStatus } from '../../src/services/api';

// One request per page load: every Generate button reads the same answer.
let statusPromise: Promise<{ configured: boolean }> | null = null;

/** Resets the cached status (tests only). */
export function resetLlmStatusCache(): void {
  statusPromise = null;
}

/**
 * Whether an LLM key is configured on the backend.
 * `null` while loading — callers treat that as "maybe", never as disabled,
 * so a slow status call cannot lock the buttons.
 */
export function useLlmStatus(): boolean | null {
  const [configured, setConfigured] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    // Any failure (network, missing endpoint) means "unknown": never lock the buttons.
    if (!statusPromise) statusPromise = Promise.resolve().then(() => getLlmStatus()).catch(() => ({ configured: true }));
    statusPromise.then(s => { if (!cancelled) setConfigured(s.configured); });
    return () => { cancelled = true; };
  }, []);
  return configured;
}
