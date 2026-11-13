#!/usr/bin/env bun
// Rebuilds the Huinsight design system's files from this app's code.
//
//   bun design-system/build.mjs          (from ux-command-center/)
//
// Reads   src/styles/colors_and_type.css     → tokens.json, components/bundle.css
//         components/operations/*.tsx         → components/bundle.js (window.Huinsight)
//         design-system/tokens.meta.json      → usage notes, type scale, bundle exports
//         design-system/curated/**            → README, component guidelines and previews
// Writes  design-system/out/project/**        → the system's files, at their artifact paths
//         design-system/out/uploads/**        → logo files (re-upload only when changed)
//         design-system/out/publish.json      → the files to send, and where
//
// Nothing here talks to the network or to the artifact. Publishing is a separate step (README.md).

import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, readdirSync, statSync, copyFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { execSync } from 'node:child_process';

const DS = dirname(import.meta.path);
const APP = resolve(DS, '..');
const OUT = join(DS, 'out');
const PROJECT = join(OUT, 'project');
const meta = JSON.parse(readFileSync(join(DS, 'tokens.meta.json'), 'utf8'));

const errors = [];
const warnings = [];
const err = (m) => errors.push(m);
const warn = (m) => warnings.push(m);

rmSync(OUT, { recursive: true, force: true });
mkdirSync(PROJECT, { recursive: true });

const write = (rel, text) => {
  const p = join(PROJECT, rel);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, text);
};

// ---------------------------------------------------------------- stylesheet
const cssPath = join(APP, meta.source.css);
const cssRaw = readFileSync(cssPath, 'utf8');

/** Parse `--name: value;` declarations of the first block whose selector list matches. */
function readBlock(selectorTest) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(cssRaw))) {
    const selectors = m[1].replace(/\/\*[\s\S]*?\*\//g, '').split(',').map((s) => s.trim());
    if (!selectors.some(selectorTest)) continue;
    const vars = new Map();
    const body = m[2];
    const declRe = /--([A-Za-z0-9_-]+)\s*:\s*([^;]+);([^\n]*)/g;
    let d;
    while ((d = declRe.exec(body))) {
      const value = d[2].replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ').trim();
      const trailing = /\/\*\s*([\s\S]*?)\s*\*\//.exec(d[3]);
      vars.set(d[1], { value, comment: trailing ? trailing[1] : '' });
    }
    return { vars, end: m.index + m[0].length };
  }
  return null;
}

const [dayTheme, nightTheme] = meta.themes;
const day = readBlock((s) => s === dayTheme.selector);
const night = readBlock((s) => s === nightTheme.selector);
if (!day) err(`No ${dayTheme.selector} block in ${meta.source.css}`);
if (!night) err(`No ${nightTheme.selector} block in ${meta.source.css}`);

const rgbSlash = (v) =>
  v.replace(/rgba?\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\/\s*([\d.]+%?)\s*\)/g, (_, r, g, b, a) =>
    `rgba(${r}, ${g}, ${b}, ${a.endsWith('%') ? parseFloat(a) / 100 : parseFloat(a)})`);

function colorValue(name, v) {
  const alias = /^var\(--([A-Za-z0-9_-]+)\)$/.exec(v);
  if (alias) return `{${alias[1]}}`;
  if (/^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v)) return v.toLowerCase();
  const c = rgbSlash(v);
  if (/^(rgba?|hsla?|oklch|oklab|lab|lch)\([0-9.,%\s/+-]+\)$/.test(c)) return c;
  err(`--${name}: "${v}" is not a colour value the design system can read (no var(), color-mix() or named colours).`);
  return null;
}

const families = { color: [], spacing: [], radius: [], shadow: [], fontSize: [], tracking: [] };
const typeFamilies = {};
const familyOf = (n) =>
  /^(color|brand|fill|zone|chart|scrollbar)-/.test(n) ? 'color'
  : /^space-/.test(n) ? 'spacing'
  : /^radius-/.test(n) ? 'radius'
  : /^shadow-/.test(n) ? 'shadow'
  : /^fs-/.test(n) ? 'fontSize'
  : /^tracking-/.test(n) ? 'tracking'
  : /^font-/.test(n) ? 'font'
  : null;

const usageFor = (name, comment) => {
  const u = meta.usage[name];
  if (u) return u;
  warn(`--${name} has no usage note in tokens.meta.json${comment ? ` (using the stylesheet comment "${comment}")` : ''}.`);
  return comment || '';
};

