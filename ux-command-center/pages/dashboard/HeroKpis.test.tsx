import { describe, it, expect } from 'vitest';
import { render, screen } from '../../test-utils';
import { HeroKpis } from './HeroKpis';
import type { KPI, PriceFreshness } from '../../src/services/api';

const kpi = (price_freshness: PriceFreshness | null): KPI => ({
  net_worth: 1_372_805,
  pnl_24h: null,
  market_pulse: null,
  market_pulse_sentiment: null,
  price_freshness,
});

const renderHero = (freshness: PriceFreshness | null) =>
  render(
    <HeroKpis
      kpi={kpi(freshness)} perfReturns={null} marketStatus={null} cashFlow={null}
      sparkData={[]} delta30d={-1_004_598} pct30d={-42.3} sinceLabel="Jun 2026" macro={null}
    />,
  );

describe('HeroKpis price freshness', () => {
  it('marks the headline degraded when the price refresh failed', () => {
    renderHero({ status: 'unpriced', unpriced_share: 1, unpriced_count: 15, holding_count: 15, last_price_at: null });
    expect(screen.getByTestId('net-worth-prices-degraded').textContent).toMatch(/Prices not refreshed — 100%/);
  });

  it('says nothing extra when prices are live', () => {
    renderHero({ status: 'fresh', unpriced_share: 0.06, unpriced_count: 1, holding_count: 15, last_price_at: '2026-09-24T00:00:00' });
    expect(screen.queryByTestId('net-worth-prices-degraded')).toBeNull();
  });

  it('names the real comparison baseline instead of "last month"', () => {
    renderHero(null);
    expect(screen.getByText('VS Jun 2026')).toBeTruthy();
  });
});
