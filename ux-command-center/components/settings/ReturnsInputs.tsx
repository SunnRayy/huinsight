import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { api } from '../../src/services/api';
import type { ReturnsInputsState, ReturnsOwnerResult, TtfundCoverageRecord, TwrRereviewChange, TwrRereviewPreview } from '../../src/services/api';
import { useFormatCurrencyStr } from '../../src/utils/format';
import {
    ActionBtn, Card, CardHeader, ChipBtn, FieldLabel, FormInput, FormTextarea, Icon, IconBtn, InfoTip,
    ModalShell, Notice, OpsTable, Pill, SectionTitle,
} from '../operations';
import type { ColDef } from '../operations';

const ROW: React.CSSProperties = { padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 };
const TABLE_BOX: React.CSSProperties = { border: '1px solid var(--color-border)', borderRadius: 8, overflowX: 'auto' };
const ACTIONS: React.CSSProperties = { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 };
const MUTED_NOTE: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--color-fg-3)', margin: 0 };
const SUMMARY_LIST: React.CSSProperties = {
    listStyle: 'none', margin: '12px 0 0', padding: 0, border: '1px solid var(--color-border)', borderRadius: 8,
    fontSize: 12, color: 'var(--color-fg-2)',
};
const SUMMARY_ITEM: React.CSSProperties = { padding: '8px 12px', borderTop: '1px solid var(--color-border-soft)', display: 'flex', gap: 8, flexWrap: 'wrap' };
const mono = (text: React.ReactNode) => <span className="uis-mono">{text}</span>;

/** Data the investment Returns need from the user (2026-11-09): TTFund months with
 *  no trades, and corrections to locked months. Performance → Returns links here. */
export function ReturnsInputs() {
    const { t } = useTranslation('performance');
    const { hash } = useLocation();
    const [state, setState] = useState<ReturnsInputsState | null>(null);
    const [lockedNeedsAction, setLockedNeedsAction] = useState(false);
    const load = useCallback(() => { api.getReturnsInputs().then(setState).catch(() => setState(null)); }, []);
    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        if (hash === '#returns-inputs') document.getElementById('returns-inputs')?.scrollIntoView?.();
    }, [hash, state]);
    const ttfundNeedsAction = !!state?.coverage?.blockers.some(b => b.code === 'cn_web_list_missing');
    const actionNeeded = ttfundNeedsAction || (state?.corrections ?? 0) > 0 || lockedNeedsAction;
    return <section id="returns-inputs" data-testid="returns-inputs" style={{ marginBottom: 24, scrollMarginTop: 24 }}>
        <Card padding={0}>
            <CardHeader icon="query_stats" title={t('returnsInputs.title')} sub={t('returnsInputs.subtitle')}
                right={state && <Pill tone={actionNeeded ? 'warning' : 'success'}>{t(actionNeeded ? 'returnsInputs.actionNeeded' : 'returnsInputs.upToDate')}</Pill>} />
            <TtfundRow state={state} needsAction={ttfundNeedsAction} onChanged={load} />
            <div style={{ borderTop: '1px solid var(--color-border-soft)' }}>
                <LockedRow state={state} onChanged={load} onNeedsAction={setLockedNeedsAction} />
            </div>
        </Card>
    </section>;
}

/** SectionTitle plus an InfoTip beside the title (SectionTitle takes a string title, so
 *  the tip cannot go inside it), with the row's pill and quiet actions on the right. */
function RowHeading({ icon, title, why, right }: { icon: string; title: string; why: string; right?: React.ReactNode }) {
    const { t } = useTranslation('performance');
    return <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <SectionTitle icon={icon} title={title} style={{ marginBottom: 0 }} />
            <InfoTip label={t('returnsInputs.whyLabel')}>{why}</InfoTip>
        </div>
        <div style={{ ...ACTIONS, marginLeft: 'auto' }}>{right}</div>
    </div>;
}

// ─── Row 1: TTFund ──────────────────────────────────────────────────────────────

interface Declaration { from: string; to: string; note: string }

