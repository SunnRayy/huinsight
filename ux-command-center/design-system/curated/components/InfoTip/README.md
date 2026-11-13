# InfoTip

An `info` IconBtn whose explanation opens in a popover on hover, keyboard focus and tap. Esc closes it. The popover sits on `color-surface` with a 1px `color-border`, `radius-lg` and `shadow-md`; its text is 12px `color-fg-2`, at most 420px wide. It is `role="tooltip"`, and the button points to it with `aria-describedby`.

Use it to keep a long "why" next to a title instead of a paragraph in the card. A native `title` tooltip reaches neither touch nor keyboard users.

**Consumer provides:** `label` (the button's accessible name, e.g. "Why this is needed") and `children` (the explanation). Source: `components/operations/InfoTip.tsx`.
