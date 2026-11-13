# OpsTable

The data table: uppercase 10px `color-fg-4` headers over a `color-border` rule, 12px rows divided by `color-border-soft`, the selected row on `fill-primary-soft`.

**Columns** (`ColDef`): `label`, `key` or `render(row)`, `align`, `mono` (Roboto Mono — use for ids, amounts, dates), `size`, `color`, `nowrap`, `width`, `padX` (default 14). Right-align numbers.

**Density:** `comfy` (12px row padding, default), `dense` (10px), `compact` (8px).

Put it in a `Card` with `padding={0}` so rows run edge to edge.

**Consumer provides:** `cols`, `rows`, optional `rowKey`, `selectedKey`, `onRowClick` (rows get a pointer cursor only when it is set). Source: `components/operations/OpsTable.tsx`.
