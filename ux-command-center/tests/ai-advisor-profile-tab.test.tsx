import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';

import { render, screen, waitFor } from '../test-utils';
import { AIAdvisor } from '../pages/AIAdvisor';

// Round 5 finding #5: the investor philosophy checked against every brief
// used to live only under System -> AI Prompts, several accordions down,
// where a new user would never find it. This file covers the new "Your
// profile" tab on the AI Advisor page (reusing InvestorProfileEditor) and
// the first-run callout that appears until the philosophy has any content.

const apiMocks = vi.hoisted(() => ({
  computeBehavioralMetrics: vi.fn(),
  getBriefHistory: vi.fn(),
  getContextPreview: vi.fn(),
  getLatestBehavioralMetrics: vi.fn(),
  getLatestBrief: vi.fn(),
  getLLMSettings: vi.fn(),
  listInsights: vi.fn(),
  generateBrief: vi.fn(),
  renderAdvisorContext: vi.fn(),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock('../src/services/api', () => ({
  computeBehavioralMetrics: apiMocks.computeBehavioralMetrics,
  getBriefHistory: apiMocks.getBriefHistory,
  getContextPreview: apiMocks.getContextPreview,
  getLatestBehavioralMetrics: apiMocks.getLatestBehavioralMetrics,
  getLatestBrief: apiMocks.getLatestBrief,
  getLLMSettings: apiMocks.getLLMSettings,
  listInsights: apiMocks.listInsights,
  generateBrief: apiMocks.generateBrief,
  renderAdvisorContext: apiMocks.renderAdvisorContext,
  SettingsAPI: {
    getProfile: apiMocks.getProfile,
    updateProfile: apiMocks.updateProfile,
  },
}));

const EMPTY_PROFILE = {
  display_name: 'Ray',
  avatar_url: null,
  philosophy: {
    goal: '',
    horizon: '',
    risk_tolerance: '',
    core_weakness: '',
    portfolio_structure: '',
  },
};

const FILLED_PROFILE = {
  display_name: 'Ray',
  avatar_url: null,
  philosophy: {
    goal: 'Long-term wealth compounding',
    horizon: '15 years',
    risk_tolerance: 'Can handle -30% drawdown',
    core_weakness: 'Recency bias',
    portfolio_structure: 'US equities 50%, bonds 20%, alts 30%',
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getBriefHistory.mockResolvedValue([]);
  apiMocks.getContextPreview.mockResolvedValue({});
  apiMocks.getLatestBehavioralMetrics.mockResolvedValue([]);
  apiMocks.getLatestBrief.mockResolvedValue(null);
  apiMocks.getLLMSettings.mockResolvedValue({
    primary_model: 'gemini/gemini-2.5-flash',
    fallback_models: [],
    temperature: 0.2,
    max_output_tokens: 2048,
  });
  apiMocks.listInsights.mockResolvedValue([]);
});

describe('AI Advisor — Your profile tab and first-run callout', () => {
  it('shows the callout when the profile is empty, and clicking it opens the profile tab/editor', async () => {
    apiMocks.getProfile.mockResolvedValue(EMPTY_PROFILE);
    const user = userEvent.setup();

    render(<AIAdvisor />);

    const callout = await screen.findByText(
      /The advisor checks every brief against your investment philosophy/i
    );
    expect(callout).toBeInTheDocument();

    const ctaButton = screen.getByRole('button', { name: /set up now/i });
    await user.click(ctaButton);

    // Switches to the "Your profile" tab, which renders InvestorProfileEditor.
    expect(await screen.findByText(/Investor Profile/)).toBeInTheDocument();
    expect(apiMocks.getProfile).toHaveBeenCalled();

    // The callout should not render while already on the profile tab.
    expect(
      screen.queryByText(/The advisor checks every brief against your investment philosophy/i)
    ).not.toBeInTheDocument();
  });

  it('does not show the callout when the profile already has content', async () => {
    apiMocks.getProfile.mockResolvedValue(FILLED_PROFILE);

    render(<AIAdvisor />);

    // Wait for the profile fetch to resolve before asserting absence.
    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalled());
    await waitFor(() => {
      expect(
        screen.queryByText(/The advisor checks every brief against your investment philosophy/i)
      ).not.toBeInTheDocument();
    });
  });

  it('renders the InvestorProfileEditor when the Your Profile tab is selected', async () => {
    apiMocks.getProfile.mockResolvedValue(FILLED_PROFILE);
    const user = userEvent.setup();

    render(<AIAdvisor />);

    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'Your Profile' }));

    expect(await screen.findByDisplayValue('Long-term wealth compounding')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('15 years')).toBeInTheDocument();
  });
});
