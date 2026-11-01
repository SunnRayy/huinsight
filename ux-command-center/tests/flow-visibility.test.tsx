import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '../test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../src/i18n';
import { FlowReviewCard } from '../components/performance/FlowReviewCard';
import { CoverageChip } from '../components/performance/CoverageChip';
import { api } from '../src/services/api';

vi.mock('../src/services/api', () => ({ api: { getFlowReview: vi.fn(), saveFlowReview: vi.fn() } }));
const item = { event_key: 'test-key', event_date: '2026-09-10', source: 'TTFund', reason: 'CN status needs confirmation' };
const ibkr = { ...item, event_key: 'ibkr-unknown:2026-09-30', source: 'IBKR', reason: 'IBKR deposits unknown' };
const status = { frozen_end: '2026-08-31', coverage_end: '2026-08-31', next_month: '2026-09-01', blockers: [
    { code: 'cn_web_list_missing' as const }, { code: 'fs_month_missing' as const }, { code: 'open_reviews' as const, count: 2 }] };

beforeEach(async () => { vi.resetAllMocks(); await i18n.changeLanguage('en'); vi.mocked(api.getFlowReview).mockResolvedValue({ items: [item] }); });

describe('coverage chip', () => {
    it('shows owner labels and links to confirmations', () => {
        render(<CoverageChip status={status} />);
        const link = screen.getByRole('link');
        expect(link).toHaveTextContent('September waiting for: TTFund website list, Financial Summary row, 2 confirmations');
        expect(link).toHaveAttribute('href', '/cash-flow-classification#investment-confirmations');
        expect(link).toHaveClass('truncate');
    });
    it('hides while the next month is in progress, including detail', () => {
        const { container } = render(<><CoverageChip status={{ ...status, in_progress: true }} /><CoverageChip status={{ ...status, in_progress: true }} detail /></>);
        expect(container).toBeEmptyDOMElement();
    });
    it('hides when clear', () => { const { container } = render(<CoverageChip status={{ ...status, blockers: [] }} />); expect(container).toBeEmptyDOMElement(); });
    it('localizes Chinese and freshness detail', async () => {
        await i18n.changeLanguage('zh-CN');
        render(<CoverageChip status={{ ...status, blockers: [{ code: 'source_data_behind', source: 'Gold', latest_date: '2026-08-30' }] }} detail />);
        expect(screen.getByText(/黄金/)).toHaveTextContent('2026-08-30');
    });
});

