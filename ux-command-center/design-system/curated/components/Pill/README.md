# Pill

A small uppercase status label: 10px bold, 0.04em tracking, `radius-sm`, soft tone fill with its matching dark text.

**Tones:** `neutral` (`fill-neutral-soft` / `color-fg-3`), `primary` (`fill-primary-soft` / `color-primary`), `success` (`fill-success-soft` / `zone-green-fg`), `warning` (`fill-warning-soft` / `zone-yellow-fg`), `danger` (`fill-danger-soft` / `zone-red-fg`).

**StatusPill** maps a status string to tone and a translated label: `ok`, `healthy`, `low` → success; `warning`, `high` → danger; `review` → warning; `info` → primary; `missing` → neutral. In the app the label comes from react-i18next (`operations:status.*`); this bundle shims it with the English labels. Note the source maps `warning` to the danger tone — use `review` for amber.

**Consumer provides:** `children` (keep to one or two words), `tone` or `status`. Source: `components/operations/Pill.tsx`.
