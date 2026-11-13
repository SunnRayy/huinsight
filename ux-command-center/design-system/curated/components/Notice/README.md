# Notice

An inline result line: a filled tone icon, the message, an optional mono `detail` underneath and an optional action on the right. Radius 8, padding 10×12, soft tone fill with its matching text: `success` (`check_circle`, `fill-success-soft` / `zone-green-fg`), `danger` (`error`, `fill-danger-soft` / `zone-red-fg`), `warning` (`warning`, `fill-warning-soft` / `zone-yellow-fg`), `info` (`info`, `fill-primary-soft` / `color-primary`).

Success, warning and info are `role="status"`; danger is `role="alert"`. Put a server's reason in `detail` verbatim, untranslated, and the way out (a ChipBtn) in `action`. Keep the notice until the next refresh or action.

**Consumer provides:** `tone`, `children`, `detail`, `action`. Source: `components/operations/Notice.tsx`.
