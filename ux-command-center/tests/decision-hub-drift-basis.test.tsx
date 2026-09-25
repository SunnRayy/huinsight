import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DecisionHub } from '../pages/DecisionHub';

// Round 5 finding #8: the Drift Alerts card must not read "0" when drift is
// unmeasurable (no strategic targets and no active risk profile) — that looks
// identical to "checked, nothing drifted" but means something else entirely.
// These three states cover: no targets at all, risk-profile fallback basis,
// and the pre-existing strategic basis.

const apiMocks = vi.hoisted(() => ({
  getDecisionsTimeline: vi.fn(),
  getDecisionsStats: vi.fn(),
  getDecisionsScorecard: vi.fn(),
  getDecisionsIntelligence: vi.fn(),
  getDecisionAlerts: vi.fn(),
}));

vi.mock('../src/services/api', async () => {
  const actual = await vi.importActual('../src/services/api');
  return { ...actual, api: apiMocks };
});

const baseTimeline = { items: [], summary: { total: 0, adopted: 0, pending: 0 } };
const baseScorecard = { items: [] };
const baseIntelligence = {
  decision_patterns: {
    funnel: { total: 0, adopted: 0, rejected: 0, pending: 0, good_call: 0, regret: 0, missed_opportunity: 0, bullet_dodged: 0 },
    leaderboard: [],
    sources: [],
  },
  growth_timeline: [],
  raw_sections: [],
};

function baseStats(overrides: Record<string, unknown>) {
  return {
    total_insights: 5,
    adopted_count: 2,
    pending_count: 3,
    pending_actions_count: 1,
    adoption_rate: 40,
    total_trades: 5,
    active_drift_alerts: 0,
    ...overrides,
  };
}

beforeEach(() => {
  apiMocks.getDecisionsTimeline.mockResolvedValue(baseTimeline);
  apiMocks.getDecisionsScorecard.mockResolvedValue(baseScorecard);
  apiMocks.getDecisionsIntelligence.mockResolvedValue(baseIntelligence);
  apiMocks.getDecisionAlerts.mockResolvedValue({ alerts: [], counts: { high: 0, medium: 0, low: 0 } });
  Element.prototype.scrollIntoView = vi.fn();
});

function renderHub() {
  return render(
    <MemoryRouter>
      <DecisionHub />
    </MemoryRouter>
  );
}

describe('DecisionHub drift alerts card — drift_basis states', () => {
  it('shows "No targets to compare" instead of 0 when drift_basis is null', async () => {
    apiMocks.getDecisionsStats.mockResolvedValue(baseStats({ active_drift_alerts: 0, drift_basis: null }));

    renderHub();

    expect(await screen.findByText('No targets to compare')).toBeInTheDocument();
    // The raw zero must not render anywhere near the card — that is the bug.
    expect(screen.queryByRole('button', { name: /drift alerts/i })).not.toHaveTextContent(/\b0\b/);
  });

  it('shows the count with a risk-profile caption when drift_basis is risk_profile', async () => {
    apiMocks.getDecisionsStats.mockResolvedValue(baseStats({ active_drift_alerts: 2, drift_basis: 'risk_profile' }));

    renderHub();

    const card = await screen.findByRole('button', { name: /drift alerts/i });
    expect(card).toHaveTextContent('2');
    expect(card).toHaveTextContent('vs your risk-profile targets');
  });

  it('shows the count with a strategic caption when drift_basis is strategic', async () => {
    apiMocks.getDecisionsStats.mockResolvedValue(baseStats({ active_drift_alerts: 3, drift_basis: 'strategic' }));

    renderHub();

    const card = await screen.findByRole('button', { name: /drift alerts/i });
    expect(card).toHaveTextContent('3');
    expect(card).toHaveTextContent('vs your strategic targets');
  });

  it('falls back to the plain count with no caption when drift_basis is absent (pre-field payload)', async () => {
    const stats = baseStats({ active_drift_alerts: 4 });
    delete (stats as Record<string, unknown>).drift_basis;
    apiMocks.getDecisionsStats.mockResolvedValue(stats);

    renderHub();

    const card = await screen.findByRole('button', { name: /drift alerts/i });
    expect(card).toHaveTextContent('4');
    expect(card).not.toHaveTextContent('vs your');
    expect(screen.queryByText('No targets to compare')).not.toBeInTheDocument();
  });
});
