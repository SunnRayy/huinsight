# CardHeader

The header band of a table card (`Card padding={0}`): `color-bg` ground with a `color-border` bottom rule, padding 14×20, an 18px `color-primary` icon, a 13px bold `color-fg-1` title, an optional 11px mono `color-fg-3` subline, and a right slot for a status Pill or actions. It wraps at narrow widths, so the right slot drops under the title.

Use it for a card whose body is rows or a table, the way the Data Sources cards are built. A card with ordinary padding uses `SectionTitle` instead.

**Consumer provides:** `icon`, `title`, `sub`, `right`. Source: `components/operations/CardHeader.tsx`.
