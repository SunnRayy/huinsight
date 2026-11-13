import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActionBtn, Card, CardHeader, ChipBtn, FieldLabel, FormTextarea, Notice, Pill } from '../operations';
import { findSimilarInsights, mergeInsightGroup } from '../../src/services/api';
import type { SimilarInsightGroup, SimilarInsightGroupsResponse } from '../../src/services/api';

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';
const STATUS_TONE: Record<string, Tone> = {
  raw: 'neutral', recurring: 'primary', validated: 'success', principle: 'primary',
};

interface Props {
  onMerged: () => void;
  onClose: () => void;
}

/** Model-proposed groups of insights that say the same thing; the user merges or skips each.
 *  Spec: docs/api-specs/insight-reinforcement.md (A3, A4, Section D). */
export function SimilarInsightsPanel({ onMerged, onClose }: Props) {
  const { t } = useTranslation('aiAdvisor');
  const [result, setResult] = useState<SimilarInsightGroupsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const [merging, setMerging] = useState<number | null>(null);
  // Members the user unticked: they stay as they are when the group is merged.
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState<{ tone: 'success' | 'danger'; text: string; detail?: string } | null>(null);

  // The combined wording per group (primary id → text), editable before merging.
  const [wording, setWording] = useState<Record<number, string>>({});
  // One model call per opening: React's dev double-mount would otherwise ask twice.
  const asked = useRef(false);

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    findSimilarInsights()
      .then((r) => {
        setResult(r);
        setWording(Object.fromEntries(r.groups.map((g) => [g.primary_id, g.merged_title])));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const hide = (primaryId: number) => setHidden((prev) => new Set(prev).add(primaryId));

  const toggle = (id: number) => setExcluded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const chosen = (group: SimilarInsightGroup) =>
    group.members.filter((m) => m.id !== group.primary_id && !excluded.has(m.id)).map((m) => m.id);

  const merge = async (group: SimilarInsightGroup) => {
    const others = chosen(group);
    setMerging(group.primary_id);
    setNotice(null);
    try {
      const merged = await mergeInsightGroup(group.primary_id, others, (wording[group.primary_id] ?? '').trim() || undefined);
      hide(group.primary_id);
      setNotice({
        tone: 'success',
        text: `${t('insightManager.similar.merged', { count: others.length, id: group.primary_id })} · ${t('insightManager.validatedCases', { count: merged.validated_cases })}`,
      });
      onMerged();
    } catch (e) {
      setNotice({ tone: 'danger', text: t('insightManager.similar.mergeFailed'), detail: (e as Error).message });
    } finally {
      setMerging(null);
    }
  };

  const visible = (result?.groups ?? []).filter((g) => !hidden.has(g.primary_id));
  const sub = result
    ? t('insightManager.similar.sub', { count: result.groups.length, considered: result.considered })
    : undefined;

  return (
    <Card padding={0} style={{ marginBottom: 16 }}>
      <CardHeader
        icon="join_inner"
        title={t('insightManager.similar.title')}
        sub={sub}
        right={<ChipBtn onClick={onClose}>{t('insightManager.similar.close')}</ChipBtn>}
      />
      <div style={{ padding: '14px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!result && !error && (
          <div role="status" style={{ fontSize: 13, color: 'var(--color-fg-3)' }}>
            {t('insightManager.similar.finding')}
          </div>
        )}
        {error && <Notice tone="danger" detail={error}>{t('insightManager.similar.failed')}</Notice>}
        {result && (
          <p style={{ margin: 0, fontSize: 12, color: 'var(--color-fg-3)', lineHeight: 1.5 }}>
            {result.groups.length === 0 ? t('insightManager.similar.none') : t('insightManager.similar.intro')}
          </p>
        )}
        {notice && <Notice tone={notice.tone} detail={notice.detail}>{notice.text}</Notice>}
        {visible.map((group) => {
          const others = chosen(group).length;
          const all = others === group.members.length - 1;
          return (
            <section
              key={group.primary_id}
              aria-label={group.theme}
              style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: '12px 14px' }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 12px', marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-fg-1)', flex: '1 1 160px' }}>
                  {group.theme}
                </span>
                <span className="uis-mono" style={{ fontSize: 11, color: 'var(--color-fg-3)' }}>
                  {t(all ? 'insightManager.similar.outcome' : 'insightManager.similar.outcomeAll', { count: group.cases_after_merge })}
                </span>
                {all && group.promotable_after_merge && <Pill tone="success">{t('insightManager.similar.promotable')}</Pill>}
              </div>
              <div style={{ marginBottom: 10 }}>
                <FieldLabel htmlFor={`merged-wording-${group.primary_id}`}>{t('insightManager.similar.wording')}</FieldLabel>
                <FormTextarea
                  id={`merged-wording-${group.primary_id}`}
                  rows={2}
                  maxLength={500}
                  value={wording[group.primary_id] ?? ''}
                  onChange={(v) => setWording((prev) => ({ ...prev, [group.primary_id]: v }))}
                />
              </div>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {group.members.map((m) => (
                  <li key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                    <span style={{ width: 44, flexShrink: 0, display: 'inline-flex', alignItems: 'center' }}>
                      {m.id === group.primary_id ? (
                        <Pill tone="primary">{t('insightManager.similar.kept')}</Pill>
                      ) : (
                        <input
                          type="checkbox"
                          checked={!excluded.has(m.id)}
                          onChange={() => toggle(m.id)}
                          aria-label={t('insightManager.similar.include', { id: m.id })}
                          style={{ accentColor: 'var(--color-primary)', margin: '0 0 0 4px' }}
                        />
                      )}
                    </span>
                    <span
                      title={m.title}
                      style={{ flex: '1 1 0', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--color-fg-2)' }}
                    >
                      {m.title}
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                      <span className="uis-mono" style={{ fontSize: 11, color: 'var(--color-fg-3)' }}>
                        {m.report_date ?? '—'}
                      </span>
                      <Pill tone={STATUS_TONE[m.status] ?? 'neutral'}>{t(`insightManager.status.${m.status}`)}</Pill>
                    </span>
                  </li>
                ))}
              </ul>
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
                <ChipBtn onClick={() => hide(group.primary_id)} disabled={merging !== null}>
                  {t('insightManager.similar.skip')}
                </ChipBtn>
                <ActionBtn variant="primary" icon="merge" onClick={() => merge(group)} disabled={merging !== null || others === 0}>
                  {t('insightManager.similar.merge', { count: others })}
                </ActionBtn>
              </div>
            </section>
          );
        })}
      </div>
    </Card>
  );
}
