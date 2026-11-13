# ModalShell

The dialog frame: a blurred 45% black overlay (click to close), a 480px `color-card` panel with `radius-xl` and `shadow-2xl`, a header with a 14px bold title, an optional mono subtitle and a close icon, a 16×20 body, and an optional right-aligned footer on `color-border-soft`. Also exports the form parts **FieldLabel** (11px uppercase `color-fg-3`), **FormInput** (`color-bg` ground, `radius-md`, `mono` option), **FormTextarea** (FormInput, multi-line, `rows` default 3) and **FormSelect**. Pair a label with its field through `FieldLabel htmlFor` and the field's `id`. The panel is a `role="dialog"` named by its title; `closeLabel` names the × button.

Footer order: secondary ActionBtn first, the one primary last.

**Consumer provides:** `title`, `subtitle`, `onClose`, `children`, `footer`; render it only while open (it is `position: fixed`, z-index 100). Inputs are controlled (`value`, `onChange(value)`). Source: `components/operations/ModalShell.tsx`.
