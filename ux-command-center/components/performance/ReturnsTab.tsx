import { CoverageChip } from './CoverageChip';
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import type { PerformanceReturns } from '../../src/services/api';
import { useFormatCurrency } from '../../src/utils/format';

export function ReturnsTab({ returns }: { returns: PerformanceReturns }) {
    const { t } = useTranslation('performance');
    const formatCNY = useFormatCurrency();
    const [methodOpen, setMethodOpen] = useState(false);
    const bridge = returns.investment_bridge;
    const card = 'bg-white dark:bg-card-dark border border-slate-200 dark:border-border-dark rounded-xl';
    const header = <div className="relative flex items-center gap-2 flex-wrap">
            {returns.twr_as_of && <span className="text-xs text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full px-3 py-1">
                {t('returns.accountChip', { asOf: returns.twr_as_of })}
            </span>}
            <CoverageChip status={returns.coverage_status} />
            <button type="button" aria-label={t('returns.methodology')} aria-expanded={methodOpen}
                onClick={() => setMethodOpen(v => !v)} className="text-slate-500 dark:text-slate-400 rounded-full p-1">ⓘ</button>
            {methodOpen && <div role="dialog" aria-label={t('returns.methodology')}
                className={`${card} absolute z-20 top-full mt-2 left-0 p-5 shadow-lg w-[min(32rem,100%)] text-sm text-slate-600 dark:text-slate-300 space-y-3`}>
                <CoverageChip status={returns.coverage_status} detail />
                <p>{t('returns.bridgeAccounts')}</p>
                <p>{t('returns.methodDetails')}</p>
                <p>{t('returns.reviewState', { state: t(`returns.review.${returns.twr_review_state || 'candidate'}`) })}</p>
                {returns.mwr_solver_status !== 'solved' && <p>{t(returns.mwr_xirr == null ? 'returns.xirrNoSolution' : 'returns.xirrAmbiguity')}</p>}
                <button type="button" onClick={() => setMethodOpen(false)} className="text-primary underline">{t('returns.closeMethod')}</button>
            </div>}
        </div>;
    if (!bridge || returns.twr_cumulative == null) {
        return <div className="space-y-6 min-w-0">{header}<div className={`${card} p-8 text-center text-slate-500 dark:text-slate-400`}>
            {t(`returns.unavailableReasons.${returns.twr_unavailable_reason || 'default'}`)}
        </div></div>;
    }
    const metrics = [
        ['twrCumulative', 'twrCumulativeDesc', returns.twr_cumulative],
        ['twrYtd', 'twrYtdDesc', returns.twr_ytd],
        ['twr1y', 'twr1yDesc', returns.twr_1y],
        ['mwrXirr', 'mwrXirrDesc', returns.mwr_xirr],
    ] as const;
    const values = [
        ['openingValue', bridge.opening_value_cny],
        ['netContribution', bridge.net_external_flow_cny],
        ['investmentGain', bridge.investment_gain_cny],
        ['closingValue', bridge.closing_value_cny],
    ] as const;
    return <div className="space-y-6 min-w-0">
        {header}
        <div className={`${card} p-6 shadow-sm min-w-0`}>
            <h3 className="text-sm font-bold mb-4">{t('returns.accountValue')}</h3>
            <div className="h-[300px] min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={returns.account_series || []} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={36} tickFormatter={date => date.slice(0, 7)} />
                        <YAxis width={60} tick={{ fontSize: 10 }} tickFormatter={value => t('returns.axisWan', { value: (value / 10000).toFixed(0) })} />
                        <Tooltip formatter={(value: number) => formatCNY(value, 0)} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Area type="monotone" dataKey="value_cny" name={t('returns.accountValue')} stroke="#3b82f6" strokeWidth={2} fill="#3b82f6" fillOpacity={0.15} />
                        <Line type="monotone" dataKey="invested_cny" name={t('returns.amountInvested')} stroke="#94a3b8" strokeWidth={1} dot={false} />
                    </ComposedChart>
                </ResponsiveContainer>
            </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {metrics.map(([label, description, value]) => <div key={label} className={`${card} p-5 min-w-0`}>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">{t(`returns.${label}`)}</p>
                <h3 className={`text-2xl font-mono font-bold ${value == null ? 'text-slate-400' : value === 0 ? 'text-slate-400' : value > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                    {value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`}
                </h3>
                <hr className="my-3 border-slate-100 dark:border-border-dark" />
                <p className="text-xs text-slate-400">{t(`returns.${description}`)}</p>
            </div>)}
        </div>
        <div className={`${card} p-5 flex flex-wrap items-center gap-y-4`}>
            {values.map(([label, value], i) => <React.Fragment key={label}>
                {i > 0 && <span aria-hidden="true" className="text-slate-400 px-2">{i === 3 ? '=' : '+'}</span>}
                <div className="flex-1 min-w-[125px]">
                    <p className="text-xs text-slate-500 mb-1">{t(`returns.${label}`)}</p>
                    <p className="font-mono font-bold text-sm break-words">{formatCNY(value, 0)}</p>
                </div>
            </React.Fragment>)}
        </div>
    </div>;
}
