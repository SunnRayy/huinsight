import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { FlowCoverageStatus } from '../../src/services/api';

export function CoverageChip({ status, detail = false }: { status?: FlowCoverageStatus; detail?: boolean }) {
    const { t, i18n } = useTranslation('performance');
    if (status?.in_progress || !status?.blockers.length || !status.next_month) return null;
    const month = new Date(`${status.next_month}T12:00:00Z`).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', timeZone: 'UTC' });
    const labels = status.blockers.map(blocker => {
        const source = t(`flows.sources.${blocker.source}`, { defaultValue: blocker.source || '' });
        const label = t(`flows.blockers.${blocker.code}`, { source, count: blocker.count });
        return detail && blocker.code === 'source_data_behind'
            ? `${label} (${t('flows.latest', { date: blocker.latest_date || '—' })})${blocker.action_hint ? ` — ${t('flows.sourceAction', { source })}` : ''}` : label;
    });
    const text = t('flows.waiting', { month, items: labels.join(t('flows.separator')) });
    if (detail) return <div>{text}</div>;
    const className = 'text-xs text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 rounded-full px-3 py-1 max-w-full min-w-0 truncate';
    return status.blockers.some(b => b.code === 'open_reviews' && (b.count || 0) > 0)
        ? <Link className={className} to="/cash-flow-classification#investment-confirmations">{text}</Link>
        : <span className={className}>{text}</span>;
}
