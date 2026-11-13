# MiniLine

A compact SVG trend line: `chart-1` stroke over a fading `chart-1` area, an optional dashed `color-fg-3` target line, mono month ticks on every other point, and a dot on the last value.

**Use it** for small trends inside cards (480×140 default). For full charts the app uses Recharts with the same `chart-1`…`chart-5` series order.

**Consumer provides:** `data` (≥2 points; `m` is the tick label), `accessor` (default `v`), optional `targetAccessor`, `width`, `height`. Returns nothing for fewer than two points. Source: `components/operations/MiniLine.tsx`.
