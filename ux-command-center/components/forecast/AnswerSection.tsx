import React, { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import type { ForecastLevers } from '../../src/services/api/types';
import { useFormatCurrency } from '../../src/utils/format';

/**
 * AnswerSection — "Your Path" (W-5) Section 2.1, "The Answer".
 * docs/design/2026-07-26-your-path.dc.html.md §2.1.
 *
 * Pure rendering of `GET /forecast/levers` (`levers.base` + `levers.goal`) —
 * NEVER re-derives a projection number client-side (§4b HARD REQUIREMENT).
 * The fan chart that used to live inside this card has moved to its own
 * card (FanChart.tsx, design §2.2) — this component is headline + method
 * popover + the four-chip summary row only.
 */

interface AnswerSectionProps {
    levers: ForecastLevers | null;
    loading: boolean;
    /** Switches the parent tab to "Goals" — used by the config_fallback CTA
     * (never present a fallback target as the owner's own goal). */
    onGoToGoals: () => void;
}

function Chip({ label, value, nowrap }: Readonly<{ label: string; value: React.ReactNode; nowrap?: boolean }>) {
    return (
        <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-fg-3)' }}>
                {label}
            </div>
            <div
                className="kpi-value"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, fontWeight: 600, whiteSpace: nowrap ? 'nowrap' : undefined, display: 'block' }}
            >
                {value}
            </div>
        </div>
    );
}

function fmtBoundYear(y: number | null, rangeKnown: boolean, horizonYears: number | null): string {
    if (!rangeKnown) return '—';
    if (y == null) return horizonYears != null ? `>${horizonYears}y` : '—';
    // §3.4 — our analytic crossing-time percentiles carry ~5-9% error vs a
    // 20,000-path Monte Carlo pin; showing more than 1 decimal is false
    // precision (design-record §3.4).
    return y.toFixed(1);
}

const DAYS_PER_MONTH = 365 / 12;

/**
 * Round 7 #2 — the headline's "this is an assumption" banner. Shown whenever
 * the projection uses the configured long-run return/volatility because the
 * portfolio's history fails the same sufficiency rule as integrity check
 * twr_in_range. Plain text on the card, not a tooltip. "Edit assumption"
 * opens where to change it: the values live in config (there is no settings
 * surface for them), so the honest edit path is the config keys.
 */
function AssumptionBanner({ assumption }: Readonly<{ assumption: NonNullable<ForecastLevers['assumption']> }>) {
    const { t } = useTranslation('reports');
    const [editOpen, setEditOpen] = useState(false);
    const pct = (n: number, digits: number) => `${(n * 100).toFixed(digits)}%`;
    const editButton = (
        <button
            type="button"
            onClick={() => setEditOpen(v => !v)}
            aria-expanded={editOpen}
            style={{ background: 'none', border: 'none', padding: 0, font: 'inherit', fontWeight: 700, color: 'inherit', textDecoration: 'underline', cursor: 'pointer' }}
        />
    );
    return (
        <div className="sig sig--warning" data-testid="forecast-assumption-banner" style={{ display: 'block', marginBottom: 12, padding: '8px 12px', lineHeight: 1.5 }}>
            <Trans
                t={t}
                i18nKey="forecast.answerSection.assumptionBanner"
                values={{
                    minMonths: Math.round(assumption.min_history_days / DAYS_PER_MONTH),
                    maxMonths: Math.round(assumption.max_history_days / DAYS_PER_MONTH),
                    ret: pct(assumption.expected_return, 1),
                    vol: pct(assumption.volatility, 0),
                }}
                components={{ edit: editButton }}
            />
            {editOpen && (
                <div style={{ marginTop: 6, fontWeight: 400 }}>
                    <Trans
                        t={t}
                        i18nKey="forecast.answerSection.assumptionEditHelp"
                        values={{ keys: assumption.config_keys.join(', ') }}
                        components={{ code: <code /> }}
                    />
                </div>
            )}
        </div>
    );
}

