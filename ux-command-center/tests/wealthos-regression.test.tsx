import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '../test-utils';
import { WealthOS } from '../pages/WealthOS';

const apiMocks = vi.hoisted(() => ({
  getWealthOSAssets: vi.fn(),
  getWealthOSSummary: vi.fn(),
}));

vi.mock('../src/services/api', () => ({
  api: apiMocks,
  manualPnlApi: { listManualPnl: vi.fn().mockResolvedValue([]) },
}));

describe('WealthOS regression', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getWealthOSSummary.mockResolvedValue({
      total_lifetime_gain: 10,
      lifetime_gain_pct: 1,
      annualized_return: 4.34,
      account_returns: { mwr_xirr: 4.34, mwr_as_of: '2026-08-31' },
      active_asset_count: 1,
      total_asset_count: 1,
    });
  });

  it('shows account XIRR and its valuation date', async () => {
    apiMocks.getWealthOSAssets
      .mockResolvedValue({ assets: [
        {
          name: 'Test Asset',
          code: 'TEST_1',
          type: 'Equity (股票)',
          period: '1y',
          status: 'ACTIVE',
          invested: 100,
          cur: 120,
          pl: 20,
          ret: 20,
        },
      ], non_rebalanceable_assets: [] });

    render(<WealthOS />);

    await waitFor(() => {
      expect(apiMocks.getWealthOSAssets).toHaveBeenCalled();
    });

    expect(await screen.findByText('Test Asset')).toBeInTheDocument();
    expect(screen.getByTestId('wealth-page')).toHaveClass('w-full', 'min-w-0', 'max-w-full');
    expect(screen.getByRole('table').parentElement).toHaveClass('overflow-x-auto', 'w-full', 'min-w-0', 'max-w-full');
    expect(screen.getByText('4.34%')).toBeInTheDocument();
    expect(screen.getByText('As of 2026-08-31')).toBeInTheDocument();
  });
});