describe('investment confirmations', () => {
    it.each([['External in', 'external_in'], ['External out', 'external_out'], ['Internal', 'internal']])('saves %s and optimistically removes', async (label, decision) => {
        let finish!: () => void;
        vi.mocked(api.saveFlowReview).mockImplementation(() => new Promise(resolve => { finish = () => resolve({ event_key: item.event_key, decision }); }));
        render(<FlowReviewCard />);
        fireEvent.click(await screen.findByRole('button', { name: label }));
        expect(screen.queryByText('2026-09-10')).not.toBeInTheDocument();
        expect(api.saveFlowReview).toHaveBeenCalledWith('test-key', { decision });
        await act(async () => finish());
        expect(await screen.findByText('Nothing to confirm')).toBeInTheDocument();
    });
    it('rolls back on save failure', async () => {
        vi.mocked(api.saveFlowReview).mockRejectedValue(new Error('failed'));
        render(<FlowReviewCard />);
        fireEvent.click(await screen.findByRole('button', { name: 'Internal' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('Could not save');
        expect(screen.getByText('2026-09-10')).toBeInTheDocument();
    });
    it('validates signed manual CNY and saves against the IBKR key', async () => {
        vi.mocked(api.getFlowReview).mockResolvedValue({ items: [ibkr] });
        vi.mocked(api.saveFlowReview).mockResolvedValue({ event_key: ibkr.event_key, decision: 'manual' });
        render(<FlowReviewCard />);
        fireEvent.click(await screen.findByRole('button', { name: 'Enter amount' }));
        const input = screen.getByRole('textbox', { name: /Signed amount/ });
        for (const value of ['', '0', 'NaN', 'Infinity', 'abc']) {
            fireEvent.change(input, { target: { value } });
            fireEvent.click(screen.getByRole('button', { name: 'Save' }));
            expect(api.saveFlowReview).not.toHaveBeenCalled();
        }
        fireEvent.change(input, { target: { value: '-250.50' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));
        await waitFor(() => expect(api.saveFlowReview).toHaveBeenCalledWith(ibkr.event_key, { decision: 'manual', amount_cny: -250.5 }));
        expect(await screen.findByText('Nothing to confirm')).toBeInTheDocument();
    });
    it('confirms no IBKR deposits as internal', async () => {
        vi.mocked(api.getFlowReview).mockResolvedValue({ items: [ibkr] });
        vi.mocked(api.saveFlowReview).mockResolvedValue({ event_key: ibkr.event_key, decision: 'internal' });
        render(<FlowReviewCard />);
        fireEvent.click(await screen.findByRole('button', { name: 'No deposits this month' }));
        expect(api.saveFlowReview).toHaveBeenCalledWith(ibkr.event_key, { decision: 'internal' });
        expect(await screen.findByText('Nothing to confirm')).toBeInTheDocument();
    });
    it('has an empty state', async () => {
        vi.mocked(api.getFlowReview).mockResolvedValue({ items: [] });
        render(<FlowReviewCard />);
        expect(await screen.findByText('Nothing to confirm')).toBeInTheDocument();
    });
    it('shows load failure and retries', async () => {
        vi.mocked(api.getFlowReview).mockRejectedValueOnce(new Error('failed')).mockResolvedValueOnce({ items: [] });
        render(<FlowReviewCard />);
        expect(await screen.findByRole('alert')).toHaveTextContent('Could not load');
        expect(screen.queryByText('Nothing to confirm')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
        expect(await screen.findByText('Nothing to confirm')).toBeInTheDocument();
    });
});

it('renders the waiting chip and full details in the Returns popover', async () => {
    const { ReturnsTab } = await import('../components/performance/ReturnsTab');
    render(<ReturnsTab returns={{ twr_cumulative: null, twr_ytd: null, twr_1y: null, mwr_xirr: null,
        twr_as_of: '2026-08-31', coverage_status: { ...status, blockers: [
            { code: 'source_data_behind', source: 'Gold', latest_date: '2026-08-30' }, { code: 'open_reviews', count: 1 },
        ] } }} />);
    expect(screen.getByRole('link')).toHaveTextContent('September waiting for: Gold update, 1 confirmation');
    fireEvent.click(screen.getByRole('button', { name: i18n.t('performance:returns.methodology') }));
    expect(screen.getByRole('dialog')).toHaveTextContent('latest: 2026-08-30');
});

it('shows known amounts and Chinese owner reasons', async () => {
    await i18n.changeLanguage('zh-CN');
    vi.mocked(api.getFlowReview).mockResolvedValue({ items: [{ ...item, amount: 120, currency: 'CNY' }] });
    render(<FlowReviewCard />);
    expect(await screen.findByText('请确认交易状态')).toBeInTheDocument();
    expect(screen.getByText('CNY 120')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '外部转入' })).toBeInTheDocument();
});

it.each([['en', 'No Gold activity in September', 'or upload a newer Gold file'],
    ['zh-CN', '九月无黄金交易', '或上传更新的黄金文件']])('confirms no source activity in %s', async (language, label, hint) => {
    await i18n.changeLanguage(language);
    const key = 'no-activity:Gold_Excel:2026-09';
    vi.mocked(api.getFlowReview).mockResolvedValue({ items: [{ event_key: key, event_date: '2026-09-30', source: 'Gold', reason: 'no_activity_unconfirmed' }] });
    vi.mocked(api.saveFlowReview).mockResolvedValue({ event_key: key, decision: 'internal' });
    render(<FlowReviewCard />);
    const button = await screen.findByRole('button', { name: label });
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByText(hint)).toBeInTheDocument();
    fireEvent.click(button);
    expect(api.saveFlowReview).toHaveBeenCalledWith(key, { decision: 'internal' });
    await waitFor(() => expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument());
});
