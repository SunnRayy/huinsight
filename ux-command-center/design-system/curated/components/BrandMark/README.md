# BrandMark

The Huinsight mark — 慧眼, "the discerning eye": an almond eye whose iris is cut into six even facets, reading as both an eye and a marquise-cut diamond.

**Use it** in the sidebar header (24px on a `color-primary` tile, `radius-lg`, `shadow-lg`) and on the login screen (48px). The detail budget is 48px and up; below that the facets blur — the favicons in Logos are a separate simplified glyph.

**Colour comes from context**, never baked in:
- outline and iris use `currentColor` — set the text colour (white on the `color-primary` tile, `color-fg-1` on a page);
- the facets use `brand-spark`;
- the pupil uses `brand-mark-hole`, which must equal the surface the mark sits on (it reads as a hole through the iris). It defaults to `color-primary`; override `--brand-mark-hole` when the mark sits anywhere else.

**Consumer provides:** a sized wrapper (the SVG fills it) and the text colour. Pass `title` when the mark stands alone so it gets `role="img"`; omit it beside the "Huinsight" wordmark (decorative, `aria-hidden`).

Props: `className`, `title`. Source: `ux-command-center/components/BrandMark.tsx`.
