/**
 * The allocation report shows each class name in one language: "股票" in
 * Chinese, "Equity" in English — never the backend's bilingual display label
 * "Equity (股票)". Chinese prefers taxonomy_classes.name_cn (class_name_cn).
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import i18n from '../src/i18n';
import { Compass } from '../pages/Compass';

const apiMocks = vi.hoisted(() => ({
    getCompassSummary: vi.fn(),
    getCompassAllocation: vi.fn(),
}));
vi.mock('../src/services/api', () => ({ api: apiMocks }));
vi.mock('../src/context/usePortfolioFilter', () => ({
    usePortfolioFilter: () => ({ includeNonRebalanceable: false, setIncludeNonRebalanceable: vi.fn() }),
}));

const row = (asset_class: string, class_name: string, class_name_cn: string | null, top: boolean) => ({
    asset_class, class_name, class_name_cn,
    current_value: 100, currency: 'CNY', current_pct: 50, target_pct: 50, drift_pct: 0,
    tolerance_pct: 5, status: 'within_range' as const, has_target: true,
    is_top_level: top, parent_class: top ? null : 'Equity (股票)',
});

beforeEach(() => {
    apiMocks.getCompassSummary.mockResolvedValue({
        total_net_worth: 200, drift_index: 0, classes_in_drift: 0, total_classes: 3,
        last_sync_date: '2026-10-25', last_sync_source: 'demo',
    });
    apiMocks.getCompassAllocation.mockResolvedValue({
        rows: [
            row('Equity (股票)', 'Equity', '股票', true),
            row('CN Equity (A股)', 'CN Equity', null, false),
            row('Pension', 'Pension', '养老金', true),
        ],
        meta: null,
    });
});
afterEach(async () => { await act(() => i18n.changeLanguage('en')); });

describe('Compass class names', () => {
    it('shows Chinese names only on the Chinese UI', async () => {
        await act(() => i18n.changeLanguage('zh-CN'));
        render(<Compass />);
        await waitFor(() => expect(screen.getAllByText('股票').length).toBeGreaterThan(0));
        expect(screen.getAllByText('A股').length).toBeGreaterThan(0);      // from the label's Chinese half
        expect(screen.getAllByText('养老金').length).toBeGreaterThan(0);   // from name_cn
        expect(screen.queryByText('Equity (股票)')).toBeNull();
        expect(screen.queryByText('Pension')).toBeNull();
    });

    it('shows English names only on the English UI', async () => {
        render(<Compass />);
        await waitFor(() => expect(screen.getAllByText('Equity').length).toBeGreaterThan(0));
        expect(screen.getAllByText('CN Equity').length).toBeGreaterThan(0);
        expect(screen.queryByText('Equity (股票)')).toBeNull();
    });
});
