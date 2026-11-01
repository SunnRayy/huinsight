import React from 'react';
import i18n from '../src/i18n';
import { act } from '../test-utils';
import { render, screen, waitFor, fireEvent } from '../test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Performance } from '../pages/Performance';
import { api } from '../src/services/api';
import { usePortfolioFilter } from '../src/context/usePortfolioFilter';

function SharedFilter() {
    const { toggleNonRebalanceable } = usePortfolioFilter();
    return <button onClick={toggleNonRebalanceable}>Toggle portfolio scope</button>;
}

// Mock recharts
vi.mock('recharts', () => ({
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    AreaChart: () => <div data-testid="area-chart" />,
    ComposedChart: ({ data }: any) => <div data-testid="account-chart">{JSON.stringify(data)}</div>,
    Line: () => null,
    Area: () => null,
    CartesianGrid: () => null,
    Legend: () => null,
    BarChart: () => <div data-testid="bar-chart" />,
    Bar: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Cell: () => null,
    ReferenceLine: () => null,
    LabelList: () => null,
}));

// Mock the API calls
vi.mock('../src/services/api', () => ({
    api: {
        getPerformanceHistory: vi.fn(),
        getPerformanceSummary: vi.fn(),
        getGainsAnalysis: vi.fn(),
        getPerformanceByClass: vi.fn(),
        getReturns: vi.fn(),
        getAttribution: vi.fn(),
        getPerformanceRiskMetrics: vi.fn(),
    }
}));

const mockSummary = {
    net_worth: 1000000,
    total_cost_basis: 800000,
    total_unrealized_pl: 150000,
    unrealized_pl_pct: 15,
    total_realized_pl: 50000,
    total_lifetime_pl: 200000,
    asset_count: 10,
    snapshot_date: '2024-03-15'
};

const mockReturns = {
    investment_bridge: { period_start: '2025-08-31', period_end: '2026-08-31',
        opening_value_cny: 1000, net_external_flow_cny: 200,
        investment_gain_cny: 50, closing_value_cny: 1250 },
    twr_as_of: '2026-08-31',
    account_series: [{ date: '2025-08-31', value_cny: 1000, invested_cny: 1000 },
        { date: '2026-08-31', value_cny: 1250, invested_cny: 1200 }],
    twr_cumulative: 15.25,
    twr_ytd: 3.50,
    twr_1y: 12.80,
    mwr_xirr: 14.20
};

const mockAttribution = {
    portfolio_return: 12.50,
    benchmark_return: 10.00,
    excess_return: 2.50,
    total_allocation_effect: 1.0,
    total_selection_effect: 1.2,
    total_interaction_effect: 0.3,
    classes: [
        {
            class: 'Equity',
            portfolio_weight: 0.6,
            benchmark_weight: 0.55,
            portfolio_return: 15.0,
            benchmark_return: 12.0,
            allocation_effect: 0.5,
            selection_effect: 0.8,
            interaction_effect: 0.2,
            total_effect: 1.5
        }
    ]
};

const mockRiskMetrics = {
    max_drawdown: -15.20,
    sharpe_ratio: 1.25,
    sortino_ratio: 1.80,
    calmar_ratio: 0.85,
    volatility_annual: 18.50,
    total_return: 42.50,
    data_points: 36
};

