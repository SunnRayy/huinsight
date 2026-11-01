import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BehavioralRadar, localizeMetricNote } from './BehavioralRadar';
import i18n from '../../src/i18n';
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

describe('localizeMetricNote', () => {
  const zh = i18n.getFixedT('zh-CN', 'aiAdvisor');
  const en = i18n.getFixedT('en', 'aiAdvisor');

  it('shows every backend note format in Chinese', () => {
    const cases: [string, string][] = [
      ['Insufficient transaction data', '交易记录不足'],
      ['No AI advisory data yet', '暂无 AI 顾问数据'],
      ['avg drift 3.7%', '平均偏离 3.7%'],
      ['2 class(es) drifted >5% (after design-intent exclusions)', '2 个类别偏离超过 5%（已排除设计性配置）'],
      ['1 class(es) drifted >5%', '1 个类别偏离超过 5%'],
      ['median 12 day decision cycle', '决策周期中位数 12 天'],
      ['40.0% manual contrarian rate (4/10)', '逆向率 40.0%（4/10）'],
      ['75% trades within strategy (since 2026-06-01)', '75% 的交易符合策略（自 2026-06-01 起）'],
    ];
    for (const [note, want] of cases) expect(localizeMetricNote(note, zh)).toBe(want);
  });

  it('leaves English notes as the backend wrote them', () => {
    for (const note of ['avg drift 3.7%', '2 class(es) drifted >5% (after design-intent exclusions)', 'No data']) {
      expect(localizeMetricNote(note, en)).toBe(note);
    }
  });

  it('shows an unknown note as sent', () => {
    expect(localizeMetricNote('40% of manual buys in drawdown', zh)).toBe('40% of manual buys in drawdown');
  });
});