function TtfundRow({ state, needsAction, onChanged }: { state: ReturnsInputsState | null; needsAction: boolean; onChanged: () => void }) {
    const { t } = useTranslation('performance');
    const fileRef = useRef<HTMLInputElement | null>(null);
    const [busy, setBusy] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [modal, setModal] = useState<0 | 1 | 2>(0);
    const [draft, setDraft] = useState<Declaration>({ from: '', to: '', note: '' });
    const [result, setResult] = useState<{ kind: 'done' | 'uploadFailed' | 'declareFailed'; end?: string; reason?: string } | null>(null);
    const coverage = state?.coverage?.cn_coverage;
    const records = [...(coverage?.records ?? [])].sort((a, b) => b.from.localeCompare(a.from));
    const open = needsAction || expanded;

    async function run(kind: 'uploadFailed' | 'declareFailed', action: () => Promise<ReturnsOwnerResult>) {
        setBusy(true); setResult(null);
        try {
            const out = await action();
            setResult({ kind: 'done', end: out.coverage?.coverage_end || '—' });
            setModal(0); setDraft({ from: '', to: '', note: '' }); onChanged();
        } catch (e) {
            setModal(0);
            setResult({ kind, reason: (e as Error).message });
        } finally { setBusy(false); }
    }
    const cols: ColDef<TtfundCoverageRecord>[] = [
        { label: t('returnsInputs.ttfund.period'), mono: true, nowrap: true, render: r => `${r.from} → ${r.to}` },
        { label: t('returnsInputs.ttfund.source'), align: 'right', render: r =>
            <Pill tone={r.basis === 'cli_pull' ? 'success' : 'warning'}>{t(`returnsInputs.ttfund.basis.${r.basis}`)}</Pill> },
    ];
    return <div style={ROW}>
        <RowHeading icon="event_available" title={t('returnsInputs.ttfund.title')} why={t('returnsInputs.ttfund.why')}
            right={<>
                {state && <Pill tone={needsAction ? 'warning' : 'success'}>{t(needsAction ? 'returnsInputs.actionNeeded' : 'returnsInputs.upToDate')}</Pill>}
                {!needsAction && <IconBtn icon={expanded ? 'expand_less' : 'expand_more'} ariaExpanded={expanded}
                    ariaLabel={t(expanded ? 'returnsInputs.ttfund.hidePeriods' : 'returnsInputs.ttfund.showPeriods')}
                    onClick={() => setExpanded(v => !v)} />}
            </>} />
        <p className="uis-body" style={{ margin: 0 }}>
            <Trans t={t} i18nKey={needsAction ? 'returnsInputs.ttfund.statusWaiting' : 'returnsInputs.ttfund.statusOk'}
                values={{ date: coverage?.through || '—', count: records.length }} components={{ d: <span className="uis-mono" /> }} />
        </p>
        {open && <>
            {records.length > 0 && <>
                <span className="uis-eyebrow" style={{ fontSize: 10 }}>{t('returnsInputs.ttfund.periods')}</span>
                <div style={TABLE_BOX} data-testid="ttfund-coverage-records">
                    <OpsTable cols={cols} rows={records} density="compact" rowKey={r => `${r.from}-${r.basis}`} />
                </div>
            </>}
            <div style={ACTIONS}>
                <input ref={fileRef} type="file" accept=".json,application/json" style={{ display: 'none' }} aria-label={t('returnsInputs.ttfund.upload')}
                    onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void run('uploadFailed', () => api.importTtfundPull(file)); }} />
                <ActionBtn variant="primary" icon={busy ? 'progress_activity' : 'upload_file'} disabled={busy} onClick={() => fileRef.current?.click()}>
                    {t('returnsInputs.ttfund.upload')}
                </ActionBtn>
                <ChipBtn icon="edit_calendar" disabled={busy} onClick={() => setModal(1)}>{t('returnsInputs.ttfund.declareToggle')}</ChipBtn>
            </div>
        </>}
        {result?.kind === 'done' && <Notice>{t('returnsInputs.ttfund.done', { date: result.end })}</Notice>}
        {result?.kind === 'uploadFailed' && <Notice tone="danger" detail={result.reason}>{t('returnsInputs.ttfund.uploadFailed')}</Notice>}
        {result?.kind === 'declareFailed' && <Notice tone="danger" detail={result.reason}
            action={<ChipBtn icon="edit" onClick={() => setModal(1)}>{t('returnsInputs.ttfund.editDeclaration')}</ChipBtn>}>
            {t('returnsInputs.ttfund.declareFailed')}
        </Notice>}
        {modal > 0 && <DeclareModal step={modal} draft={draft} busy={busy} onDraft={setDraft} onStep={setModal}
            onSubmit={() => void run('declareFailed', () => api.attestTtfund(draft.from, draft.to, draft.note.trim()))} />}
    </div>;
}

