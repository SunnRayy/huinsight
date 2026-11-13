# Card

The default container: `color-card` ground, 1px `color-border`, `radius-xl` (12px), `shadow-sm`, 20px padding.

**Use it** for every dashboard tile and panel. Override `padding` with 16 (`space-4`) for dense side panels or 24 (`space-6`) for large ones; the CSS twin is `.uis-card` / `--tight` / `--lg`.

**Don't** stack cards inside cards or add coloured borders — status lives in Pills and SevDots inside the card.

**Consumer provides:** `children`, optional `padding`, `style`. Source: `components/operations/Card.tsx`.
