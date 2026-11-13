# Design system producer

Rebuilds the files of the **Huinsight design system** (the Claude Design System artifact in `tokens.meta.json` → `artifact`) from this app's code, so the system never drifts from what ships.

```bash
cd ux-command-center
npm run ds:build        # = bun design-system/build.mjs
```

It needs [Bun](https://bun.sh) (it bundles the components with `Bun.build`) and nothing else: no install, no network.

## What it reads and writes

| From the code | Becomes |
| --- | --- |
| `src/styles/colors_and_type.css` — the `:root` and `[data-theme="night"]` variables | `tokens.json` (colours in Day and Night, spacing, radii, shadows, font sizes, tracking, font stacks) |
| the same file, everything after the token blocks | `components/bundle.css` (`html.dark` rules mirrored on `[data-theme="night"]`) |
| `components/operations/*.tsx`, `components/BrandMark.tsx` | `components/bundle.js` — one script assigning `window.Huinsight`, on the page's React 18 |
| `src/i18n/locales/en/operations.json` → `status` | the English labels `StatusPill` shows |
| logo files listed in `tokens.meta.json` → `logos` | `out/uploads/` with a sha256 each |

Hand-kept parts live here, because the code cannot say them:

- `tokens.meta.json` — a usage note per variable, the type scale, which components go in the bundle, logo sources.
- `curated/` — the brand book (`README.md`), each component's guideline and live preview, the cover, `index.d.ts`.

Output goes to `design-system/out/` (git-ignored): `out/project/…` at the artifact's own paths, and `out/publish.json` listing what to send.

## When it complains

The build exits non-zero and prints `ERROR` when something would break the system: a colour written in a form the system can't read (`color-mix()`, a named colour), a duplicate token name, a component card with no matching export, or a bundle that fails to compile.

It prints `warn` — and still succeeds — when the code and the hand-kept notes drift apart:

- a new CSS variable has no usage note → add one to `tokens.meta.json` → `usage`;
- a note names a variable the CSS dropped → delete the note;
- `components/operations/index.ts` exports something the system doesn't include → add it to `bundle.exports` (plus a `curated/components/<Name>/` card), or list it under `notBundled` with the reason.

## Publishing

Building changes nothing online. To update the artifact, ask Claude (Claude Code or the Claude app, with the Artifact tool):

> Publish `ux-command-center/design-system/out` to the Huinsight design system, as `out/publish.json` describes.

That sends every file in `publish.json` → `files` in one publish to the artifact, with `root` = `out/`. It does not resend `project/design-system.json` (the page owns it) or `components/lib/` (React 18, already there). Re-upload a logo only when its sha256 changed.

Editing a token on the artifact's page is fine for trying things, but the next publish from here replaces it: make the lasting change in `colors_and_type.css` (or `tokens.meta.json` for notes) and rebuild.

## Adding a component

1. Export it from `components/operations/index.ts` as usual.
2. Add it to `tokens.meta.json` → `bundle.exports`.
3. Add `curated/components/<Name>/README.md` (first sentence = summary) and `preview.html` (line 1 `<!-- @dsCard group="…" height=N -->`, then a small document mounting `window.Huinsight.<Name>`).
4. Add its props to `curated/index.d.ts`.
5. `npm run ds:build`.