function DeclareModal({ step, draft, busy, onDraft, onStep, onSubmit }: {
    step: 1 | 2; draft: Declaration; busy: boolean;
    onDraft: (d: Declaration) => void; onStep: (s: 0 | 1 | 2) => void; onSubmit: () => void;
}) {
    const { t } = useTranslation('performance');
    const ids = { from: useId(), to: useId(), note: useId() };
    const valid = !!draft.from && !!draft.to && draft.from <= draft.to && !!draft.note.trim();
    const close = () => onStep(0);
    const footer = step === 1
        ? <>
            <ChipBtn onClick={close}>{t('returnsInputs.cancel')}</ChipBtn>
            <ActionBtn variant="primary" icon="arrow_forward" disabled={!valid} onClick={() => onStep(2)}>{t('returnsInputs.ttfund.continue')}</ActionBtn>
        </>
        : <>
            <ChipBtn onClick={() => onStep(1)}>{t('returnsInputs.ttfund.back')}</ChipBtn>
            <ActionBtn variant="primary" icon={busy ? 'progress_activity' : 'check'} disabled={busy} onClick={onSubmit}>{t('returnsInputs.ttfund.declare')}</ActionBtn>
        </>;
    return <ModalShell title={t('returnsInputs.ttfund.declare')} subtitle={t(`returnsInputs.ttfund.step${step}`)}
        closeLabel={t('returnsInputs.cancel')} onClose={close} footer={footer}>
        {step === 1 ? <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <p className="uis-body" style={{ margin: 0 }}>{t('returnsInputs.ttfund.intro')}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                <div><FieldLabel htmlFor={ids.from}>{t('returnsInputs.ttfund.from')}</FieldLabel>
                    <FormInput id={ids.from} type="date" mono value={draft.from} onChange={from => onDraft({ ...draft, from })} /></div>
                <div><FieldLabel htmlFor={ids.to}>{t('returnsInputs.ttfund.to')}</FieldLabel>
                    <FormInput id={ids.to} type="date" mono value={draft.to} onChange={to => onDraft({ ...draft, to })} /></div>
            </div>
            <div><FieldLabel htmlFor={ids.note}>{t('returnsInputs.ttfund.note')}</FieldLabel>
                <FormTextarea id={ids.note} maxLength={500} value={draft.note} placeholder={t('returnsInputs.ttfund.notePlaceholder')}
                    onChange={note => onDraft({ ...draft, note })} /></div>
        </div> : <div>
            <p className="uis-body" style={{ margin: 0 }}>{t('returnsInputs.ttfund.confirm', { from: draft.from, to: draft.to })}</p>
            <ul style={SUMMARY_LIST}>
                <li style={{ ...SUMMARY_ITEM, borderTop: 'none' }}><span style={{ color: 'var(--color-fg-3)' }}>{t('returnsInputs.ttfund.period')}</span>{mono(`${draft.from} → ${draft.to}`)}</li>
                <li style={SUMMARY_ITEM}><span style={{ color: 'var(--color-fg-3)' }}>{t('returnsInputs.ttfund.shownAs')}</span>
                    <Pill tone="warning">{t('returnsInputs.ttfund.basis.owner_attestation')}</Pill></li>
                <li style={SUMMARY_ITEM}><span style={{ color: 'var(--color-fg-3)' }}>{t('returnsInputs.ttfund.note')}</span><span>{draft.note.trim()}</span></li>
            </ul>
        </div>}
    </ModalShell>;
}

