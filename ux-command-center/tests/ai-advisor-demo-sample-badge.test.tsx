import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { AIAdvisor } from '../pages/AIAdvisor';
import { ReviewFlow } from '../components/ai-advisor/ReviewFlow';
import { PortfolioFilterProvider } from '../src/context/usePortfolioFilter';

// Phase 3b (Round 5 finding #3): a brief/review whose model_used is the
// deterministic seeder's marker ('demo-sample', see tools/demo_data/seed_ai.py)
// must render a visible "Sample" badge + one-line explanation so a new user
// without an LLM key never mistakes seeded illustrative content for a real
// AI-generated report. A normal, LLM-generated report must show neither.

const apiMocks = vi.hoisted(() => ({
  computeBehavioralMetrics: vi.fn(),
  createStrategyMemo: vi.fn(),
  createTrade: vi.fn(),
  deleteStrategyMemo: vi.fn(),
  deleteReview: vi.fn(),
  deleteTrade: vi.fn(),
  generateReviewQuestions: vi.fn(),
  generateReview: vi.fn(),
  getBriefById: vi.fn(),
  getBriefHistory: vi.fn(),
  getContextPreview: vi.fn(),
  getReviewHistory: vi.fn(),
  renderAdvisorContext: vi.fn(),
  getLatestBehavioralMetrics: vi.fn(),
  getLatestBrief: vi.fn(),
  getLatestReview: vi.fn(),
  getLLMSettings: vi.fn(),
  getReviewById: vi.fn(),
  getStrategyMemos: vi.fn(),
  listInsights: vi.fn(),
  listTrades: vi.fn(),
  generateBrief: vi.fn(),
  promoteInsight: vi.fn(),
  searchAssets: vi.fn(),
  updateReview: vi.fn(),
}));

vi.mock('../src/services/api', () => ({
  computeBehavioralMetrics: apiMocks.computeBehavioralMetrics,
  generateReviewQuestions: apiMocks.generateReviewQuestions,
  generateReview: apiMocks.generateReview,
  getBriefById: apiMocks.getBriefById,
  getBriefHistory: apiMocks.getBriefHistory,
  getContextPreview: apiMocks.getContextPreview,
  getReviewHistory: apiMocks.getReviewHistory,
  renderAdvisorContext: apiMocks.renderAdvisorContext,
  getLatestBehavioralMetrics: apiMocks.getLatestBehavioralMetrics,
  getLatestBrief: apiMocks.getLatestBrief,
  getLatestReview: apiMocks.getLatestReview,
  getLLMSettings: apiMocks.getLLMSettings,
  getReviewById: apiMocks.getReviewById,
  getStrategyMemos: apiMocks.getStrategyMemos,
  listInsights: apiMocks.listInsights,
  listTrades: apiMocks.listTrades,
  generateBrief: apiMocks.generateBrief,
  promoteInsight: apiMocks.promoteInsight,
  updateReview: apiMocks.updateReview,
  deleteReview: apiMocks.deleteReview,
  api: {
    getStrategyMemos: apiMocks.getStrategyMemos,
    createStrategyMemo: apiMocks.createStrategyMemo,
    deleteStrategyMemo: apiMocks.deleteStrategyMemo,
    listTrades: apiMocks.listTrades,
    createTrade: apiMocks.createTrade,
    deleteTrade: apiMocks.deleteTrade,
    searchAssets: apiMocks.searchAssets,
  },
}));

const briefUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };

function makeBrief(modelUsed: string) {
  return {
    id: 1,
    report_type: 'brief',
    content_json: {
      macro_outlook: { narrative: 'Sample macro narrative for the demo persona.' },
    },
    content_markdown: '## Macro outlook\n\nSample macro narrative for the demo persona.',
    model_used: modelUsed,
    created_at: '2026-08-15T00:00:00Z',
    context_config: {
      tiers: {
        identity: { enabled: true, detail: 'summary' },
        portfolio: { enabled: true, detail: 'summary' },
        market: { enabled: true, detail: 'summary' },
        strategy: { enabled: false, detail: 'summary' },
        transactions: { enabled: true, detail: 'summary', timeframe: '14d' },
      },
      include_realtime: false,
    },
    usage: briefUsage,
  };
}

function makeReviewHistoryItem(id: number) {
  return {
    id,
    title: 'Sample investment review 2026-07-15 ~ 2026-08-14',
    model_used: 'demo-sample',
    created_at: '2026-08-14T00:00:00Z',
    period_start: '2026-07-15',
    period_end: '2026-08-14',
  };
}

