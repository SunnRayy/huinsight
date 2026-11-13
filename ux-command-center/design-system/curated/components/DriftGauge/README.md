# DriftGauge

A centred allocation-drift bar: a shaded tolerance band, a centre tick, and a bar from centre to the drift value — `color-success` under half the tolerance, `color-warning` up to it, `color-danger` at or beyond it. Also exports **DriftRow**, a current-vs-target bar (fill to current, a `color-fg-2` tick at target).

Always print the signed drift percentage beside the gauge; the colour alone is not the message.

**Consumer provides:** `drift` (percentage points, signed), `tolerance` (default 5) / `current`, `target`, `color` (default `color-primary`). Width comes from the container. Source: `components/operations/DriftGauge.tsx`.
