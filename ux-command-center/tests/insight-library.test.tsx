import React from 'react';
import { fireEvent, render, screen, within } from '../test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../src/i18n';
import { InsightManager } from '../components/ai-advisor/InsightManager';
import { promoteInsight } from '../src/services/api';
import type { InsightItem } from '../src/services/api';

vi.mock('../src/services/api', () => ({
  promoteInsight: vi.fn(), addValidatedCase: vi.fn(), setRuleLayer: vi.fn(),
  findSimilarInsights: vi.fn(), mergeInsightGroup: vi.fn(),
}));

const base: InsightItem = {
  id: 0, category: 'strategy', title: '', body: '', tags: '', confidence: 0.3, status: 'raw',
  recurrence_count: 1, entity_refs: '', source_report_id: 19, created_at: '2026-04-03 10:00:00',
  updated_at: '2026-11-09 10:00:00', validated_cases: 0, validated_case_links: '[]', rule_layer: null,
  promote_eligible: false, promote_blocked_reason: 'confidence 30% < 70% and validated_cases 0 < 3',
  merged_from: '[]',
};
const insights: InsightItem[] = [
  { ...base, id: 1, title: 'Gold DCA needs a grid and position limits' },
  { ...base, id: 39, status: 'recurring', recurrence_count: 4, validated_cases: 3, promote_eligible: true,
    promote_blocked_reason: null, title: 'Keep 70% of SGOV for the SPX 6300 plan',
    merged_from: JSON.stringify([
      { id: 39, title: 'Graded dip-buying: SPX 6300 is the floor', report_id: 19, replaced_wording: true },
      { id: 46, title: 'Refine the graded dip-buying rule', report_id: 28 },
      { id: 67, title: 'Physically separate the reserve', report_id: 57 },
    ]) },
  { ...base, id: 45, status: 'validated', recurrence_count: 2, validated_cases: 1, title: 'Value-bucket sell rule' },
];

beforeEach(async () => {
  vi.resetAllMocks();
  await i18n.changeLanguage('en');
});

describe('Insight Library rows', () => {
  it('shows progress toward promotion and only the actions that apply', () => {
    render(<InsightManager insights={insights} onRefresh={vi.fn()} />);
    expect(screen.getByText('Each review that repeats an insight adds a case. At 3 cases you can promote it.')).toBeInTheDocument();

    const fresh = within(screen.getByTestId('insight-1'));
    expect(fresh.getByText('Seen in 1 review')).toBeInTheDocument();
    expect(fresh.getByText('0 of 3 cases')).toBeInTheDocument();
    expect(fresh.queryByRole('button', { name: /Promote/ })).not.toBeInTheDocument();
    expect(fresh.queryByRole('combobox')).not.toBeInTheDocument(); // "Use as" only once validated
    expect(fresh.queryByText(/Confidence/)).not.toBeInTheDocument();

    const ready = within(screen.getByTestId('insight-39'));
    expect(ready.getByText('Seen in 4 reviews')).toBeInTheDocument();
    expect(ready.getByText('Ready to promote')).toBeInTheDocument();
    fireEvent.click(ready.getByRole('button', { name: 'Promote to Validated' }));
    expect(promoteInsight).toHaveBeenCalledWith(39);
    expect(ready.getByText('Merged from 2 insights')).toBeInTheDocument();
    expect(ready.getByText('Refine the graded dip-buying rule')).toBeInTheDocument();
    expect(ready.getByText('(earlier wording)')).toBeInTheDocument();

    const validated = within(screen.getByTestId('insight-45'));
    expect(validated.getByText('1 of 3 cases')).toBeInTheDocument();
    expect(validated.getByRole('combobox')).toHaveDisplayValue('Not set');
    expect(validated.queryByRole('button', { name: /Promote|principle/ })).not.toBeInTheDocument();
  });

  it('reads in Chinese', async () => {
    await i18n.changeLanguage('zh-CN');
    render(<InsightManager insights={insights} onRefresh={vi.fn()} />);
    const ready = within(screen.getByTestId('insight-39'));
    expect(ready.getByText('出现在 4 次复盘中')).toBeInTheDocument();
    expect(ready.getByRole('button', { name: '晋升为已验证' })).toBeInTheDocument();
    expect(ready.getByText('合并了 2 条洞察')).toBeInTheDocument();
    expect(within(screen.getByTestId('insight-1')).getByText('0/3 个案例')).toBeInTheDocument();
  });
});
