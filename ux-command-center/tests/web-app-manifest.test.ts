import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, test } from 'vitest';

const root = resolve(__dirname, '..');
const manifestPath = resolve(root, 'public/manifest.webmanifest');

test('publishes both app icons through a linked web app manifest', () => {
  expect(existsSync(manifestPath), 'public/manifest.webmanifest must exist').toBe(true);
  if (!existsSync(manifestPath)) return;

  const html = readFileSync(resolve(root, 'index.html'), 'utf8');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as {
    name: string;
    short_name: string;
    theme_color: string;
    icons: Array<{ src: string; sizes: string; type: string }>;
  };

  expect(html).toContain('<link rel="manifest" href="/manifest.webmanifest" />');
  expect(manifest.name).toBe('Huinsight');
  expect(manifest.short_name).toBe('Huinsight');
  expect(manifest.theme_color).toBe('#3b82f6');
  expect(manifest.icons).toEqual([
    { src: '/icons/app-icon-192.png', sizes: '192x192', type: 'image/png' },
    { src: '/icons/app-icon-512.png', sizes: '512x512', type: 'image/png' },
  ]);

  for (const icon of manifest.icons) {
    expect(existsSync(resolve(root, `public${icon.src}`)), `${icon.src} must exist`).toBe(true);
  }
});
