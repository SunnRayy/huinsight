import React from 'react';
import { Trans, useTranslation } from 'react-i18next';
import type { DecisionAlert } from '../src/services/api';
import { useLanguage } from '../src/context/useLanguage';
import { localizedClassName } from '../src/utils/localizedClassName';

/**
 * Drift-alert text shared by the Dashboard's Action Center and the Decision
 * Hub (Round 7 #1): the localized title/message, and the yardstick line that
 * says which targets the alert measured against — "vs risk profile: Balanced
 * (default) — change".
 *
 * The backend's `title` / `message` are English. For drift alerts the
 * structured `data` (see src/services/alert_generator.py) carries everything
 * needed to render them in either language; any other alert, or a payload
 * without that data, falls back to the backend strings unchanged.
 *
 * "(default)" comes from `yardstick.is_default`, a stored flag
 * (risk_profiles.activated_by_user_at), never from the profile's name. The
 * profile name itself is user data and renders verbatim.
 */

interface Yardstick {
    kind: 'strategic' | 'risk_profile';
    profile_id?: number | null;
    profile_name?: string | null;
    is_default?: boolean | null;
}

interface DriftData {
    asset_class?: string;
    asset_class_cn?: string | null;
    drift_pct?: number;
    actual_pct?: number;
    target_pct?: number;
    yardstick?: Yardstick | null;
}

const RISK_PROFILES_PATH = '/risk-profiles';

function driftData(alert: DecisionAlert): DriftData | null {
    if (alert.category !== 'drift' || !alert.data) return null;
    return alert.data as DriftData;
}

export function useAlertText(alert: DecisionAlert): { title: string; message: string } {
    const { t } = useTranslation('common');
    const { lang } = useLanguage();
    const d = driftData(alert);
    if (!d || d.asset_class == null || d.drift_pct == null) {
        return { title: alert.title, message: alert.message };
    }
    const title = t('driftAlert.title', {
        assetClass: localizedClassName(d.asset_class, d.asset_class_cn, lang),
        drift: d.drift_pct.toFixed(1),
    });
    const message = d.actual_pct != null && d.target_pct != null
        ? t('driftAlert.message', { actual: d.actual_pct.toFixed(1), target: d.target_pct.toFixed(1) })
        : alert.message;
    return { title, message };
}

export const DriftYardstick: React.FC<{ alert: DecisionAlert; style?: React.CSSProperties; className?: string }> = ({
    alert, style, className,
}) => {
    const { t } = useTranslation('common');
    const y = driftData(alert)?.yardstick;
    if (!y) return null;

    if (y.kind === 'strategic') {
        return <div className={className} style={style} data-testid="drift-yardstick">{t('driftAlert.vsStrategic')}</div>;
    }

    const link = <a href={RISK_PROFILES_PATH} style={{ color: 'var(--color-primary)', textDecoration: 'none', fontWeight: 600 }} />;
    const name = y.profile_name || t('driftAlert.unnamedProfile');
    const i18nKey = y.is_default ? 'driftAlert.vsRiskProfileDefault' : 'driftAlert.vsRiskProfile';
    return (
        <div className={className} style={style} data-testid="drift-yardstick">
            <Trans t={t} i18nKey={i18nKey} values={{ name }} components={{ profiles: link }} />
        </div>
    );
};
