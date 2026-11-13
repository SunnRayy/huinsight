import React from 'react';
import { Icon } from './Icon';

interface CardHeaderProps {
  icon?: string;
  title: string;
  sub?: React.ReactNode;
  right?: React.ReactNode;
}

/** The header band of a table card (`<Card padding={0}>`): icon, title, optional mono
 *  subline, right slot. Wraps at narrow widths. Matches the Data Sources table headers. */
export function CardHeader({ icon, title, sub, right }: CardHeaderProps) {
  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between',
      gap: '8px 12px', padding: '14px 20px',
      borderBottom: '1px solid var(--color-border)', background: 'var(--color-bg)',
      borderRadius: '11px 11px 0 0', // Card radius 12 minus its 1px border
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        {icon && <Icon name={icon} size={18} color="var(--color-primary)" />}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 13, fontWeight: 700, lineHeight: 1.3, color: 'var(--color-fg-1)' }}>{title}</h2>
          {sub && <p style={{ margin: '2px 0 0', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--color-fg-3)' }}>{sub}</p>}
        </div>
      </div>
      {right && <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>{right}</div>}
    </div>
  );
}
