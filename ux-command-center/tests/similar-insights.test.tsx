import React from 'react';
import { fireEvent, render, screen, waitFor } from '../test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../src/i18n';
import { SimilarInsightsPanel } from '../components/ai-advisor/SimilarInsightsPanel';
import { findSimilarInsights, mergeInsightGroup } from '../src/services/api';
import type { InsightItem, SimilarInsightGroupsResponse } from '../src/services/api';

vi.mock('../src/services/api', () => ({ findSimilarInsights: vi.fn(), mergeInsightGroup: vi.fn() }));

const groups: SimilarInsightGroupsResponse = {
  considered: 52, model_used: 'fake',
  groups: [
    { theme: 'SGOV reserve for SPX 6300', merged_title: 'Keep 70% of SGOV for SPX 6300', primary_id: 9, cases_after_merge: 3, promotable_after_merge: true,
      members: [
        { id: 9, title: 'Graded dip-buying: SPX 6300 is the floor', status: 'principle', category: 'strategy', source_report_id: 19, report_date: '2026-04-03' },
        { id: 21, title: 'Refine the graded dip-buying rule', status: 'recurring', category: 'strategy', source_report_id: 28, report_date: '2026-05-04' },
        { id: 55, title: 'Ring-fence emergency SGOV reserves', status: 'raw', category: 'process', source_report_id: 72, report_date: '2026-11-08' },
      ] },
    { theme: 'Minimum trade size', merged_title: 'No trades under 0.2% of assets', primary_id: 30, cases_after_merge: 1, promotable_after_merge: false,
      members: [
        { id: 30, title: 'No trades under 0.2% of assets', status: 'raw', category: 'strategy', source_report_id: 32, report_date: '2026-05-24' },
        { id: 31, title: 'Batch small DCA orders', status: 'raw', category: 'process', source_report_id: null, report_date: null },
      ] },
  ],
};

beforeEach(async () => {
  vi.resetAllMocks();
  await i18n.changeLanguage('en');
});

describe('Insight Library: similar insights', () => {
  it('lists the proposed groups and merges one into the kept insight', async () => {
    vi.mocked(findSimilarInsights).mockResolvedValue(groups);
    vi.mocked(mergeInsightGroup).mockResolvedValue({ id: 9, validated_cases: 3, cases_added: 2 } as InsightItem & { cases_added: number });
    const onMerged = vi.fn();
    render(<React.StrictMode><SimilarInsightsPanel onMerged={onMerged} onClose={vi.fn()} /></React.StrictMode>);
    expect(screen.getByRole('status')).toHaveTextContent('Comparing insights…');
    expect(await screen.findByText('2 groups · 52 insights compared')).toBeInTheDocument();
    expect(findSimilarInsights).toHaveBeenCalledTimes(1); // once, even under StrictMode
    const sgov = screen.getByRole('region', { name: 'SGOV reserve for SPX 6300' });
    expect(sgov).toHaveTextContent('3 validated cases after merging');
    expect(sgov).toHaveTextContent('Promotable');
    expect(sgov).toHaveTextContent('Kept');
    expect(screen.getByText('—')).toBeInTheDocument(); // deleted review has no date

    // The combined wording is editable and goes with the merge.
    const box = screen.getByLabelText('Combined rule (you can edit it)', { selector: '#merged-wording-9' });
    expect(box).toHaveValue('Keep 70% of SGOV for SPX 6300');
    fireEvent.change(box, { target: { value: 'Keep 70% of SGOV for SPX 6300; never raid it' } });
    fireEvent.click(screen.getByRole('button', { name: /Merge 2 into the kept one/ }));
    await waitFor(() => expect(mergeInsightGroup).toHaveBeenCalledWith(9, [21, 55], 'Keep 70% of SGOV for SPX 6300; never raid it'));
    expect(await screen.findByText('Merged 2 insights into #9 · 3 validated cases')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'SGOV reserve for SPX 6300' })).not.toBeInTheDocument();
    expect(onMerged).toHaveBeenCalled();

    // Unticking a member leaves it out of the merge; the outcome no longer claims promotable.
    fireEvent.click(screen.getByRole('checkbox', { name: 'Merge #31 into the kept one' }));
    expect(screen.getByRole('button', { name: /Merge 0 into the kept one/ })).toBeDisabled();
    expect(screen.getByText('1 validated case if all are merged')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(screen.queryByRole('region', { name: 'Minimum trade size' })).not.toBeInTheDocument();
  });

  it('shows the server reason when a merge is refused', async () => {
    vi.mocked(findSimilarInsights).mockResolvedValue(groups);
    vi.mocked(mergeInsightGroup).mockRejectedValue(new Error('Insight 21 is missing or already merged'));
    render(<SimilarInsightsPanel onMerged={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /Merge 1 into the kept one/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The merge did not go through.');
    expect(screen.getByRole('alert')).toHaveTextContent('Insight 21 is missing or already merged');
  });

  it('says so when nothing matches, and when the comparison fails (zh)', async () => {
    await i18n.changeLanguage('zh-CN');
    vi.mocked(findSimilarInsights).mockResolvedValueOnce({ groups: [], considered: 4, model_used: 'fake' });
    const { unmount } = render(<SimilarInsightsPanel onMerged={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('没有表达相同观点的洞察，无需合并。')).toBeInTheDocument();
    unmount();
    vi.mocked(findSimilarInsights).mockRejectedValueOnce(new Error('ERR_INSIGHT_GROUPS_LLM'));
    render(<SimilarInsightsPanel onMerged={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('无法比较这些洞察。');
  });
});
