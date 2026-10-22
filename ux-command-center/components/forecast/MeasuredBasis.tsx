import React, { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import type { ForecastLeversBase } from '../../src/services/api/types';

export function MeasuredBasis({ base, editable = false }: { base: ForecastLeversBase; editable?: boolean }) {
    const { t, i18n } = useTranslation('reports');
    const [editOpen, setEditOpen] = useState(false);
    const month = (value?: string | null) => value ? new Intl.DateTimeFormat(i18n.language, {
        month: 'short', year: 'numeric', timeZone: 'UTC',
    }).format(new Date(`${value}T00:00:00Z`)) : '—';
    return <div style={{ fontSize: 12, color: 'var(--color-fg-3)', overflowWrap: 'anywhere' }}>
        <span data-testid="forecast-measured-basis" style={{ display: 'inline-block', background: 'var(--fill-neutral-soft)' , border: '1px solid var(--color-border)', borderRadius: 12, padding: '3px 8px' }}>
            {t('forecast.answerSection.measuredBasis', { start: month(base.window_start), end: month(base.window_end) })}
        </span>
        {editable && <button type="button" aria-expanded={editOpen} onClick={() => setEditOpen(v => !v)} style={{ background: 'none', border: 0, color: 'inherit', font: 'inherit', textDecoration: 'underline', marginLeft: 8, cursor: 'pointer' }}>
            {t('forecast.answerSection.editAssumption')}
        </button>}
        {editOpen && <div role="dialog" style={{ marginTop: 8 }}><Trans t={t} i18nKey="forecast.answerSection.measuredEditHelp" components={{ code: <code /> }} /></div>}
    </div>;
}
