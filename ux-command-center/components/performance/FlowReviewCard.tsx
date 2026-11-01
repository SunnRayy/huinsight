import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { api } from '../../src/services/api';
import type { FlowReviewDecision, FlowReviewItem } from '../../src/services/api';

const reasonKeys: Record<string, string> = {
    'CN cancelled paid application needs confirmation': 'cancelledPaid',
    'CN status needs confirmation': 'status',
    'CN website business type or bank account needs confirmation': 'bankAccount',
    'Schwab unclassified cash action': 'cashAction',
    'Gold unknown transaction type': 'transactionType',
    'RSU unknown transaction type': 'transactionType',
    'RSU commission exceeds gross proceeds': 'commission',
    'Boundary amount unavailable or zero': 'amount',
    'Dated FX unavailable': 'fx',
    'IBKR deposits unknown': 'ibkr',
};
const button = 'rounded-full border border-slate-200 dark:border-border-dark px-3 py-1 text-xs text-slate-600 dark:text-slate-300 disabled:opacity-50';

export function FlowReviewCard() {
    const { t } = useTranslation('performance');
    const { hash } = useLocation();
    const [items, setItems] = useState<FlowReviewItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
    const [saveError, setSaveError] = useState(false);
    const [pending, setPending] = useState(0);
    const load = useCallback(async () => {
        setLoading(true);
        setLoadError(false);
        try { setItems((await api.getFlowReview()).items); }
        catch { setLoadError(true); }
        finally { setLoading(false); }
    }, []);
    useEffect(() => { void load(); }, [load]);
    useEffect(() => {
        if (hash === '#investment-confirmations') document.getElementById('investment-confirmations')?.scrollIntoView?.();
    }, [hash]);
    async function save(item: FlowReviewItem, decision: FlowReviewDecision) {
        const index = items.findIndex(row => row.event_key === item.event_key);
        setSaveError(false);
        setPending(value => value + 1);
        setItems(rows => rows.filter(row => row.event_key !== item.event_key));
        try { await api.saveFlowReview(item.event_key, decision); }
        catch {
            setItems(rows => [...rows.slice(0, index), item, ...rows.slice(index)]);
            setSaveError(true);
        } finally { setPending(value => value - 1); }
    }
    return <section id="investment-confirmations" className="bg-white dark:bg-card-dark border border-slate-200 dark:border-border-dark rounded-xl p-5 scroll-mt-6">
        <h2 className="text-sm font-bold mb-3">{t('flows.title')}</h2>
        {loading ? <span className="text-sm text-slate-500">{t('flows.loading')}</span>
            : loadError ? <div role="alert" className="text-sm text-rose-600">{t('flows.loadError')} <button className={button} onClick={() => void load()}>{t('flows.retry')}</button></div>
            : <>
                {saveError && <div role="alert" className="text-sm text-rose-600 mb-2">{t('flows.saveError')}</div>}
                {items.length === 0 && <span className="text-sm text-slate-500" role="status">{t(pending ? 'flows.saving' : 'flows.empty')}</span>}
                {items.map(item => <ReviewRow key={item.event_key} item={item} save={decision => void save(item, decision)} />)}
            </>}
    </section>;
}

const ReviewRow: React.FC<{ item: FlowReviewItem; save: (decision: FlowReviewDecision) => void }> = ({ item, save }) => {
    const { t, i18n } = useTranslation('performance');
    const [manual, setManual] = useState(false);
    const [amount, setAmount] = useState('');
    const [invalid, setInvalid] = useState(false);
    const noActivity = item.reason === 'no_activity_unconfirmed';
    const uploadNeeded = item.reason === 'upload_needed';
    const source = t(`flows.sources.${item.source}`, { defaultValue: item.source });
    const month = new Date(`${item.event_date}T12:00:00Z`).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', timeZone: 'UTC' });
    const unknownDeposits = item.reason === 'IBKR deposits unknown';
    const fsZero = item.reason === 'fs_zero_with_position';
    const fsUnchanged = item.reason === 'fs_value_unchanged';
    const fsCheck = fsZero || fsUnchanged;
    const money = (value?: number | null) => value == null ? '—'
        : `¥${value.toLocaleString(i18n.resolvedLanguage, { maximumFractionDigits: 0 })}`;
    const column = t(`flows.fsColumns.${item.column}`, { defaultValue: item.column || '' });
    function submit() {
        const value = Number(amount);
        if (!amount.trim() || !Number.isFinite(value) || value === 0) { setInvalid(true); return; }
        save({ decision: 'manual', amount_cny: value });
    }
    return <div className="border-t border-slate-100 dark:border-border-dark py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-slate-600 dark:text-slate-300">
            <span className="font-mono text-xs">{item.event_date}</span>
            <span className="mx-2">{t(`flows.sources.${item.source}`, { defaultValue: item.source })}</span>
            <span>{fsZero ? t('flows.fsZero', { column, month, estimate: money(item.estimate_cny) })
                : fsUnchanged ? t('flows.fsUnchanged', { column, month, value: money(item.amount) })
                : uploadNeeded ? t('flows.uploadThrough', { source, date: item.latest_date || '—' })
                : noActivity ? t('flows.uploadNewer', { source }) : t(`flows.reasons.${reasonKeys[item.reason] || 'default'}`)}</span>
            {!fsCheck && item.amount != null && <span className="ml-2 font-mono">{item.currency} {item.amount.toLocaleString(i18n.resolvedLanguage, { maximumFractionDigits: 2 })}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
            {fsCheck ? <button className={button} onClick={() => save({ decision: 'internal' })}>{t('flows.fsValueCorrect')}</button>
            : uploadNeeded ? null : noActivity ? <button className={button} onClick={() => save({ decision: 'internal' })}>{t('flows.noActivity', { source, month })}</button> : unknownDeposits ? <>
                <button className={button} onClick={() => save({ decision: 'internal' })}>{t('flows.noDeposits')}</button>
                <button className={button} onClick={() => setManual(value => !value)}>{t('flows.enterAmount')}</button>
                {manual && <>
                    <input aria-label={t('flows.signedAmount')} inputMode="decimal" value={amount} onChange={event => { setAmount(event.target.value); setInvalid(false); }}
                        className="border border-slate-200 dark:border-border-dark rounded-lg px-2 py-1 text-sm w-36 bg-transparent" placeholder={t('flows.signedAmount')} />
                    <button className={button} onClick={submit}>{t('flows.save')}</button>
                    {invalid && <span role="alert" className="text-xs text-rose-600">{t('flows.invalidAmount')}</span>}
                </>}
            </> : <>
                <button className={button} onClick={() => save({ decision: 'external_in' })}>{t('flows.externalIn')}</button>
                <button className={button} onClick={() => save({ decision: 'external_out' })}>{t('flows.externalOut')}</button>
                <button className={button} onClick={() => save({ decision: 'internal' })}>{t('flows.internal')}</button>
            </>}
        </div>
    </div>;
}
