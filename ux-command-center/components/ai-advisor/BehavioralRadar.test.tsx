import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BehavioralRadar } from './BehavioralRadar';
import type { BehavioralMetric } from '../../src/services/api';

const metric = (dimension: string, score: number | null, label: string): BehavioralMetric => ({
  dimension,
  score,
  raw_value: score == null ? null : score * 100,
  label,
  description: '',
});

describe('BehavioralRadar', () => {
  it('never draws an unmeasured dimension as a value', () => {
    const metrics = [
      metric('loss_tolerance', 0.7, 'avg loss 12%'),
      metric('rebalance_discipline', 0.4, '2 class(es) drifted >5%'),
      metric('position_sizing_discipline', 0.9, 'avg drift 1.2%'),
      metric('decision_speed', null, 'Insufficient transaction data'),
      metric('manual_contrarian', null, '40% of manual buys in drawdown'),
    ];
    render(<BehavioralRadar metrics={metrics} onCompute={vi.fn()} computing={false} />);

    expect(screen.getByTestId('metric-unmeasured-decision_speed')).toBeTruthy();
    expect(screen.getByTestId('metric-unmeasured-manual_contrarian')).toBeTruthy();
    expect(screen.queryByTestId('metric-unmeasured-loss_tolerance')).toBeNull();
    // The label still carries what is known about an unscored dimension.
    expect(screen.getByText('40% of manual buys in drawdown')).toBeTruthy();
    // The shape discloses that it covers only the measured dimensions.
    expect(screen.getByTestId('radar-partial')).toBeTruthy();
  });

  it('does not draw a shape from fewer than three measured dimensions', () => {
    const metrics = [
      metric('loss_tolerance', 0.7, 'avg loss 12%'),
      metric('decision_speed', null, 'Insufficient transaction data'),
      metric('strategy_compliance', null, 'No AI advisory data yet'),
    ];
    render(<BehavioralRadar metrics={metrics} onCompute={vi.fn()} computing={false} />);

    expect(screen.getByTestId('radar-too-few')).toBeTruthy();
    expect(screen.queryByTestId('radar-partial')).toBeNull();
  });
});
