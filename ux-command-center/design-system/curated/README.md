Huinsight is a self-hosted personal finance and portfolio analytics app — dense, numeric, and calm. It is **Day-first** (light) with a **Night** theme, bilingual (English and Simplified Chinese), and built from cards of KPIs, tables and small trends.

## Content fundamentals

- **Plain, operational voice.** Labels say what the number is: "Net Worth", "Cash Buffer", "Last synced: 2h ago", "All portfolio values shown in CNY". No marketing adjectives, no emoji.
- **Title Case** for page titles, card titles and buttons ("Unified Portfolio", "Export AI Context", "Sync All"); **UPPERCASE** only through `uis-eyebrow`, table headers and Pills — never typed in caps in the source string.
- **Numbers carry their unit and sign.** Money in CNY with `¥` and K/M suffixes (`¥2.70M`, `+¥318.68K`); percentages signed (`+13.4%`, `−0.9%`); always in `font-mono` with tabular numerals.
- **Say when a value is degraded.** A fallback is labelled on screen (`USD/CNY 6.7205 FALLBACK`), an empty state says so ("No active flags", "No data") — never a blank.
- **Every control does something.** A button has a real handler or is `disabled` with a title explaining why. No decorative buttons.
- **Bilingual.** Copy goes through i18n; Chinese falls back through the CJK stack in `--font-sans` / `--font-mono`, so never set a face without it.

## Visual foundations

**Colour.** One brand colour: `color-primary` (#3b82f6) for primary actions, links, active nav and the brand-mark tile; `color-primary-hover` on hover. `brand-spark` gold belongs to the mark only. Status uses `color-success`, `color-warning`, `color-danger` as dots and fills; text on soft fills uses the matching `zone-*-fg` (`fill-success-soft` + `zone-green-fg`, `fill-warning-soft` + `zone-yellow-fg`, `fill-danger-soft` + `zone-red-fg`, `fill-neutral-soft` + `color-fg-3`). `color-investment` indigo marks investment data. Sentiment runs `zone-green` → `zone-light-green` → `zone-yellow` → `zone-orange` → `zone-red`. Charts use `chart-1` … `chart-5` in order.

**Surfaces.** Page on `color-bg`, content on `color-card`, raised rows on `color-surface`, sidebar on `color-sidebar`. Containers are separated by a 1px `color-border` plus `shadow-sm`, not by colour; row dividers use `color-border-soft`.

**Text.** `color-fg-1` headings and values, `color-fg-2` body and cells, `color-fg-3` secondary and eyebrows, `color-fg-4` muted labels and ticks (below 4.5:1 — non-essential text only), `color-fg-5` hairlines, never text. P&L text: `.uis-pos` / `.uis-neg`.

**Type.** Inter for UI (`font-sans`, also `font-display`), Roboto Mono for every number, id, cell, chip label and code (`font-mono`). Scale: `uis-h1` 24/700 page titles; `uis-h3` 14/700 section titles; `uis-base` 14 root; `uis-body` 12 rows; `uis-cell` 11 mono cells; `uis-eyebrow` 10/700 uppercase labels; `uis-num-kpi` 24/700 mono KPIs. The CSS classes `.uis-h1`, `.uis-body`, `.uis-eyebrow`, `.uis-num`, `.uis-num--kpi`, `.uis-cell` in `bundle.css` apply them.

**Spacing and shape.** Tailwind 4px scale: `space-5` (20px) card padding, `space-4` dense panels, `space-6` large cards, `space-8` page gutter. Radii: `radius-xl` (12px) cards and modals, `radius-lg` (8px) buttons, chips and nav, `radius-md` (6px) inputs, `radius-sm` (4px) pills. Shadows are quiet: `shadow-sm` on every card, `shadow-2xl` on modals, `shadow-primary-glow` on primary buttons only.

**Motion and states.** 120ms ease colour/background transitions only. Disabled = 50% opacity + `not-allowed`. Selected rows and active nav sit on `fill-primary-soft`. In Demo mode money values blur (`filter: blur(6px)`).

**Themes.** Day is the default; Night switches with `[data-theme="night"]` (the app toggles `html.dark` and stores the choice under `uis-theme`). Brand and status colours are identical in both; surfaces, text, soft fills and `zone-*-fg` change.

## Iconography

- **Material Symbols Outlined** through the `Icon` component (ligature names: `sync`, `trending_up`, `account_balance_wallet`), outline by default, `fill` for selected states, weight 400, optical size 24. Sizes: 13–14 in buttons and chips, 16 beside section titles, 24 in navigation. The app self-hosts the font (`@fontsource-variable/material-symbols-outlined`, FILL axis); without it icons render as their literal words.
- A few controls use **lucide-react** (e.g. the logout icon).
- **The brand mark** (Logos): the `BrandMark` component — white on a `color-primary` tile at 24px in the sidebar, 48px on login. Facets are `brand-spark`; the pupil is `brand-mark-hole`, which must match the surface underneath. Below 48px use the favicon glyphs, not a scaled-down mark.
- No emoji, no illustration.

## Components

`window.Huinsight` exposes the operations library: `Card`, `Section` / `SectionTitle`, `OpsKpi`, `OpsTable`, `Pill` / `StatusPill`, `ChipBtn` / `ActionBtn` / `IconBtn`, `SourceChip` / `SevDot`, `MiniLine`, `DriftGauge` / `DriftRow`, `Toolbar` / `SearchInput` / `OpsSelect`, `ModalShell` / `FieldLabel` / `FormInput` / `FormSelect`, `Icon`, and `BrandMark`. They style themselves inline from the tokens above, so load `tokens.css` and `bundle.css` first. Compose pages as rows of `OpsKpi` tiles, then `Card`s holding a `SectionTitle` and an `OpsTable` or `MiniLine`, with a `Toolbar` above tables.

## Not synced

- **Font files.** Inter (300–700), Roboto Mono (400, 500) and Material Symbols Outlined are npm dependencies (`@fontsource/*`), not committed to the repository, so no files were copied; `bundle.css` loads the same faces from Google Fonts.
- **Variables adapted:** `rgb(r g b / a)` values were written as the equivalent `rgba()`. The `html.dark` rules are mirrored on `[data-theme="night"]`. `ActionBtn` / `IconBtn` danger tints use `color-mix()` inline (kept in the component).
- **Components not built:** `PipelinePanel` (calls the live Operations API) and the `fmtCNY` / `fmtPct` formatters; page-level components outside `components/operations/` (dashboard, forecast, settings, AI advisor).
- **Route:** the components were compiled from the repository's own source (`ux-command-center/components/operations/*.tsx`, `components/BrandMark.tsx`) into one bundle on React 18; `react-i18next` is shimmed with the English `operations:status.*` labels.
