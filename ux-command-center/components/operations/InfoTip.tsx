import React, { useId, useLayoutEffect, useRef, useState } from 'react';
import { IconBtn } from './Buttons';

interface InfoTipProps {
  /** Accessible name of the trigger, e.g. "Why this is needed". */
  label: string;
  children: React.ReactNode;
}

/** An info button whose explanation opens on hover, keyboard focus and tap (a native
 *  `title` reaches neither touch nor keyboard users). Esc closes it. */
export function InfoTip({ label, children }: InfoTipProps) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hovered || focused || pinned;
  // Anchored at the button's left edge; near the right edge of a narrow window it would run
  // off-screen, so shift it left by the overflow (never past the window's left edge).
  const tipRef = useRef<HTMLSpanElement | null>(null);
  const [shift, setShift] = useState(0);
  useLayoutEffect(() => {
    if (!open || !tipRef.current) { setShift(0); return; }
    const r = tipRef.current.getBoundingClientRect();
    const over = r.right - (window.innerWidth - 8);
    setShift(over > 0 ? -Math.min(over, Math.max(r.left - 8, 0)) : 0);
  }, [open]);
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => { setFocused(false); setPinned(false); }}
      onKeyDown={(e) => { if (e.key === 'Escape') { setHovered(false); setFocused(false); setPinned(false); } }}
    >
      <IconBtn icon="info" ariaLabel={label} ariaExpanded={open} ariaDescribedBy={open ? id : undefined}
        onClick={() => setPinned((p) => !p)} />
      {open && (
        <span ref={tipRef} id={id} role="tooltip" style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: shift, zIndex: 30,
          width: 'max-content', maxWidth: 'min(420px, 80vw)', padding: '10px 12px',
          background: 'var(--color-surface)', border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-md)',
          fontSize: 12, lineHeight: 1.5, fontWeight: 400, color: 'var(--color-fg-2)',
          textTransform: 'none', letterSpacing: 0, whiteSpace: 'normal',
        }}>
          {children}
        </span>
      )}
    </span>
  );
}
