import React from 'react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { act, render, screen } from '../test-utils';
import { AnswerSection } from '../components/forecast/AnswerSection';
import { FanChart } from '../components/forecast/FanChart';
import type { ForecastLevers, ProjectionResult } from '../src/services/api/types';
import i18n from '../src/i18n';

// Round 7 #2: while history is too short to trust a measured return, Your Path
// projects from the configured long-run assumption and must say so on the
// headline itself (not a tooltip), and the fan chart must look different from
// a history-based one. Once history suffices, the banner is gone.

const ASSUMPTION = {
  expected_return: 0.05,
  volatility: 0.12,
  reason: 'Like-for-like basis too thin at a 180-day lookback',
  min_history_days: 180,
  max_history_days: 365,
  config_keys: ['north_star.long_run_return', 'north_star.long_run_volatility'],
};

function makeLevers(basis: 'measured' | 'assumption'): ForecastLevers {
  return {
    base: {
      current_nw: 1_200_000,
      expected_return: basis === 'assumption' ? 0.05 : 0.09,
      volatility: basis === 'assumption' ? 0.12 : 0.15,
      median_return: 0.0425,
      monthly_contribution: 10_000,
      target: 5_000_000,
      years_to_target: 16.4,
      crossing_years: { p25: 13.1, p50: 16.4, p75: 21.0 },
      return_basis: basis,
    },
    levers: { savings: [], return: [], volatility: [] },
    combined: { label: 'combined', years_to_target: null, delta_years: null },
    goal: {
      target_amount: 5_000_000, source: 'goals', goal_id: 1, name: 'Financial independence',
      target_date: '2038-12-31', fallback_reason: null,
    },
    assumption: basis === 'assumption' ? ASSUMPTION : null,
  };
}

const PROJECTION = {
  years: [0, 10, 20],
  percentiles: {
    p10: [1_200_000, 1_900_000, 2_900_000],
    p25: [1_200_000, 2_300_000, 3_800_000],
    p50: [1_200_000, 2_800_000, 5_200_000],
    p75: [1_200_000, 3_300_000, 6_900_000],
    p90: [1_200_000, 3_900_000, 8_800_000],
  },
} as unknown as ProjectionResult;

describe('Your Path — long-run assumption banner', () => {
  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  test('shows the assumption plainly on the headline (EN)', () => {
    render(<AnswerSection levers={makeLevers('assumption')} loading={false} onGoToGoals={vi.fn()} />);

    const banner = screen.getByTestId('forecast-assumption-banner');
    expect(banner).toHaveTextContent(
      'Not enough history yet (needs 6–12 months) — projecting with a long-run assumption: 5.0% return, 12% volatility. Edit assumption'
    );
    expect(screen.getByText('16.4')).toBeInTheDocument();
    expect(screen.getByText('Return / Vol (assumed)')).toBeInTheDocument();
  });

  test('"Edit assumption" says where the assumption is set', async () => {
    render(<AnswerSection levers={makeLevers('assumption')} loading={false} onGoToGoals={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Edit assumption' }));

    const banner = screen.getByTestId('forecast-assumption-banner');
    expect(banner).toHaveTextContent('config/verification.yaml');
    expect(banner).toHaveTextContent('north_star.long_run_return, north_star.long_run_volatility');
  });

  test('renders the banner in Chinese', async () => {
    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    render(<AnswerSection levers={makeLevers('assumption')} loading={false} onGoToGoals={vi.fn()} />);

    expect(screen.getByTestId('forecast-assumption-banner')).toHaveTextContent(
      '历史数据不足（约需 6–12 个月）——当前按长期假设预测：年化收益 5.0%、波动 12%。修改假设'
    );
  });

  test('no banner once history is measured', () => {
    render(<AnswerSection levers={makeLevers('measured')} loading={false} onGoToGoals={vi.fn()} />);

    expect(screen.queryByTestId('forecast-assumption-banner')).toBeNull();
    expect(screen.getByText('Return / Vol')).toBeInTheDocument();
  });
});

describe('Your Path — fan chart basis', () => {
  test('an assumption-based projection is labelled and drawn differently', () => {
    render(<FanChart levers={makeLevers('assumption')} projection={PROJECTION} loading={false} />);

    expect(screen.getByTestId('fan-assumption-label')).toHaveTextContent('Assumption-based range');
    const band = screen.getByTestId('fan-band-outer');
    expect(band).toHaveAttribute('data-basis', 'assumption');
    expect(band).toHaveAttribute('fill', 'url(#fanAssumptionHatch)');
  });

  test('a history-based projection keeps the plain bands and no label', () => {
    render(<FanChart levers={makeLevers('measured')} projection={PROJECTION} loading={false} />);

    expect(screen.queryByTestId('fan-assumption-label')).toBeNull();
    expect(screen.getByTestId('fan-band-outer')).toHaveAttribute('data-basis', 'measured');
  });
});
