import React from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Shown once per AI page when no LLM key is configured. Points at the
 * quickstart by path rather than a URL: a self-hosted install (or a fork)
 * should not link out to one particular upstream repository.
 */
export const LlmKeyNotice: React.FC = () => {
  const { t } = useTranslation('aiAdvisor');
  return (
    <div
      role="status"
      data-testid="llm-key-notice"
      className="flex items-start gap-3 rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 px-4 py-3"
    >
      <span className="material-symbols-outlined !text-[18px] text-amber-600 dark:text-amber-400 mt-0.5">key_off</span>
      <div className="text-sm">
        <p className="font-medium text-amber-900 dark:text-amber-200">{t('llmKey.title')}</p>
        <p className="text-amber-800/80 dark:text-amber-200/70 mt-0.5">{t('llmKey.body')}</p>
        <p className="text-amber-800/80 dark:text-amber-200/70 mt-1 text-xs">
          {t('llmKey.howTo')} <code className="font-mono">docs/quickstart.md</code>
        </p>
      </div>
    </div>
  );
};
