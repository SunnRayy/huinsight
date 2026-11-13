import React from 'react';
import { fireEvent, render, screen, waitFor } from '../test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../src/i18n';
import { ReturnsInputs } from '../components/settings/ReturnsInputs';
import { ReturnsTab } from '../components/performance/ReturnsTab';
import { api } from '../src/services/api';
import type { PerformanceReturns } from '../src/services/api';

vi.mock('../src/services/api', () => ({
    api: { getReturnsInputs: vi.fn(), getTwrRereview: vi.fn(), applyTwrRereview: vi.fn(), importTtfundPull: vi.fn(), attestTtfund: vi.fn() },
}));

const coverage = {
    frozen_end: '2026-08-31', coverage_end: '2026-10-31', next_month: '2026-11-01', blockers: [],
    cn_coverage: { through: '2026-11-09', records: [
        { from: '2026-09-12', to: '2026-11-09', basis: 'cli_pull' as const, recorded_at: null },
        { from: '2026-11-10', to: '2026-11-20', basis: 'owner_attestation' as const, recorded_at: null },
    ] },
};
const preview = {
    available: true, frozen_end: '2026-08-31', workbook: 'funding.xlsx', evidence_text_changes: 3, net_change_cny: -38937.57,
    needs_review: true, history_changed_since_review: false,
    changes: [{ flow_id: 'flow-1', change: 'changed' as const, event_date: '2026-03-15', source: 'RSU', before_cny: 120000, after_cny: 104000 }],
};

beforeEach(async () => {
    vi.resetAllMocks();
    await i18n.changeLanguage('en');
    vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage, corrections: 0 });
});

