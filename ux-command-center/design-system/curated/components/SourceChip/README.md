# SourceChip

A data-source status chip: a 6px status dot, the source name in mono, an optional muted count. Also exports **SevDot**, the bare 6px severity dot.

- SourceChip `status`: `ok` (default, `color-success`), `warning` (`color-warning`), `error` (`color-danger`).
- SevDot `sev`: `high` → `color-danger`, `review` → `color-warning`, `info` → `color-primary`, anything else → `color-success`.

The dot never carries meaning alone — always pair it with the status word or a list label beside it.

**Consumer provides:** `name`, `status`, `count` / `sev`. Source: `components/operations/Indicators.tsx`.
