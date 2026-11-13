import React, { useId } from 'react';
import { Icon } from './Icon';

interface ModalShellProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Accessible name of the × button (default "Close"). */
  closeLabel?: string;
}

export function ModalShell({ title, subtitle, onClose, children, footer, closeLabel = 'Close' }: ModalShellProps) {
  const titleId = useId();
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(4px)',
        display: 'grid', placeItems: 'center',
      }}
      onClick={onClose}
    >
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(e) => e.stopPropagation()} style={{
        width: 480, maxWidth: '90vw',
        background: 'var(--color-card)',
        border: '1px solid var(--color-border)',
        borderRadius: 12, boxShadow: 'var(--shadow-2xl)',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--color-border-soft)',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        }}>
          <div>
            <h3 id={titleId} style={{ margin: 0, fontSize: 14, fontWeight: 700, color: 'var(--color-fg-1)' }}>{title}</h3>
            {subtitle && <div style={{ fontSize: 11, color: 'var(--color-fg-4)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>{subtitle}</div>}
          </div>
          <button type="button" aria-label={closeLabel} onClick={onClose} style={{
            border: 'none', background: 'transparent',
            color: 'var(--color-fg-4)', cursor: 'pointer',
            display: 'grid', placeItems: 'center',
          }}>
            <Icon name="close" size={18} />
          </button>
        </div>
        <div style={{ padding: '16px 20px' }}>{children}</div>
        {footer && (
          <div style={{
            padding: '12px 20px', borderTop: '1px solid var(--color-border-soft)',
            display: 'flex', justifyContent: 'flex-end', gap: 8,
            background: 'var(--color-border-soft)',
          }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function FieldLabel({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} style={{
      display: 'block', fontSize: 11, fontWeight: 600,
      color: 'var(--color-fg-3)', marginBottom: 6,
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {children}
    </label>
  );
}

interface FormInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
  /** Pair with `<FieldLabel htmlFor={id}>`. */
  id?: string;
  maxLength?: number;
}

const FIELD_STYLE: React.CSSProperties = {
  width: '100%', padding: '8px 10px',
  background: 'var(--color-bg)',
  border: '1px solid var(--color-border)',
  borderRadius: 6, fontSize: 12,
  color: 'var(--color-fg-1)', outline: 'none',
};

export function FormInput({ value, onChange, placeholder, type = 'text', mono, id, maxLength }: FormInputProps) {
  return (
    <input
      id={id}
      maxLength={maxLength}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      type={type}
      style={{ ...FIELD_STYLE, fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)' }}
    />
  );
}

interface FormTextareaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  id?: string;
  maxLength?: number;
}

/** FormInput, multi-line. */
export function FormTextarea({ value, onChange, placeholder, rows = 3, id, maxLength }: FormTextareaProps) {
  return (
    <textarea
      id={id}
      rows={rows}
      maxLength={maxLength}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      style={{ ...FIELD_STYLE, fontFamily: 'var(--font-sans)', lineHeight: 1.5, resize: 'vertical', display: 'block' }}
    />
  );
}

interface FormSelectOption { value: string; label: string }

interface FormSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: FormSelectOption[];
}

const DROPDOWN_SVG = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='%2394a3b8'><path d='M7 10l5 5 5-5z'/></svg>")`;

export function FormSelect({ value, onChange, options }: FormSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: '100%', padding: '8px 28px 8px 10px',
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        borderRadius: 6, fontSize: 12, color: 'var(--color-fg-1)',
        fontFamily: 'var(--font-sans)',
        cursor: 'pointer', outline: 'none',
        appearance: 'none',
        backgroundImage: DROPDOWN_SVG,
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 8px center',
      }}
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
