/**
 * Dashboard Charts — SVG Sparkline, Donut, and DriftBar primitives
 * Following Huinsight Design System: Inter + Roboto Mono, slate palette, semantic colors
 */
import React from 'react';

/* ---------- Sparkline ---------- */
export const Sparkline: React.FC<{
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
}> = ({ data, width = 120, height = 36, color = 'var(--color-primary)', fill = true }) => {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => [i * stepX, height - ((v - min) / span) * (height - 4) - 2]);
  const d = points.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ');
  const fillD = `${d} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1];
  const gradId = `spark-${Math.random().toString(36).slice(2, 8)}`;
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {fill && (
        <>
          <defs>
            <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.18" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={fillD} fill={`url(#${gradId})`} />
        </>
      )}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2.5" fill={color} />
    </svg>
  );
};

/* ---------- Donut ---------- */
export const Donut: React.FC<{
  data: Array<{ cur: number; color: string; name: string }>;
  size?: number;
  thickness?: number;
}> = ({ data, size = 180, thickness = 22 }) => {
  const total = data.reduce((s, d) => s + d.cur, 0);
  if (total === 0) return null;
  const r = size / 2 - 2;
  const inner = r - thickness;
  const cx = size / 2, cy = size / 2;
  let acc = 0;
  const slices = data.map((d) => {
    const a0 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += d.cur;
    const a1 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const xi1 = cx + inner * Math.cos(a1), yi1 = cy + inner * Math.sin(a1);
    const xi0 = cx + inner * Math.cos(a0), yi0 = cy + inner * Math.sin(a0);
    const path = [
      `M${x0},${y0}`,
      `A${r},${r} 0 ${large} 1 ${x1},${y1}`,
      `L${xi1},${yi1}`,
      `A${inner},${inner} 0 ${large} 0 ${xi0},${yi0}`,
      'Z',
    ].join(' ');
    return { path, color: d.color, name: d.name };
  });
  return (
    <svg width={size} height={size} style={{ display: 'block' }}>
      {slices.map((s, i) => (
        <path key={i} d={s.path} fill={s.color} />
      ))}
    </svg>
  );
};

/* ---------- Drift bar ---------- */
export const DriftBar: React.FC<{
  pct: number;
  target: number;
  color: string;
}> = ({ pct, target, color }) => {
  const max = Math.max(pct, target) * 1.15 + 2;
  const w = 120;
  const cur = (pct / max) * w;
  const tgt = (target / max) * w;
  return (
    <svg width={w} height={14} style={{ display: 'block' }}>
      <rect x="0" y="6" width={w} height="2" fill="var(--color-border-soft)" rx="1" />
      <rect x="0" y="5" width={cur} height="4" fill={color} rx="1" />
      <line x1={tgt} x2={tgt} y1="2" y2="12" stroke="var(--color-fg-2)" strokeWidth="1.5" />
    </svg>
  );
};

/* ---------- Area Chart ---------- */

/** Round step (1, 2, 2.5 or 5 × 10^n) giving about `target` intervals over `span`. */
export function niceStep(span: number, target = 4): number {
  if (!(span > 0)) return 1;
  const raw = span / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return nice * mag;
}

export const AreaChart: React.FC<{
  data: Array<{ m: string; v: number }>;
  /** Actual rendered width in px; the chart draws 1:1 so text is never stretched. */
  width?: number;
  height?: number;
  color?: string;
  /** Formats a y-axis value (e.g. ¥3M / ¥300万). */
  formatY?: (v: number) => string;
}> = ({ data, width = 780, height = 320, color = '#135bec', formatY }) => {
  if (!data || data.length < 2 || width < 120) return null;
  const fmtY = formatY ?? ((v: number) => `¥${(v / 1_000_000).toFixed(1)}M`);
  const padL = 64, padR = 14, padT = 12, padB = 26;
  const w = width - padL - padR;
  const h = height - padT - padB;
  const min = Math.min(...data.map((d) => d.v));
  const max = Math.max(...data.map((d) => d.v));
  const step = niceStep(max - Math.max(0, min - (max - min) * 0.1));
  const yMin = Math.max(0, Math.floor((min - (max - min) * 0.1) / step) * step);
  const yMax = Math.ceil((max + (max - min) * 0.04) / step) * step;
  const span = yMax - yMin || 1;
  const xAt = (i: number) => padL + (i / (data.length - 1)) * w;
  const yAt = (v: number) => padT + h - ((v - yMin) / span) * h;
  const linePts = data.map((d, i) => [xAt(i), yAt(d.v)]);
  const lineD = linePts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ');
  const fillD = `${lineD} L${padL + w},${padT + h} L${padL},${padT + h} Z`;
  const yTickValues: number[] = [];
  for (let v = yMin; v <= yMax + step / 2; v += step) yTickValues.push(v);
  // Month labels are "YYYY-MM-DD"; show "YYYY-MM" and space them by the real width.
  const maxXTicks = Math.max(2, Math.floor(w / 90));
  const xTickStride = Math.max(1, Math.ceil((data.length - 1) / (maxXTicks - 1)));
  const last = data.length - 1;
  const xTicks = data
    .map((d, i) => ({ i, m: d.m.length >= 7 ? d.m.slice(0, 7) : d.m }))
    // every stride-th month, plus the last one; drop a stride tick that would crowd the last
    .filter((d) => d.i === last || (d.i % xTickStride === 0 && last - d.i >= xTickStride / 2));
  const gradId = `area-grad-${Math.random().toString(36).slice(2, 8)}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.30" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {yTickValues.map((v, i) => (
        <g key={i}>
          <line x1={padL} x2={padL + w} y1={yAt(v)} y2={yAt(v)} stroke="var(--color-border-soft)" strokeDasharray={i === 0 ? '0' : '2 3'} />
          <text className="money-value" x={padL - 8} y={yAt(v)} textAnchor="end" dominantBaseline="middle" fontSize="11" fontFamily="var(--font-mono)" fill="var(--color-fg-3)">
            {fmtY(v)}
          </text>
        </g>
      ))}
      <path d={fillD} fill={`url(#${gradId})`} />
      <path d={lineD} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {xTicks.map((t) => (
        <text key={t.i} x={xAt(t.i)} y={padT + h + 18} textAnchor={t.i === data.length - 1 ? 'end' : t.i === 0 ? 'start' : 'middle'} fontSize="11" fontFamily="var(--font-mono)" fill="var(--color-fg-3)">
          {t.m}
        </text>
      ))}
      <circle cx={linePts[linePts.length - 1][0]} cy={linePts[linePts.length - 1][1]} r="4" fill={color} />
      <circle cx={linePts[linePts.length - 1][0]} cy={linePts[linePts.length - 1][1]} r="8" fill={color} opacity="0.18" />
    </svg>
  );
};
