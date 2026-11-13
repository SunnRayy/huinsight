import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { InsightItem } from '../../src/services/api';
import { promoteInsight, addValidatedCase, setRuleLayer } from '../../src/services/api';
import { useLanguage } from '../../src/context/useLanguage';
import { formatDate } from '../../src/utils/formatMoney';
import { ChipBtn } from '../operations';
import { SimilarInsightsPanel } from './SimilarInsightsPanel';

interface InsightManagerProps {
  insights: InsightItem[];
  onRefresh: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  raw: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  recurring: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  validated: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  principle: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  deprecated: 'bg-slate-50 text-slate-400',
};

const NEXT_STATUS: Record<string, 'recurring' | 'validated' | 'principle'> = {
  raw: 'recurring', recurring: 'validated', validated: 'principle',
};
const CASES_TO_PROMOTE = 3;

interface MergedEntry { id: number; title: string; replaced_wording?: boolean }

function parseMerged(raw: InsightItem['merged_from']): MergedEntry[] {
  if (Array.isArray(raw)) return raw;
  try {
    const value = JSON.parse(raw || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function statusLabels(t: TFunction<'aiAdvisor'>): Record<string, string> {
  return {
    raw: t('insightManager.status.raw'),
    recurring: t('insightManager.status.recurring'),
    validated: t('insightManager.status.validated'),
    principle: t('insightManager.status.principle'),
    deprecated: t('insightManager.status.deprecated'),
  };
}

function categoryLabels(t: TFunction<'aiAdvisor'>): Record<string, string> {
  return {
    risk: t('insightManager.category.risk'),
    timing: t('insightManager.category.timing'),
    sizing: t('insightManager.category.sizing'),
    strategy: t('insightManager.category.strategy'),
    process: t('insightManager.category.process'),
    recommendation: t('insightManager.category.recommendation'),
  };
}

/** Three dots: how far an insight is toward the 3 cases that make it promotable. */
function CaseMeter({ cases }: { cases: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden>
      {Array.from({ length: CASES_TO_PROMOTE }, (_, i) => (
        <span
          key={i}
          className={`inline-block h-1.5 w-1.5 rounded-full ${i < cases ? 'bg-emerald-500' : 'bg-slate-200 dark:bg-slate-700'}`}
        />
      ))}
    </span>
  );
}

export const InsightManager: React.FC<InsightManagerProps> = ({ insights, onRefresh }) => {
  const { t } = useTranslation('aiAdvisor');
  const STATUS_LABELS = statusLabels(t);
  const CATEGORY_LABELS = categoryLabels(t);
  const { lang } = useLanguage();
  const [filterStatus, setFilterStatus] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [promoting, setPromoting] = useState<number | null>(null);
  const [addingCase, setAddingCase] = useState<number | null>(null);
  const [settingRuleLayer, setSettingRuleLayer] = useState<number | null>(null);
  const [showSimilar, setShowSimilar] = useState(false);

  const filtered = insights.filter((item) => {
    if (filterStatus && item.status !== filterStatus) return false;
    if (filterCategory && item.category !== filterCategory) return false;
    return true;
  });

  const handlePromote = async (id: number) => {
    setPromoting(id);
    try {
      await promoteInsight(id);
      onRefresh();
    } catch {
      // silent fail
    } finally {
      setPromoting(null);
    }
  };

  // A case the user records by hand (link + optional note); reviews add their own.
  const handleAddCase = async (id: number) => {
    const link = window.prompt(t('insightManager.prompts.caseLink'));
    if (!link) return;
    const note = window.prompt(t('insightManager.prompts.note')) || undefined;
    setAddingCase(id);
    try {
      await addValidatedCase(id, link, note);
      onRefresh();
    } catch {
      // silent fail — matches handlePromote
    } finally {
      setAddingCase(null);
    }
  };

  const handleSetRuleLayer = async (id: number, value: string) => {
    if (!value) return;
    setSettingRuleLayer(id);
    try {
      await setRuleLayer(id, value as 'principle' | 'checklist_item');
      onRefresh();
    } catch {
      // silent fail
    } finally {
      setSettingRuleLayer(null);
    }
  };

  const selectClass = 'text-xs rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary';

  return (
    <div className="rounded-xl border border-slate-200 dark:border-border-dark bg-white dark:bg-card-dark p-5">
      {/* Header */}
      <div className="flex items-center gap-3 mb-1 flex-wrap">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('insightManager.title')}</h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">
          {insights.length}
        </span>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className={selectClass}>
            <option value="">{t('insightManager.allStatuses')}</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)} className={selectClass}>
            <option value="">{t('insightManager.allCategories')}</option>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <ChipBtn icon="join_inner" onClick={() => setShowSimilar(true)} disabled={showSimilar || insights.length < 2}>
            {t('insightManager.findSimilar')}
          </ChipBtn>
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-4">{t('insightManager.intro')}</p>

      {showSimilar && <SimilarInsightsPanel onMerged={onRefresh} onClose={() => setShowSimilar(false)} />}

      {/* Content */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <span className="material-symbols-outlined !text-[36px] text-slate-300 dark:text-slate-600 mb-3">
            lightbulb
          </span>
          <p className="text-sm text-slate-400">
            {insights.length === 0
              ? t('insightManager.emptyNoInsights')
              : t('insightManager.emptyNoMatch')}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((item) => {
            const merged = parseMerged(item.merged_from);
            const next = NEXT_STATUS[item.status];
            const canPromote = Boolean(next) && item.promote_eligible;
            const showsUse = item.status === 'validated' || item.status === 'principle';
            const cases = item.validated_cases ?? 0;
            return (
              <div
                key={item.id}
                data-testid={`insight-${item.id}`}
                className="rounded-lg border border-slate-100 dark:border-slate-700 p-4 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
              >
                {/* Title row */}
                <div className="flex items-start gap-2 mb-2">
                  <span className="font-medium text-sm text-slate-800 dark:text-slate-100 flex-1 min-w-0">
                    {item.title}
                  </span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0 ${STATUS_COLORS[item.status] ?? STATUS_COLORS.raw}`}>
                    {STATUS_LABELS[item.status] ?? item.status}
                  </span>
                  {item.category && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 shrink-0">
                      {CATEGORY_LABELS[item.category] ?? item.category}
                    </span>
                  )}
                </div>

                {/* Body: only when it adds to the title (titles are cut at 80 characters) */}
                {item.body && item.body !== item.title && (
                  <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed mb-3">{item.body}</p>
                )}

                {/* Evidence, and only the actions that apply */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
                    <span>{t('insightManager.seenIn', { count: item.recurrence_count })}</span>
                    {item.status !== 'principle' && (
                      <span className="flex items-center gap-1.5">
                        <CaseMeter cases={cases} />
                        <span className={canPromote ? 'text-emerald-600 dark:text-emerald-400' : undefined}>
                          {cases >= CASES_TO_PROMOTE ? t('insightManager.readyToPromote') : t('insightManager.caseProgress', { cases })}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleAddCase(item.id)}
                          disabled={addingCase === item.id}
                          className="text-primary hover:underline disabled:opacity-50"
                        >
                          {t('insightManager.addCase')}
                        </button>
                      </span>
                    )}
                    <span>{formatDate(item.created_at, lang)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {showsUse && (
                      <label className="flex items-center gap-1.5 text-xs text-slate-500">
                        {t('insightManager.ruleLayer.label')}
                        <select
                          value={item.rule_layer ?? ''}
                          onChange={(e) => handleSetRuleLayer(item.id, e.target.value)}
                          disabled={settingRuleLayer === item.id}
                          className={selectClass}
                        >
                          <option value="">{t('insightManager.ruleLayer.unset')}</option>
                          <option value="principle">{t('insightManager.ruleLayer.principle')}</option>
                          <option value="checklist_item">{t('insightManager.ruleLayer.checklistItem')}</option>
                        </select>
                      </label>
                    )}
                    {canPromote && (
                      <button
                        type="button"
                        onClick={() => handlePromote(item.id)}
                        disabled={promoting === item.id}
                        className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-primary text-white hover:bg-primary/90 disabled:opacity-50 transition-colors"
                      >
                        <span className="material-symbols-outlined !text-[12px]" aria-hidden>arrow_upward</span>
                        {t(`insightManager.promoteTo.${next}`)}
                      </button>
                    )}
                  </div>
                </div>

                {/* What a merge folded into this insight */}
                {merged.length > 0 && (
                  <details className="mt-2 text-xs text-slate-500">
                    <summary className="cursor-pointer select-none hover:text-slate-700 dark:hover:text-slate-300">
                      {t('insightManager.mergedFrom', { count: merged.filter((m) => !m.replaced_wording).length })}
                    </summary>
                    <ul className="mt-1.5 space-y-1 pl-4 list-disc">
                      {merged.map((m, i) => (
                        <li key={`${m.id}-${i}`} className="leading-relaxed">
                          {m.title}
                          {m.replaced_wording && <span className="ml-1 text-slate-400">({t('insightManager.earlierWording')})</span>}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