// ─── Row 2: corrections to locked months ────────────────────────────────────────

function LockedRow({ state, onChanged, onNeedsAction }: {
    state: ReturnsInputsState | null; onChanged: () => void; onNeedsAction: (v: boolean) => void;
}) {
    const { t } = useTranslation('performance');
    const money = useFormatCurrencyStr();
    const ids = { reviewer: useId(), evidence: useId() };
    const [preview, setPreview] = useState<TwrRereviewPreview | null>(null);
    const [busy, setBusy] = useState(false);
    const [reviewer, setReviewer] = useState('');
    const [evidence, setEvidence] = useState('');
    const [confirming, setConfirming] = useState(false);
    const [result, setResult] = useState<{ kind: 'done' | 'applyFailed' | 'compareFailed'; reason?: string } | null>(null);
    const lockDate = state?.coverage?.frozen_end || preview?.frozen_end || '—';
    const waiting = state?.corrections ?? 0;
    const changes = preview?.available ? preview.changes ?? [] : [];
    const needsAction = waiting > 0 || !!(preview?.available && preview.needs_review);
    useEffect(() => { onNeedsAction(!!(preview?.available && preview.needs_review)); }, [preview, onNeedsAction]);

    const compare = useCallback(async () => {
        setBusy(true); setResult(null); setConfirming(false);
        try { setPreview(await api.getTwrRereview()); }
        catch (e) { setResult({ kind: 'compareFailed', reason: (e as Error).message }); }
        finally { setBusy(false); }
    }, []);
    // Compare by itself when corrections wait, or when the server couldn't count them (the
    // read-only preview then says why, e.g. the workbook isn't uploaded).
    const autoCompare = state != null && state.corrections !== 0;
    useEffect(() => { if (autoCompare) void compare(); }, [autoCompare, waiting, compare]);

    async function apply() {
        setBusy(true); setResult(null);
        try { await api.applyTwrRereview(reviewer.trim(), evidence.trim()); setPreview(null); setResult({ kind: 'done' }); onChanged(); }
        catch (e) { setResult({ kind: 'applyFailed', reason: (e as Error).message }); }
        finally { setBusy(false); setConfirming(false); }
    }
    const cny = (value: number | null | undefined) => value == null ? '—' : money(value, 2);
    const cols: ColDef<TwrRereviewChange>[] = [
        { label: t('returnsInputs.locked.record'), render: c => <span title={c.flow_id} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {mono(c.source)}<Pill tone="primary">{t(`returnsInputs.locked.change.${c.change}`)}</Pill></span> },
        { label: t('returnsInputs.locked.date'), mono: true, nowrap: true, key: 'event_date' },
        { label: t('returnsInputs.locked.now'), mono: true, nowrap: true, align: 'right', color: 'var(--color-fg-3)', render: c => cny(c.before_cny) },
        { label: t('returnsInputs.locked.inFile'), mono: true, nowrap: true, align: 'right', color: 'var(--color-fg-1)', render: c => cny(c.after_cny) },
    ];
    const compareAgain = <ChipBtn icon="refresh" disabled={busy} onClick={() => void compare()}>{t('returnsInputs.locked.compareAgain')}</ChipBtn>;
    const pill = needsAction
        ? <Pill tone="warning">{changes.length || waiting ? t('returnsInputs.locked.waitingPill', { count: changes.length || waiting }) : t('returnsInputs.actionNeeded')}</Pill>
        : state?.corrections === 0 || (preview?.available && !preview.needs_review) ? <Pill tone="success">{t('returnsInputs.upToDate')}</Pill> : null;
    const filled = !!reviewer.trim() && !!evidence.trim();

    return <div style={ROW}>
        <RowHeading icon="lock_clock" title={t('returnsInputs.locked.title', { date: lockDate })}
            why={t('returnsInputs.locked.why')} right={<>{pill}{!needsAction && compareAgain}</>} />
        {preview && !preview.available
            ? <Notice tone="warning">{t(`returnsInputs.locked.unavailable.${preview.reason}`, { defaultValue: preview.reason })}</Notice>
            : <p className="uis-body" style={{ margin: 0 }}>
                {changes.length
                    ? t('returnsInputs.locked.summary', { count: changes.length, amount: cny(preview?.net_change_cny ?? 0) })
                    : needsAction && !preview ? t('returnsInputs.locked.comparing') : t('returnsInputs.locked.match')}
            </p>}
        {preview?.available && preview.needs_review && <>
            {changes.length > 0 && <div style={TABLE_BOX} data-testid="rereview-preview">
                <OpsTable cols={cols} rows={changes} density="dense" rowKey={c => c.flow_id} />
            </div>}
            {(preview.evidence_text_changes ?? 0) > 0 && <p style={MUTED_NOTE}><Icon name="notes" size={14} color="var(--color-fg-4)" />
                {t('returnsInputs.locked.textOnly', { count: preview.evidence_text_changes })}</p>}
            {preview.history_changed_since_review && <p style={MUTED_NOTE}><Icon name="history" size={14} color="var(--color-fg-4)" />
                {t('returnsInputs.locked.valuesChanged', { date: preview.frozen_end })}</p>}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                <div><FieldLabel htmlFor={ids.reviewer}>{t('returnsInputs.locked.reviewer')}</FieldLabel>
                    <FormInput id={ids.reviewer} maxLength={100} value={reviewer} onChange={setReviewer} /></div>
                <div><FieldLabel htmlFor={ids.evidence}>{t('returnsInputs.locked.evidence')}</FieldLabel>
                    <FormInput id={ids.evidence} maxLength={500} value={evidence} onChange={setEvidence} /></div>
            </div>
            <div style={ACTIONS}>
                <ActionBtn variant="primary" icon={busy ? 'progress_activity' : 'published_with_changes'} disabled={busy || !filled}
                    onClick={() => setConfirming(true)}>{t('returnsInputs.locked.apply')}</ActionBtn>
                {!filled && <span style={{ fontSize: 11, color: 'var(--color-fg-3)' }}>{t('returnsInputs.locked.fillBoth')}</span>}
                <span style={{ marginLeft: 'auto' }}>{compareAgain}</span>
            </div>
        </>}
        {result?.kind === 'done' && <Notice>{t('returnsInputs.locked.done', { date: lockDate })}</Notice>}
        {(result?.kind === 'applyFailed' || result?.kind === 'compareFailed') && <Notice tone="danger" detail={result.reason} action={compareAgain}>
            {t(result.kind === 'applyFailed' ? 'returnsInputs.locked.applyFailed' : 'returnsInputs.locked.compareFailed')}
        </Notice>}
        {confirming && preview?.available && <ModalShell title={t('returnsInputs.locked.apply')}
            subtitle={t('returnsInputs.locked.modalSub', { date: preview.frozen_end })} closeLabel={t('returnsInputs.cancel')}
            onClose={() => setConfirming(false)}
            footer={<>
                <ChipBtn onClick={() => setConfirming(false)}>{t('returnsInputs.cancel')}</ChipBtn>
                <ActionBtn variant="primary" icon={busy ? 'progress_activity' : 'published_with_changes'} disabled={busy} onClick={() => void apply()}>
                    {t('returnsInputs.locked.replace')}
                </ActionBtn>
            </>}>
            <p className="uis-body" style={{ margin: 0 }}>{t('returnsInputs.locked.confirm', { date: preview.frozen_end })}</p>
            <ul style={SUMMARY_LIST}>
                <li style={{ ...SUMMARY_ITEM, borderTop: 'none' }}>{t('returnsInputs.locked.confirmCount', { count: changes.length, amount: cny(preview.net_change_cny ?? 0) })}</li>
                <li style={SUMMARY_ITEM}>{t('returnsInputs.locked.confirmBy', { name: reviewer.trim(), reason: evidence.trim() })}</li>
                <li style={SUMMARY_ITEM}>{t('returnsInputs.locked.archived')}</li>
            </ul>
        </ModalShell>}
    </div>;
}
