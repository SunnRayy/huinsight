import React from 'react';
import { Icon } from './Icon';

type NoticeTone = 'success' | 'danger' | 'warning' | 'info';

const TONES: Record<NoticeTone, { icon: string; bg: string; fg: string }> = {
  success: { icon: 'check_circle', bg: 'var(--fill-success-soft)', fg: 'var(--zone-green-fg)' },
  danger:  { icon: 'error',        bg: 'var(--fill-danger-soft)',  fg: 'var(--zone-red-fg)' },
  warning: { icon: 'warning',      bg: 'var(--fill-warning-soft)', fg: 'var(--zone-yellow-fg)' },
  info:    { icon: 'info',         bg: 'var(--fill-primary-soft)', fg: 'var(--color-primary)' },
};

interface NoticeProps {
  tone?: NoticeTone;
  children: React.ReactNode;
  /** Shown under the message in mono, verbatim (e.g. the server's reason). */
  detail?: React.ReactNode;
  action?: React.ReactNode;
}

/** An inline result line. Success announces politely (`status`), danger immediately (`alert`). */
export function Notice({ tone = 'success', children, detail, action }: NoticeProps) {
  const t = TONES[tone];
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} style={{
      display: 'flex', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap',
      padding: '10px 12px', borderRadius: 8, background: t.bg, color: t.fg, fontSize: 12,
    }}>
      <Icon name={t.icon} size={16} fill style={{ marginTop: 1 }} />
      <div style={{ flex: '1 1 200px', minWidth: 0 }}>
        <div>{children}</div>
        {detail && <div style={{ marginTop: 4, fontSize: 11, fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>{detail}</div>}
      </div>
      {action && <div style={{ marginLeft: 'auto' }}>{action}</div>}
    </div>
  );
}
