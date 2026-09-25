import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { RiskMatrix } from '../pages/RiskMatrix';
import { api } from '../src/services/api';

vi.mock('../src/context/usePortfolioFilter', () => ({
  usePortfolioFilter: () => ({
    includeNonRebalanceable: false,
    toggleNonRebalanceable: vi.fn(),
  }),
}));

vi.mock('../src/services/api', () => ({
  api: {
    getRiskMetrics: vi.fn(),
    getRiskCorrelation: vi.fn(),
  },
  ExportAPI: {
    downloadAiContext: vi.fn(),
  },
}));

describe('RiskMatrix correlation null rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getRiskMetrics as ReturnType<typeof vi.fn>).mockResolvedValue({
      volatility: 12.1,
      volatility_status: 'MED',
      sharpe: 0.5,
      sharpe_status: 'AVG',
      var_95: 1.2,
      var_95_status: 'LOW',
      beta: 1.0,
      div_score: 6,
    });
    (api.getRiskCorrelation as ReturnType<typeof vi.fn>).mockResolvedValue({
      method: 'empirical_holdings',
      assets: ['Equity', 'Fixed Income'],
      matrix: [
        {
          asset: 'Equity',
          correlations: {
            Equity: { value: 1.0, overlap: 12, low_confidence: false },
            'Fixed Income': { value: null, overlap: 4, low_confidence: false },
          },
        },
        {
          asset: 'Fixed Income',
          correlations: {
            Equity: { value: null, overlap: 4, low_confidence: false },
            'Fixed Income': { value: 1.0, overlap: 12, low_confidence: false },
          },
        },
      ],
      insufficient_pairs: 1,
      total_pairs: 1,
      effective_periods: 2,
      overlap_min: 0,
      overlap_median: 0,
      min_overlap_periods: 8,
      window_start: '2025-09-15',
      window_end: '2026-03-12',
      excluded_jump_points_count: 2,
      winsor_p_low: 0.05,
      winsor_p_high: 0.95,
    });
  });

  it('renders null correlations as dash and shows coverage warning/footnote', async () => {
    render(<RiskMatrix />);

    await waitFor(() => {
      expect(api.getRiskCorrelation).toHaveBeenCalled();
    });

    expect(screen.getByText('Most class pairs lack sufficient history for correlation. Results shown where available.')).toBeInTheDocument();
    expect(screen.getByText(/Window: 2025-09-15 to 2026-03-12/i)).toBeInTheDocument();
    // Legend copy updated with the shared-grid fix (issue #34): the dash now
    // means "not enough overlapping periods on the shared grid", and the grid
    // itself has to be explained or the numbers imply a synchronisation the
    // underlying readers do not have.
    expect(screen.getByText(/– = not enough overlapping return periods to measure/i)).toBeInTheDocument();
    expect(screen.getByText(/shared period grid chosen from the slowest-reporting class/i)).toBeInTheDocument();
    expect(screen.getAllByText('–').length).toBeGreaterThan(0);
  });

  it('discloses the grid, the carried endpoints and the refused periods', async () => {
    (api.getRiskCorrelation as ReturnType<typeof vi.fn>).mockResolvedValue({
      method: 'empirical_holdings',
      assets: ['Equity', 'Cash'],
      matrix: [
        {
          asset: 'Equity',
          correlations: {
            Equity: { value: 1.0, overlap: 24, low_confidence: false, bridged_share: 0 },
            Cash: { value: 0.31, overlap: 22, low_confidence: false, bridged_share: 0.1 },
          },
        },
        {
          asset: 'Cash',
          correlations: {
            Equity: { value: 0.31, overlap: 22, low_confidence: false, bridged_share: 0.1 },
            Cash: { value: 1.0, overlap: 22, low_confidence: false, bridged_share: 0 },
          },
        },
      ],
      insufficient_pairs: 0,
      total_pairs: 1,
      effective_periods: 26,
      overlap_min: 22,
      overlap_median: 22,
      min_overlap_periods: 8,
      window_start: '2024-06-30',
      window_end: '2026-08-28',
      excluded_jump_points_count: 0,
      winsor_p_low: 0.05,
      winsor_p_high: 0.95,
      grid_frequency: 'ME',
      grid_label: 'monthly',
      window_days: 841,
      bridged_return_share: 0.12,
      fabricated_returns_suppressed: 7,
    });

    render(<RiskMatrix />);
    await waitFor(() => expect(api.getRiskCorrelation).toHaveBeenCalled());

    expect(screen.getByText(/Measured on monthly periods \(26 periods over 841 days\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Carried-forward endpoints: 12% of periods/i)).toBeInTheDocument();
    expect(screen.getByText(/7 unobserved periods refused/i)).toBeInTheDocument();
  });

  it('warns when a class has not reported recently', async () => {
    (api.getRiskCorrelation as ReturnType<typeof vi.fn>).mockResolvedValue({
      method: 'empirical_holdings',
      assets: ['Equity', 'Pension'],
      matrix: [
        {
          asset: 'Equity',
          correlations: {
            Equity: { value: 1.0, overlap: 24, low_confidence: false, bridged_share: 0 },
            Pension: { value: 0.4, overlap: 20, low_confidence: false, bridged_share: 0 },
          },
        },
        {
          asset: 'Pension',
          correlations: {
            Equity: { value: 0.4, overlap: 20, low_confidence: false, bridged_share: 0 },
            Pension: { value: 1.0, overlap: 20, low_confidence: false, bridged_share: 0 },
          },
        },
      ],
      insufficient_pairs: 0,
      total_pairs: 1,
      effective_periods: 26,
      overlap_min: 20,
      overlap_median: 20,
      min_overlap_periods: 8,
      window_start: '2024-06-30',
      window_end: '2026-08-28',
      excluded_jump_points_count: 0,
      winsor_p_low: 0.05,
      winsor_p_high: 0.95,
      grid_frequency: 'ME',
      grid_label: 'monthly',
      window_days: 841,
      class_evidence: {
        Equity: { observations: 500, median_gap_days: 1, first_observed: '2024-06-30', last_observed: '2026-08-28' },
        // Five months stale while the footer reads through 2026-08-28.
        Pension: { observations: 20, median_gap_days: 30, first_observed: '2024-06-15', last_observed: '2026-03-15' },
      },
    });

    render(<RiskMatrix />);
    await waitFor(() => expect(api.getRiskCorrelation).toHaveBeenCalled());

    expect(screen.getByText(/Pension last observed 2026-03-15/i)).toBeInTheDocument();
    // The fresh class must not be listed as stale.
    expect(screen.queryByText(/Equity last observed/i)).not.toBeInTheDocument();
  });

  it('renders low-confidence badge when backend marks a cell as low confidence', async () => {
    (api.getRiskCorrelation as ReturnType<typeof vi.fn>).mockResolvedValue({
      method: 'empirical_holdings',
      assets: ['Equity', 'Fixed Income'],
      matrix: [
        {
          asset: 'Equity',
          correlations: {
            Equity: { value: 1.0, overlap: 12, low_confidence: false },
            'Fixed Income': { value: 0.22, overlap: 9, low_confidence: true },
          },
        },
        {
          asset: 'Fixed Income',
          correlations: {
            Equity: { value: 0.22, overlap: 9, low_confidence: true },
            'Fixed Income': { value: 1.0, overlap: 12, low_confidence: false },
          },
        },
      ],
      insufficient_pairs: 0,
      total_pairs: 1,
      effective_periods: 12,
      overlap_min: 9,
      overlap_median: 9,
      min_overlap_periods: 8,
      window_start: '2025-09-15',
      window_end: '2026-03-12',
      excluded_jump_points_count: 0,
      winsor_p_low: 0.05,
      winsor_p_high: 0.95,
    });

    render(<RiskMatrix />);

    await waitFor(() => {
      expect(api.getRiskCorrelation).toHaveBeenCalled();
    });

    expect(screen.getAllByText('LC').length).toBeGreaterThan(0);
  });
});
