The Huinsight mark and app icons, copied from the repository as delivered.

- `icon-mark.svg` — the mark (from `ux-command-center/src/assets/icon-mark.svg`). Outline and iris are `currentColor`, so shown through `<img>` they render black; facets fall back to gold #dd9a2e and the pupil to white. In product UI use the `BrandMark` component instead, which takes its colour from context.
- `mark-1024.png` — the mark at 1024px: ink-indigo outline and iris, gold facets, off-white pupil, on white. For docs and large placements.
- `app-icon-512.png`, `app-icon-192.png` — PWA icons (`manifest.webmanifest`, theme colour `color-primary`).
- `apple-touch-icon.png`, `favicon-48.png`, `favicon-32.png`, `favicon-16.png` — the simplified small-size glyph; use these, never a scaled-down mark, below 48px.
- `social-card.png` — the repository's social preview image.