if (day) {
  for (const [name, { value, comment }] of day.vars) {
    if (meta.skip.includes(name)) continue;
    const fam = familyOf(name);
    if (!fam) { warn(`--${name}: no family for this prefix; left out.`); continue; }
    if (fam === 'font') {
      const key = meta.familyKeys[name];
      if (!key) { warn(`--${name}: not mapped in familyKeys; left out.`); continue; }
      let stack = value;
      const ref = /^var\(--([A-Za-z0-9_-]+)\)$/.exec(stack);
      if (ref) stack = day.vars.get(ref[1])?.value ?? '';
      stack = stack.replace(/'/g, '"').replace(/\s+/g, ' ').trim();
      if (/[;{}<>\\()]/.test(stack)) err(`--${name}: font stack contains characters the design system rejects.`);
      typeFamilies[key] = stack;
      continue;
    }
    if (fam === 'color') {
      const d = colorValue(name, value);
      const nv = night?.vars.get(name);
      const n = nv ? colorValue(name, nv.value) : null;
      if (!d) continue;
      families.color.push({ name, value: n && n !== d ? { [dayTheme.id]: d, [nightTheme.id]: n } : { [dayTheme.id]: d }, usage: usageFor(name, comment) });
      continue;
    }
    const v = fam === 'shadow' ? rgbSlash(value) : value;
    if (/var\(|calc\(|color-mix\(/.test(v)) { warn(`--${name}: "${v}" references another value; left out.`); continue; }
    families[fam].push({ name, value: v, usage: usageFor(name, comment) });
  }
  if (night) for (const name of night.vars.keys()) if (!day.vars.has(name)) warn(`--${name} is set only for ${nightTheme.name}; left out.`);
  for (const name of Object.keys(meta.usage)) if (!day.vars.has(name)) warn(`tokens.meta.json has a note for --${name}, which the stylesheet no longer defines.`);
}

const fsValue = (ref) => {
  const m = /^\{([A-Za-z0-9_-]+)\}$/.exec(ref);
  if (!m) return ref;
  const v = day?.vars.get(m[1])?.value;
  if (!v) err(`Type style refers to {${m[1]}}, which the stylesheet does not define.`);
  return v;
};
const typeGroups = meta.typeGroups.map((g) => ({
  ...g,
  styles: g.styles.map((s) => ({ ...s, fontSize: fsValue(s.fontSize) })),
}));

const nameRe = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const seen = new Set();
for (const fam of Object.values(families)) for (const t of fam) {
  if (!nameRe.test(t.name)) err(`Token name "${t.name}" is not allowed.`);
  if (seen.has(t.name)) err(`Token name "${t.name}" is used twice.`);
  seen.add(t.name);
}

let sha = 'unknown';
try { sha = execSync('git rev-parse --short HEAD', { cwd: APP }).toString().trim(); } catch {}
const today = new Date().toISOString().slice(0, 10);

const tokens = {
  name: meta.name,
  version: 1,
  color: { themes: meta.themes.map(({ id, name }) => ({ id, name })), tokens: families.color },
  type: { fonts: [], families: typeFamilies, groups: typeGroups },
  spacing: { tokens: families.spacing },
  radius: { tokens: families.radius },
  shadow: { tokens: families.shadow },
  fontSize: { tokens: families.fontSize },
  tracking: { tokens: families.tracking },
  meta: {
    source: 'github', repo: meta.source.repo, ref: `HEAD@${sha}`, package: meta.source.package,
    paths: { tokens: [meta.source.css] }, producer: 'ux-command-center/design-system/build.mjs', synced: today,
  },
};
write('tokens.json', JSON.stringify(tokens, null, 1) + '\n');

// ---------------------------------------------------------------- bundle.css
if (night) {
  let rest = cssRaw.slice(night.end);
  rest = rest.replace(/^([ \t]*)html\.dark ([^,{\n]+?)(\s*\{)/gm, (_, ind, sel, brace) => `${ind}html.dark ${sel}, [data-theme="night"] ${sel}${brace}`);
  const header = `/* ${meta.name} — component stylesheet, generated from ${meta.source.css} by design-system/build.mjs. Tokens live in tokens.json.
   The app self-hosts Inter, Roboto Mono and Material Symbols; here they load from Google Fonts. */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Roboto+Mono:wght@400;500&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block');
`;
  const css = header + rest.trimStart();
  if (/<\/style/i.test(css)) err('bundle.css contains "</style".');
  write('components/bundle.css', css);
}

// ---------------------------------------------------------------- bundle.js
const curatedComponents = join(DS, 'curated', 'components');
const exported = meta.bundle.exports.flatMap((e) => e.names);
const cardOrder = (n) => (exported.indexOf(n) + 1) || Infinity;
const cards = readdirSync(curatedComponents).filter((n) => n !== 'Cover' && statSync(join(curatedComponents, n)).isDirectory())
  .sort((a, b) => cardOrder(a) - cardOrder(b) || a.localeCompare(b));
for (const c of cards) if (!exported.includes(c)) err(`curated/components/${c} has no matching export in tokens.meta.json bundle.exports.`);

const kitIndex = join(APP, meta.bundle.kitIndex);
if (existsSync(kitIndex)) {
  const src = readFileSync(kitIndex, 'utf8');
  const names = [...src.matchAll(/export\s*\{([^}]*)\}/g)].flatMap((m) => m[1].split(',').map((s) => s.trim().split(/\s+as\s+/).pop()).filter(Boolean));
  for (const n of names) if (!/^type\s/.test(n) && !exported.includes(n) && !(n in meta.bundle.notBundled)) warn(`${meta.bundle.kitIndex} exports ${n}, which the design system does not include yet.`);
}

const locale = existsSync(join(APP, meta.source.locales)) ? JSON.parse(readFileSync(join(APP, meta.source.locales), 'utf8')) : {};
const statusLabels = Object.fromEntries(Object.entries(locale.status ?? {}).map(([k, v]) => [`status.${k}`, v]));

const tmp = join(OUT, '.tmp');
mkdirSync(tmp, { recursive: true });
const entry = join(tmp, 'entry.ts');
writeFileSync(entry,
  meta.bundle.exports.map((e) => `export { ${e.names.join(', ')} } from ${JSON.stringify(join(APP, e.from))};`).join('\n') + '\n');
const main = join(tmp, 'main.ts');
writeFileSync(main, `import * as NS from './entry';\n(window as any).${meta.bundle.namespace} = { ...NS };\n`);

const shims = {
  react: 'module.exports = window.React;',
  'react-dom': 'module.exports = window.ReactDOM;',
  'react/jsx-runtime': `const R = window.React;
function jsx(type, props, key) { const p = Object.assign({}, props); if (key !== undefined) p.key = key; return R.createElement(type, p); }
module.exports = { jsx, jsxs: jsx, jsxDEV: jsx, Fragment: R.Fragment };`,
  'react-i18next': `const L = ${JSON.stringify(statusLabels)};
module.exports = { useTranslation: () => ({ t: (k) => L[k] ?? k, i18n: { language: 'en' } }) };`,
};
shims['react/jsx-dev-runtime'] = shims['react/jsx-runtime'];

const built = await Bun.build({
  entrypoints: [main], format: 'iife', minify: true, target: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{
    name: 'globals',
    setup(b) {
      b.onResolve({ filter: /^(react|react-dom|react\/jsx-runtime|react\/jsx-dev-runtime|react-i18next)$/ }, (a) => ({ path: a.path, namespace: 'g' }));
      b.onLoad({ filter: /.*/, namespace: 'g' }, (a) => ({ contents: shims[a.path], loader: 'js' }));
    },
  }],
});
if (!built.success) {
  err('bundle.js failed to build:\n' + built.logs.map(String).join('\n'));
} else {
  const code = await built.outputs[0].text();
  if (/<\/script|<!--/i.test(code)) err('bundle.js contains "</script" or "<!--".');
  const header = `/* @ds-bundle: ${JSON.stringify({ format: 4, namespace: meta.bundle.namespace, components: cards.map((name) => ({ name })) })} */`;
  write('components/bundle.js', header + '\n' + code);
}
rmSync(tmp, { recursive: true, force: true });

// ---------------------------------------------------------------- curated docs
function copyTree(from, to) {
  for (const n of readdirSync(from)) {
    const p = join(from, n);
    if (statSync(p).isDirectory()) copyTree(p, join(to, n));
    else write(join(to, n), readFileSync(p, 'utf8'));
  }
}
const curated = join(DS, 'curated');
write('README.md', readFileSync(join(curated, 'README.md'), 'utf8'));
copyTree(join(curated, 'components'), 'components');
copyTree(join(curated, 'assets'), 'assets');
write('components/index.d.ts', readFileSync(join(curated, 'index.d.ts'), 'utf8'));

// ---------------------------------------------------------------- logos
const uploads = {};
mkdirSync(join(OUT, 'uploads'), { recursive: true });
for (const [name, src] of Object.entries(meta.logos)) {
  const p = join(APP, src);
  if (!existsSync(p)) { warn(`Logo ${name}: ${src} not found.`); continue; }
  copyFileSync(p, join(OUT, 'uploads', name));
  uploads[name] = { file: `uploads/${name}`, sha256: createHash('sha256').update(readFileSync(p)).digest('hex') };
}

// ---------------------------------------------------------------- publish plan
const listFiles = (dir) => readdirSync(dir).flatMap((n) => {
  const p = join(dir, n);
  return statSync(p).isDirectory() ? listFiles(p) : [p];
});
const files = Object.fromEntries(listFiles(PROJECT).map((p) => {
  const rel = relative(OUT, p).split('\\').join('/');
  return [rel, rel.endsWith('.d.ts') ? { from: rel, contentType: 'text/plain' } : rel];
}));
writeFileSync(join(OUT, 'publish.json'), JSON.stringify({
  url: meta.artifact,
  root: OUT,
  ref: sha,
  files,
  uploads,
  note: 'Send `files` in one Artifact publish to `url` with `root`. Do not send project/design-system.json, components/lib/ or uploads unless they changed.',
}, null, 2) + '\n');

// ---------------------------------------------------------------- report
const count = Object.keys(files).length;
console.log(`${meta.name} design system @ ${sha}: ${families.color.length} colours, ${typeGroups.reduce((n, g) => n + g.styles.length, 0)} text styles, ${families.spacing.length} spacing, ${families.radius.length} radii, ${families.shadow.length} shadows, ${cards.length} components → ${count} files in ${relative(APP, OUT)}/`);
for (const w of warnings) console.log(`  warn  ${w}`);
for (const e of errors) console.error(`  ERROR ${e}`);
process.exit(errors.length ? 1 : 0);