describe('Performance Page Batch 6', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.removeItem('uis-include-non-rebalanceable');

        // Mock existing APIs
        (api.getPerformanceHistory as ReturnType<typeof vi.fn>).mockResolvedValue([]);
        (api.getPerformanceSummary as ReturnType<typeof vi.fn>).mockResolvedValue(mockSummary);
        (api.getGainsAnalysis as ReturnType<typeof vi.fn>).mockResolvedValue({ assets: [] });
        (api.getPerformanceByClass as ReturnType<typeof vi.fn>).mockResolvedValue({ top_classes: [], sub_classes: [] });

        // Mock new APIs
        (api.getReturns as ReturnType<typeof vi.fn>).mockResolvedValue(mockReturns);
        (api.getAttribution as ReturnType<typeof vi.fn>).mockResolvedValue(mockAttribution);
        (api.getPerformanceRiskMetrics as ReturnType<typeof vi.fn>).mockResolvedValue(mockRiskMetrics);
    });

    it('renders 4 tabs and defaults to Overview', async () => {
        render(<Performance />);

        await waitFor(() => {
            expect(screen.getByText('Performance Analysis')).toBeInTheDocument();
        });

        // Check for the 4 tabs
        expect(screen.getByRole('button', { name: /Overview/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Attribution/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Risk Metrics/i })).toBeInTheDocument();

        // The default tab should be overview (current existing content is visible)
        expect(screen.getByText('Lifetime P&L Contribution')).toBeInTheDocument();
    });

    it('sends selected period to performance APIs when period buttons are clicked', async () => {
        render(<Performance />);

        await waitFor(() => {
            expect(api.getPerformanceSummary).toHaveBeenCalledWith('all_time', false, false);
            expect(api.getPerformanceHistory).toHaveBeenCalledWith('all_time', false, false);
            expect(api.getGainsAnalysis).toHaveBeenCalledWith('all_time', false, false);
            expect(api.getPerformanceByClass).toHaveBeenCalledWith('all_time', false, false);
        });

        fireEvent.click(screen.getByRole('button', { name: /Last 36M/i }));

        await waitFor(() => {
            expect(api.getPerformanceSummary).toHaveBeenCalledWith('last_36m', false, false);
            expect(api.getPerformanceHistory).toHaveBeenCalledWith('last_36m', false, false);
            expect(api.getGainsAnalysis).toHaveBeenCalledWith('last_36m', false, false);
            expect(api.getPerformanceByClass).toHaveBeenCalledWith('last_36m', false, false);
        });

        fireEvent.click(screen.getByRole('button', { name: /Last 12M/i }));

        await waitFor(() => {
            expect(api.getPerformanceSummary).toHaveBeenCalledWith('last_12m', false, false);
            expect(api.getPerformanceHistory).toHaveBeenCalledWith('last_12m', false, false);
            expect(api.getGainsAnalysis).toHaveBeenCalledWith('last_12m', false, false);
            expect(api.getPerformanceByClass).toHaveBeenCalledWith('last_12m', false, false);
        });
    });

    it('forwards the shared portfolio scope to class analysis', async () => {
        (api.getPerformanceByClass as ReturnType<typeof vi.fn>)
            .mockResolvedValueOnce({
                total_market_value: 1000,
                total_cost_basis: 900,
                top_classes: [
                    {
                        class_name: 'Real Estate (房地产)',
                        market_value: 400,
                        cost_basis: 300,
                        unrealized_pl: 100,
                        realized_pl: 0,
                        lifetime_pl: 100,
                        return_pct: 33.3,
                        weight_pct: 40,
                        asset_count: 1,
                    },
                    {
                        class_name: 'Equity (股票)',
                        market_value: 600,
                        cost_basis: 600,
                        unrealized_pl: 0,
                        realized_pl: 0,
                        lifetime_pl: 0,
                        return_pct: 0,
                        weight_pct: 60,
                        asset_count: 1,
                    },
                ],
                sub_classes: [],
            })
            .mockResolvedValueOnce({
                total_market_value: 600,
                total_cost_basis: 600,
                top_classes: [
                    {
                        class_name: 'Equity (股票)',
                        market_value: 600,
                        cost_basis: 600,
                        unrealized_pl: 0,
                        realized_pl: 0,
                        lifetime_pl: 0,
                        return_pct: 0,
                        weight_pct: 100,
                        asset_count: 1,
                    },
                ],
                sub_classes: [],
            });

        render(<><SharedFilter /><Performance /></>);

        await waitFor(() => {
            expect(screen.getByText('Real Estate (房地产)')).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Toggle portfolio scope/i }));

        await waitFor(() => {
            expect(api.getPerformanceByClass).toHaveBeenCalledWith('all_time', false, true);
        });
    });

    it('applies the shared scope to summary and gains calculations', async () => {
        render(<><SharedFilter /><Performance /></>);

        await waitFor(() => {
            expect(api.getPerformanceSummary).toHaveBeenCalledWith('all_time', false, false);
            expect(api.getPerformanceHistory).toHaveBeenCalledWith('all_time', false, false);
            expect(api.getGainsAnalysis).toHaveBeenCalledWith('all_time', false, false);
        });

        fireEvent.click(screen.getByRole('button', { name: /Toggle portfolio scope/i }));

        await waitFor(() => {
            expect(api.getPerformanceSummary).toHaveBeenCalledWith('all_time', false, true);
            expect(api.getPerformanceHistory).toHaveBeenCalledWith('all_time', false, true);
            expect(api.getGainsAnalysis).toHaveBeenCalledWith('all_time', false, true);
        });
    });

    it('renders Returns and respects both shared chart scope settings', async () => {
        render(<><SharedFilter /><Performance /></>);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Returns/i }));

        await waitFor(() => {
            expect(screen.getByText('TWR (window)')).toBeInTheDocument();
            expect(screen.getByText('+15.25%')).toBeInTheDocument();
            expect(screen.getByText('TWR YTD')).toBeInTheDocument();
            expect(screen.getByText('+3.50%')).toBeInTheDocument();
            expect(screen.getByText('XIRR (annualized)')).toBeInTheDocument();
            expect(screen.getByText('+14.20%')).toBeInTheDocument();
            expect(api.getPerformanceHistory).toHaveBeenLastCalledWith('all_time', false, false);
        });
        fireEvent.click(screen.getByRole('button', { name: /Toggle portfolio scope/i }));
        await waitFor(() => {
            expect(api.getReturns).toHaveBeenLastCalledWith('all_time', false, true);
        });
    });

    it('keeps method details in one popover and uses account chart data', async () => {
        (api.getReturns as ReturnType<typeof vi.fn>).mockResolvedValue({ ...mockReturns,
            twr_review_state: 'candidate', mwr_solver_status: 'solved_ambiguity_not_ruled_out' });
        render(<Performance />);
        await waitFor(() => expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /Returns/i }));
        await waitFor(() => expect(screen.getByText('Investment account value')).toBeInTheDocument());
        expect(screen.getByText('Investment accounts · data through 2026-08-31 · estimate')).toBeInTheDocument();
        expect(screen.getByTestId('account-chart')).toHaveTextContent('"invested_cny":1200');
        expect(screen.queryByText(/Monthly Modified Dietz/)).not.toBeInTheDocument();
        expect(screen.queryByText(/additional solutions/i)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Methodology & data quality' }));
        expect(screen.getByRole('dialog')).toHaveTextContent('Monthly Modified Dietz');
        expect(screen.getByRole('dialog')).toHaveTextContent('Excludes household bank deposits');
        expect(screen.getByRole('dialog')).toHaveTextContent('unreviewed estimate');
        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        expect(screen.queryByRole('dialog')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: /Last 12M/i }));
        await waitFor(() => expect(api.getReturns).toHaveBeenLastCalledWith('last_12m', false, false));
    });

    it('shows one reason card and no KPIs when the account window is unavailable', async () => {
        (api.getReturns as ReturnType<typeof vi.fn>).mockResolvedValue({ ...mockReturns,
            investment_bridge: null, twr_cumulative: null, twr_unavailable_reason: 'default' });
        render(<Performance />);
        await waitFor(() => expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /Returns/i }));
        await waitFor(() => expect(api.getReturns).toHaveBeenCalled());
        expect(screen.queryByText('TWR (window)')).toBeNull();
        expect(screen.queryByTestId('account-chart')).toBeNull();
    });

    it('renders the account scope and method popover in Chinese', async () => {
        await act(async () => { await i18n.changeLanguage('zh-CN'); });
        try {
            render(<Performance />);
            await waitFor(() => expect(screen.getByRole('button', { name: '收益' })).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: '收益' }));
            await waitFor(() => expect(screen.getByText('投资账户市值')).toBeInTheDocument());
            expect(screen.getByText('投资账户 · 数据截至 2026-08-31 · 估算')).toBeInTheDocument();
            fireEvent.click(screen.getByRole('button', { name: '计算方法与数据质量' }));
            expect(screen.getByRole('dialog')).toHaveTextContent('月度修正迪茨法');
        } finally {
            await act(async () => { await i18n.changeLanguage('en'); });
        }
    });

    it('applies Returns metric value colors for positive, negative, and zero values', async () => {
        (api.getReturns as ReturnType<typeof vi.fn>).mockResolvedValue({
            ...mockReturns,
            twr_cumulative: 8.5,
            twr_ytd: -2.25,
            twr_1y: 0,
            mwr_xirr: null
        });

        render(<Performance />);
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument();
        });
        fireEvent.click(screen.getByRole('button', { name: /Returns/i }));

        await waitFor(() => {
            expect(screen.getByText('+8.50%')).toBeInTheDocument();
            expect(screen.getByText('-2.25%')).toBeInTheDocument();
            expect(screen.getByText('0.00%')).toBeInTheDocument();
        });

        expect(screen.getByText('+8.50%')).toHaveClass('text-emerald-600');
        expect(screen.getByText('-2.25%')).toHaveClass('text-rose-600');
        expect(screen.getByText('0.00%')).toHaveClass('text-slate-400');
    });

    it('renders Attribution tab correctly with API data', async () => {
        render(<Performance />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Attribution/i })).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Attribution/i }));

        await waitFor(() => {
            // Check summary cards
            expect(screen.getByText('Portfolio Return')).toBeInTheDocument();
            expect(screen.getByText('+12.50%')).toBeInTheDocument();
            expect(screen.getByText('Excess Return')).toBeInTheDocument();
            expect(screen.getByText('+2.50%')).toBeInTheDocument();

            // Check table details
            expect(screen.getByText('Equity')).toBeInTheDocument();
            expect(screen.getByText('60.0%')).toBeInTheDocument(); // port weight
            expect(screen.getByText('15.00%')).toBeInTheDocument(); // port ret
            expect(screen.getByText('+1.50%')).toBeInTheDocument(); // total effect
        });
    });

    it('renders Risk Metrics tab correctly with API data', async () => {
        render(<Performance />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Risk Metrics/i })).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Risk Metrics/i }));

        await waitFor(() => {
            // Check risk cards
            expect(screen.getByText('Sharpe Ratio')).toBeInTheDocument();
            expect(screen.getByText('1.25')).toBeInTheDocument();
            expect(screen.getByText('Max Drawdown')).toBeInTheDocument();
            expect(screen.getByText('-15.20%')).toBeInTheDocument();
            expect(screen.getByText('Annual Volatility')).toBeInTheDocument();
            expect(screen.getByText('18.50%')).toBeInTheDocument();

            // Check data points label
            expect(screen.getByText(/Based on 36 data points/i)).toBeInTheDocument();
        });
    });

    it('enriches Risk Metrics cards with threshold borders, scale bars, and descriptions', async () => {
        render(<Performance />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Risk Metrics/i })).toBeInTheDocument();
        });
        fireEvent.click(screen.getByRole('button', { name: /Risk Metrics/i }));

        await waitFor(() => {
            expect(screen.getByText('Sharpe Ratio')).toBeInTheDocument();
        });

        expect(screen.getByText('Sharpe Ratio').closest('.rounded-xl')).toHaveClass('border-green-200');
        expect(screen.getByText('Sortino Ratio').closest('.rounded-xl')).toHaveClass('border-amber-200');
        expect(screen.getByText('Max Drawdown').closest('.rounded-xl')).toHaveClass('border-amber-200');
        expect(screen.getByText('Calmar Ratio').closest('.rounded-xl')).toHaveClass('border-amber-200');
        expect(screen.getByText('Annual Volatility').closest('.rounded-xl')).toHaveClass('border-amber-200');
        expect(screen.getByText('Total Return').closest('.rounded-xl')).toHaveClass('border-green-200');

        expect(screen.getByTestId('risk-bar-sharpe')).toBeInTheDocument();
        expect(screen.getByTestId('risk-bar-sortino')).toBeInTheDocument();
        expect(screen.getByTestId('risk-bar-drawdown')).toBeInTheDocument();
        expect(screen.getByTestId('risk-bar-calmar')).toBeInTheDocument();
        expect(screen.getByTestId('risk-bar-volatility')).toBeInTheDocument();
        expect(screen.queryByTestId('risk-bar-total-return')).not.toBeInTheDocument();

        expect(screen.getByText(/Risk-adjusted return per unit of total volatility/i)).toBeInTheDocument();
        expect(screen.getByText(/Risk-adjusted return per unit of downside volatility/i)).toBeInTheDocument();
        expect(screen.getByText(/Largest peak-to-trough decline. Lower is better./i)).toBeInTheDocument();
        expect(screen.getByText(/Annualized return ÷ Max Drawdown/i)).toBeInTheDocument();
        expect(screen.getByText(/Annualized standard deviation of returns. Lower = less risk./i)).toBeInTheDocument();
        expect(screen.getByText(/Overall portfolio return since first data point./i)).toBeInTheDocument();
    });

    it('shows limited-data warning notes for positive drawdown and extreme volatility', async () => {
        (api.getPerformanceRiskMetrics as ReturnType<typeof vi.fn>).mockResolvedValue({
            max_drawdown: 12.5,
            sharpe_ratio: 0.9,
            sortino_ratio: 1.1,
            calmar_ratio: 0.4,
            volatility_annual: 62.0,
            total_return: 5.0,
            data_points: 12
        });

        render(<Performance />);
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Risk Metrics/i })).toBeInTheDocument();
        });
        fireEvent.click(screen.getByRole('button', { name: /Risk Metrics/i }));

        await waitFor(() => {
            expect(screen.getByText('Max Drawdown')).toBeInTheDocument();
            expect(screen.getByText('Annual Volatility')).toBeInTheDocument();
        });

        expect(screen.getByText('May reflect limited data.')).toBeInTheDocument();
        expect(screen.getByText('High volatility may reflect limited data.')).toBeInTheDocument();
    });

    it('handles null values by displaying "Insufficient data"', async () => {
        (api.getReturns as ReturnType<typeof vi.fn>).mockResolvedValue({
            ...mockReturns,
            twr_cumulative: null,
            twr_ytd: null,
            twr_1y: null,
            mwr_xirr: null
        });

        render(<Performance />);
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Returns/i })).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Returns/i }));

        await waitFor(() => {
            expect(screen.getByText('Investment return is unavailable because a complete matching value and flow series is missing.')).toBeInTheDocument();
            expect(screen.queryByText('TWR (window)')).toBeNull();
        });
    });
});
