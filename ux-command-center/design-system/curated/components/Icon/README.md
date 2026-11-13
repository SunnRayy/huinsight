# Icon

A Material Symbols Outlined glyph, named by its ligature (`sync`, `trending_up`, `account_balance_wallet`).

**Use it** for every product icon; it is what ChipBtn, IconBtn, OpsKpi, Section and SearchInput render internally. Default size 18; the product uses 13–14 inside buttons and chips, 16 beside section titles, 24 in nav.

- `fill` switches to the filled variant (`.filled-icon`, FILL axis 1) — for selected or emphasised states only.
- `color` defaults to `inherit`; use `color-fg-3` beside headings and `color-fg-4` for decorative KPI icons.
- The glyph font must be loaded: `bundle.css` imports Material Symbols Outlined. Without the font every icon renders as its literal ligature word.

**Consumer provides:** `name` (any Material Symbols ligature). Source: `components/operations/Icon.tsx`.
