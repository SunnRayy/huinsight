import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';

import { render, screen, waitFor } from '../test-utils';
import { AIAdvisor } from '../pages/AIAdvisor';

// Round 5 finding #5 added a first-run callout for an empty investor philosophy.
// 2026-10-19 (owner): the profile editor has one home — Settings → AI Prompts — so the
// duplicate "Your Profile" tab was removed and the callout links there.

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

const navigateMock = vi.hoisted(() => vi.fn());
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});

describe('AI Advisor — first-run callout points to Settings → AI Prompts (single profile home)', () => {
  it('shows the callout when the profile is empty, and "Set up now" opens Settings → AI Prompts', async () => {
    apiMocks.getProfile.mockResolvedValue(EMPTY_PROFILE);
    const user = userEvent.setup();

    render(<AIAdvisor />);

    expect(await screen.findByText(
      /The advisor checks every brief against your investment philosophy/i
    )).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /set up now/i }));
    expect(navigateMock).toHaveBeenCalledWith('/ai-prompts');
  });

  it('does not show the callout when the profile already has content', async () => {
    apiMocks.getProfile.mockResolvedValue(FILLED_PROFILE);

    render(<AIAdvisor />);

    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalled());
    await waitFor(() => {
      expect(
        screen.queryByText(/The advisor checks every brief against your investment philosophy/i)
      ).not.toBeInTheDocument();
    });
  });

  it('has no duplicate "Your Profile" tab (the editor lives only in Settings → AI Prompts)', async () => {
    apiMocks.getProfile.mockResolvedValue(FILLED_PROFILE);
    render(<AIAdvisor />);
    await waitFor(() => expect(apiMocks.getProfile).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Your Profile' })).not.toBeInTheDocument();
  });
});
