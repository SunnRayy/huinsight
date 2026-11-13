# OpsKpi

A KPI tile: uppercase eyebrow label, a large mono value (24px bold, 18px when `dense`), an optional mono sub-line, an optional corner icon.

**Use it** in rows of 3–4 at the top of operations and dashboard pages. Colour the value with `accent` only for signed P&L (`color-success` / `color-danger`); leave plain totals in `color-fg-1`. `subColor` defaults to `color-fg-4`.

**Consumer provides:** `label`, pre-formatted `value` (format money with the app's locale formatter — CNY with ¥, K/M suffixes), optional `sub`, `subColor`, `accent`, `icon`, `dense`. Source: `components/operations/OpsKpi.tsx`.
