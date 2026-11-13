# Toolbar

A filter bar above tables: `color-border-soft` ground, 1px `color-border`, 10px radius, 14px padding, wrapping 8px gaps. Also exports **SearchInput** (search icon + borderless input, 220px default) and **OpsSelect** (native select with a mono label and a chevron).

Put filters left and actions (ChipBtn) right with `marginLeft: auto`.

**Consumer provides:** `children`; for SearchInput and OpsSelect a controlled `value` + `onChange(value)`, `placeholder` / `options` (strings or `{value,label}`), `label`, `width`. Source: `components/operations/Toolbar.tsx`.
