# ChipBtn

The product's buttons: compact 11px chips with an optional leading Icon. Also exports **ActionBtn** and **IconBtn**.

- **ChipBtn** — toolbar and header actions. Secondary: mono label, `color-card` ground, `color-border`, `color-fg-2`. `primary`: `color-primary` fill, white bold sans label, `shadow-primary-glow`.
- **ActionBtn** — row and dialog actions; `variant="primary"` as above, `danger` gives a tinted danger outline with `color-danger` text.
- **IconBtn** — 26px square icon-only button, `radius-md`; always pass `title` (it is the accessible name).

All use `radius-lg` (8px) and `padding: 6px 12px`. Use one primary per view.

**Every button needs a real `onClick` or `disabled`** — the project forbids decorative buttons (AGENTS.md Rule 19).

**Consumer provides:** `children`, `icon` (Material Symbols name), `onClick`, `primary` / `variant` / `danger`, `disabled`. Note ActionBtn and IconBtn's danger tints use `color-mix()`. Source: `components/operations/Buttons.tsx`.