describe('Data Sources: investment returns inputs', () => {
    it('shows both rows up to date, with the coverage periods behind a toggle', async () => {
        render(<ReturnsInputs />);
        const card = await screen.findByTestId('returns-inputs');
        await waitFor(() => expect(card).toHaveTextContent('TTFund trades confirmed through 2026-11-09 · 2 coverage periods'));
        expect(screen.getAllByText('Up to date')).toHaveLength(3);
        expect(screen.getByText('Corrections to locked months, up to 2026-08-31')).toBeInTheDocument();
        expect(screen.getByText('Locked records match the uploaded file.')).toBeInTheDocument();
        expect(screen.queryByTestId('ttfund-coverage-records')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Show coverage periods' }));
        const table = screen.getByTestId('ttfund-coverage-records');
        expect(table).toHaveTextContent('2026-11-10 → 2026-11-20');
        expect(table.textContent!.indexOf('2026-11-10')).toBeLessThan(table.textContent!.indexOf('2026-09-12')); // latest first
        expect(screen.getByText('From TTFund export')).toBeInTheDocument();
        expect(screen.getByText('Declared by you')).toBeInTheDocument();
        expect(api.getTwrRereview).not.toHaveBeenCalled();
    });

    it('explains why behind the info button', async () => {
        render(<ReturnsInputs />);
        await screen.findByTestId('returns-inputs');
        fireEvent.click(screen.getAllByRole('button', { name: 'Why this is needed' })[0]);
        expect(screen.getByRole('tooltip')).toHaveTextContent('Returns add a month only once');
    });

    it('declares no trades in two steps; only the second calls the server', async () => {
        vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage: { ...coverage, blockers: [{ code: 'cn_web_list_missing' }] }, corrections: 0 });
        vi.mocked(api.attestTtfund).mockResolvedValue({ coverage: { coverage_end: '2026-10-31' }, sync_log_id: 4 });
        render(<ReturnsInputs />);
        expect(await screen.findAllByText('Action needed')).toHaveLength(2);
        fireEvent.click(screen.getByText("Can't export? Declare no trades yourself"));
        expect(screen.getByRole('dialog')).toHaveTextContent('TTFund · Step 1 of 2');
        const next = screen.getByText('Continue').closest('button')!;
        expect(next).toBeDisabled();
        fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-12' } });
        fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-10-31' } });
        fireEvent.change(screen.getByLabelText('How you checked'), { target: { value: 'app history' } });
        fireEvent.click(next);
        expect(screen.getByRole('dialog')).toHaveTextContent('Confirm there were no TTFund trades from 2026-09-12 to 2026-10-31?');
        expect(api.attestTtfund).not.toHaveBeenCalled();
        fireEvent.click(screen.getByText('Declare no trades', { selector: 'button' }));
        await waitFor(() => expect(api.attestTtfund).toHaveBeenCalledWith('2026-09-12', '2026-10-31', 'app history'));
        expect(await screen.findByRole('status')).toHaveTextContent('Done. Returns are now calculated through 2026-10-31.');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(api.getReturnsInputs).toHaveBeenCalledTimes(2);
    });

    it('keeps the declaration when the server refuses it, and reopens it', async () => {
        vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage: { ...coverage, blockers: [{ code: 'cn_web_list_missing' }] }, corrections: 0 });
        vi.mocked(api.attestTtfund).mockRejectedValue(new Error('covered_to must be before today'));
        render(<ReturnsInputs />);
        fireEvent.click(await screen.findByText("Can't export? Declare no trades yourself"));
        fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-12' } });
        fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-11-09' } });
        fireEvent.change(screen.getByLabelText('How you checked'), { target: { value: 'app' } });
        fireEvent.click(screen.getByText('Continue'));
        fireEvent.click(screen.getByText('Declare no trades', { selector: 'button' }));
        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent("Couldn't save the declaration. The server said:");
        expect(alert).toHaveTextContent('covered_to must be before today');
        fireEvent.click(screen.getByText('Edit declaration'));
        expect(screen.getByLabelText('To')).toHaveValue('2026-11-09');
        expect(screen.getByLabelText('How you checked')).toHaveValue('app');
    });

    it('shows the server reason when an export is refused', async () => {
        vi.mocked(api.importTtfundPull).mockRejectedValue(new Error('The export must include the tradeType=all query'));
        render(<ReturnsInputs />);
        fireEvent.click(await screen.findByRole('button', { name: 'Show coverage periods' }));
        const file = new File(['{}'], 'pull.json', { type: 'application/json' });
        fireEvent.change(screen.getByLabelText('Upload TTFund export (.json)'), { target: { files: [file] } });
        expect(await screen.findByRole('alert')).toHaveTextContent('tradeType=all');
    });

    it('opens the comparison by itself when corrections are waiting, and applies them after the confirm dialog', async () => {
        vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage, corrections: 1 });
        vi.mocked(api.getTwrRereview).mockResolvedValue(preview);
        vi.mocked(api.applyTwrRereview).mockResolvedValue({ status: 'ok', coverage: { coverage_end: '2026-10-31' }, sync_log_id: 1 });
        render(<ReturnsInputs />);
        const table = await screen.findByTestId('rereview-preview');
        expect(screen.getByText('1 correction waiting')).toBeInTheDocument();
        expect(table).toHaveTextContent('RSU');
        expect(table).toHaveTextContent('changed');
        expect(table).toHaveTextContent('¥120,000.00');
        expect(table).not.toHaveTextContent('[object Object]');
        expect(screen.getByText('3 other records differ only in notes or file paths — no figure changes')).toBeInTheDocument();
        const apply = screen.getByText('Use the corrected records').closest('button')!;
        expect(apply).toBeDisabled();
        expect(screen.getByText('Fill in both fields to continue.')).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Confirmed by'), { target: { value: 'me' } });
        fireEvent.change(screen.getByLabelText('Why (statement or reference)'), { target: { value: 'statement' } });
        fireEvent.click(apply);
        const dialog = screen.getByRole('dialog');
        expect(dialog).toHaveTextContent('Locked months · up to 2026-08-31');
        expect(dialog).toHaveTextContent('Confirmed by me · statement');
        expect(api.applyTwrRereview).not.toHaveBeenCalled();
        fireEvent.click(screen.getByText('Replace and recalculate'));
        await waitFor(() => expect(api.applyTwrRereview).toHaveBeenCalledWith('me', 'statement'));
        expect(await screen.findByRole('status')).toHaveTextContent('Done. Locked records up to 2026-08-31 replaced; Returns recalculated.');
    });

    it('shows the server reason when the replacement is refused', async () => {
        vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage, corrections: 1 });
        vi.mocked(api.getTwrRereview).mockResolvedValue(preview);
        vi.mocked(api.applyTwrRereview).mockRejectedValue(new Error('history is not frozen yet'));
        render(<ReturnsInputs />);
        await screen.findByTestId('rereview-preview');
        fireEvent.change(screen.getByLabelText('Confirmed by'), { target: { value: 'me' } });
        fireEvent.change(screen.getByLabelText('Why (statement or reference)'), { target: { value: 'x' } });
        fireEvent.click(screen.getByText('Use the corrected records'));
        fireEvent.click(screen.getByText('Replace and recalculate'));
        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent("Couldn't replace the locked records. The server said:");
        expect(alert).toHaveTextContent('history is not frozen yet');
    });

    it('says when the file matches the locked records after comparing again', async () => {
        vi.mocked(api.getTwrRereview).mockResolvedValue({ ...preview, changes: [], evidence_text_changes: 0, needs_review: false });
        render(<ReturnsInputs />);
        fireEvent.click(await screen.findByText('Compare again'));
        await waitFor(() => expect(api.getTwrRereview).toHaveBeenCalled());
        expect(await screen.findByText('Locked records match the uploaded file.')).toBeInTheDocument();
        expect(screen.queryByText('Use the corrected records')).not.toBeInTheDocument();
    });

    it('says why when the server cannot count corrections', async () => {
        vi.mocked(api.getReturnsInputs).mockResolvedValue({ coverage, corrections: null });
        vi.mocked(api.getTwrRereview).mockResolvedValue({ available: false, reason: 'workbook_missing' } as never);
        render(<ReturnsInputs />);
        expect(await screen.findByText('funding_transactions.xlsx has not been uploaded.')).toBeInTheDocument();
    });

    it('uses 用户 in Chinese', async () => {
        await i18n.changeLanguage('zh-CN');
        render(<ReturnsInputs />);
        expect(await screen.findByText('投资收益：补充数据与更正')).toBeInTheDocument();
        expect(screen.getByText('仅能由用户提供 · 用于 业绩 → 收益')).toBeInTheDocument();
        expect(screen.getByTestId('returns-inputs')).not.toHaveTextContent('业主');
    });
});

describe('Performance → Returns only links to Data Sources', () => {
    const base = { twr_cumulative: null, twr_unavailable_reason: 'default', coverage_status: coverage } as unknown as PerformanceReturns;

    it('has no input controls and no banner when nothing is waiting', () => {
        render(<ReturnsTab returns={base} />);
        expect(screen.queryByTestId('returns-inputs-banner')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /upload/i })).not.toBeInTheDocument();
        expect(screen.getAllByTestId('ttfund-basis-chip')).toHaveLength(2);
    });

    it('links to Data Sources when corrections or TTFund months are waiting', async () => {
        await i18n.changeLanguage('zh-CN');
        render(<ReturnsTab returns={{ ...base, locked_history_corrections: 1,
            coverage_status: { ...coverage, blockers: [{ code: 'cn_web_list_missing' }] } } as PerformanceReturns} />);
        const banner = screen.getByTestId('returns-inputs-banner');
        expect(banner).toHaveTextContent('更正了已锁定月份中的 1 条记录');
        expect(banner).toHaveTextContent('之后的天天基金交易尚未确认');
        screen.getAllByRole('link', { name: '前往数据源 →' }).forEach(a => expect(a).toHaveAttribute('href', '/data-sources#returns-inputs'));
    });
});