function makeReviewDetail(id: number, modelUsed: string) {
  return {
    id,
    title: 'Sample investment review 2026-07-15 ~ 2026-08-14',
    model_used: modelUsed,
    created_at: '2026-08-14T00:00:00Z',
    content_json: {
      trade_summary: { narrative: 'Sample trade summary for the demo persona.' },
    },
    content_markdown: '## Trade summary\n\nSample trade summary for the demo persona.',
    period_start: '2026-07-15',
    period_end: '2026-08-14',
    prompt_text: null,
    raw_response_text: null,
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();

  apiMocks.getBriefHistory.mockResolvedValue([]);
  apiMocks.getContextPreview.mockResolvedValue({});
  apiMocks.getLatestBehavioralMetrics.mockResolvedValue([]);
  apiMocks.getLLMSettings.mockResolvedValue({
    primary_model: 'gemini/gemini-2.5-flash',
    fallback_models: [],
    temperature: 0.2,
    max_output_tokens: 2048,
  });
  apiMocks.listInsights.mockResolvedValue([]);
  apiMocks.getReviewHistory.mockResolvedValue([makeReviewHistoryItem(101)]);
});

const renderAIAdvisor = () =>
  render(
    <PortfolioFilterProvider>
      <MemoryRouter>
        <AIAdvisor />
      </MemoryRouter>
    </PortfolioFilterProvider>
  );

const renderReviewFlow = () =>
  render(
    <MemoryRouter>
      <ReviewFlow
        contextConfig={{
          tiers: {
            identity: { enabled: false, detail: 'summary' },
            portfolio: { enabled: true, detail: 'summary' },
            market: { enabled: false, detail: 'summary' },
            strategy: { enabled: false, detail: 'summary' },
            transactions: { enabled: false, detail: 'summary', timeframe: '14d' },
          },
          include_realtime: false,
          include_non_rebalanceable: false,
        }}
      />
    </MemoryRouter>
  );

describe('Demo-sample badge — Brief (pages/AIAdvisor.tsx)', () => {
  it('shows the sample badge and explanation when the latest brief is model_used=demo-sample', async () => {
    apiMocks.getLatestBrief.mockResolvedValue(makeBrief('demo-sample'));

    renderAIAdvisor();

    expect(await screen.findByText('Sample macro narrative for the demo persona.')).not.toBeNull();
    expect(screen.getByText('Sample')).not.toBeNull();
    expect(
      screen.getByText('Sample brief — written for the demo persona, not generated by an AI model.')
    ).not.toBeNull();
  });

  it('does not show the sample badge for a normal, LLM-generated brief', async () => {
    apiMocks.getLatestBrief.mockResolvedValue(makeBrief('gemini/gemini-2.5-flash'));

    renderAIAdvisor();

    expect(await screen.findByText('Sample macro narrative for the demo persona.')).not.toBeNull();
    expect(screen.queryByText('Sample')).toBeNull();
    expect(
      screen.queryByText('Sample brief — written for the demo persona, not generated by an AI model.')
    ).toBeNull();
  });
});

describe('Demo-sample badge — Review (components/ai-advisor/ReviewFlow.tsx)', () => {
  it('shows the sample badge and explanation for a saved review with model_used=demo-sample', async () => {
    const user = userEvent.setup();
    apiMocks.getReviewById.mockResolvedValue(makeReviewDetail(101, 'demo-sample'));

    renderReviewFlow();

    expect(await screen.findByText('Recent Reviews')).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Open' }));

    expect(await screen.findByText('Sample trade summary for the demo persona.')).not.toBeNull();
    expect(screen.getByText('Sample')).not.toBeNull();
    expect(
      screen.getByText('Sample review — written for the demo persona, not generated by an AI model.')
    ).not.toBeNull();
  });

  it('does not show the sample badge for a normal, LLM-generated review', async () => {
    const user = userEvent.setup();
    apiMocks.getReviewById.mockResolvedValue(makeReviewDetail(101, 'gemini/gemini-2.5-flash'));

    renderReviewFlow();

    expect(await screen.findByText('Recent Reviews')).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Open' }));

    expect(await screen.findByText('Sample trade summary for the demo persona.')).not.toBeNull();
    expect(screen.queryByText('Sample')).toBeNull();
    expect(
      screen.queryByText('Sample review — written for the demo persona, not generated by an AI model.')
    ).toBeNull();
  });
});