export const AnswerSection: React.FC<AnswerSectionProps> = ({ levers, loading, onGoToGoals }) => {
    const { t } = useTranslation('reports');
    const formatMoney = useFormatCurrency();
    const fmtPct = (n: number | null | undefined): string => (n == null ? '—' : `${(n * 100).toFixed(1)}%`);
    const [methodOpen, setMethodOpen] = useState(false);

    const base = levers?.base ?? null;
    const goal = levers?.goal ?? null;
    const target = base?.target ?? null;
    const headlineYears = base?.years_to_target ?? null;
    // Round 7 #2: non-null only while history is too short to trust a measured
    // return — every number on this card is then assumption-based.
    const assumption = base?.return_basis === 'assumption' ? (levers?.assumption ?? null) : null;

    const crossingYears = base?.crossing_years ?? null;
    const rangeKnown = target != null && !!crossingYears;
    // Horizon isn't known inside this card (it's chart geometry — FanChart
    // owns it); an unbounded ">Ny" caption isn't needed here since the
    // caption only ever prints the two bound numbers, not ">N".
    const lowLabel = fmtBoundYear(crossingYears?.p25 ?? null, rangeKnown, null);
    const highLabel = fmtBoundYear(crossingYears?.p75 ?? null, rangeKnown, null);

    return (
        <section
            className="card"
            style={{
                position: 'relative',
                borderTop: '3px solid var(--color-primary)',
                padding: '18px 24px 16px 28px',
                // .card sets overflow:hidden (rounded-corner clipping) — the
                // method popover is position:absolute WITHIN this card and
                // must escape it, or it gets clipped at the card's own
                // bottom edge instead of floating over the content below.
                overflow: 'visible',
            }}
        >
            <button
                type="button"
                className="method-btn"
                style={{ position: 'absolute', top: 14, right: 18 }}
                onClick={() => setMethodOpen(v => !v)}
                aria-label={t('forecast.answerSection.methodology')}
                title={t('forecast.answerSection.methodologyTitle')}
            >
                <span className="material-symbols-outlined">info</span>
            </button>
            {methodOpen && (
                <div className="method-pop" role="dialog">
                    <p style={{ margin: 0 }}>
                        <Trans t={t} i18nKey="forecast.answerSection.methodBasis" components={{ b: <b />, code: <code /> }} />
                    </p>
                    <p>
                        <Trans t={t} i18nKey="forecast.answerSection.methodLikelyRange" components={{ b: <b />, i: <i /> }} />
                    </p>
                    <p>
                        {t('forecast.answerSection.methodApproximation')}
                    </p>
                    <p style={{ marginBottom: 0 }}>
                        <Trans t={t} i18nKey="forecast.answerSection.methodLiquidNw" components={{ b: <b /> }} />
                    </p>
                </div>
            )}

            {!levers && loading && (
                <div style={{ fontSize: 13, color: 'var(--color-fg-3)' }}>{t('forecast.answerSection.computing')}</div>
            )}
            {!levers && !loading && (
                <div style={{ fontSize: 13, color: 'var(--color-fg-3)' }}>{t('forecast.answerSection.unavailable')}</div>
            )}
            {levers && assumption && <AssumptionBanner assumption={assumption} />}
            {levers && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 20, flexWrap: 'wrap' }}>
                    <div>
                        <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--color-primary)' }}>
                            {t('forecast.answerSection.yearsTo', { goalName: goal?.name || t('forecast.answerSection.goalFallback') })}
                        </div>
                        {headlineYears != null && target != null ? (
                            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 32, letterSpacing: '-0.02em', lineHeight: 1 }}>
                                {headlineYears.toFixed(1)}
                                <span style={{ fontSize: 20, color: 'var(--color-fg-3)', marginLeft: 6 }}>{t('forecast.answerSection.years')}</span>
                            </div>
                        ) : (
                            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22, color: 'var(--color-fg-3)' }}>
                                {t('forecast.answerSection.goalNotReachable')}
                            </div>
                        )}
                        <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--color-fg-3)', marginTop: 4 }}>
                            {t('forecast.answerSection.likelyRange', { low: lowLabel, high: highLabel })}
                        </div>
                        {goal?.source === 'config_fallback' && (
                            <div className="sig sig--warning" style={{ marginTop: 10, cursor: 'pointer' }} onClick={onGoToGoals} role="button" tabIndex={0}>
                                {t('forecast.answerSection.noRetirementGoal')}
                            </div>
                        )}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, auto)', gap: '6px 28px', textAlign: 'right', paddingRight: 26 }}>
                        <Chip label={t('forecast.answerSection.chipGoal')} value={target != null ? formatMoney(target) : '—'} />
                        <Chip label={t('forecast.answerSection.chipLiquidNw')} value={base?.current_nw != null ? formatMoney(base.current_nw) : '—'} />
                        <Chip
                            label={t('forecast.answerSection.chipContribution')}
                            value={base?.monthly_contribution != null ? <>{formatMoney(base.monthly_contribution)}{t('forecast.answerSection.perMonth')}</> : '—'}
                            nowrap
                        />
                        <Chip
                            label={assumption ? t('forecast.answerSection.chipReturnVolAssumed') : t('forecast.answerSection.chipReturnVol')}
                            value={`${fmtPct(base?.expected_return)} / ${fmtPct(base?.volatility)}`}
                            nowrap
                        />
                    </div>
                </div>
            )}
        </section>
    );
};
