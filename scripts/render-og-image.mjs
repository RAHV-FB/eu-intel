#!/usr/bin/env node
// Renders public/og-image.png, the image of the site's link previews (og:image, scripts/seo.mjs), from the site's icon:
// the SVG of the icon link in index.html, 512 × 512 pixels on the icon's own blue, so that a platform that crops or
// rounds the image keeps it whole. The PNG is committed (Vite copies public/ into the site); run this again when the icon
// changes, and commit the result:
//
//   node scripts/render-og-image.mjs                          # with the Chromium of `npx playwright install chromium`
//   CHROMIUM=/path/to/chrome node scripts/render-og-image.mjs # with another Chromium
//
// The same Chromium gives the same image, byte for byte: shapes only, no text, so no font comes into it.
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const SIZE = 512;
const OUT = 'public/og-image.png';

const href = /<link rel="icon" href="data:image\/svg\+xml,([^"]+)"/.exec(readFileSync('index.html', 'utf8'))?.[1];
if (!href) throw new Error('render-og-image: no SVG icon link in index.html');
const svg = decodeURIComponent(href);
// the icon's square: its fill is the background, so that the rounded corners do not show
const fill = /<rect\b[^>]*\bfill='(#[0-9A-Fa-f]{3,6})'/.exec(svg)?.[1];
if (!fill) throw new Error('render-og-image: no filled square in the icon');

const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
try {
  const page = await browser.newPage({ viewport: { width: SIZE, height: SIZE }, deviceScaleFactor: 1 });
  const sized = svg.replace('<svg ', `<svg width='${SIZE}' height='${SIZE}' `);
  await page.setContent(`<!doctype html><html><body style="margin:0;background:${fill}">${sized}</body></html>`);
  await page.screenshot({ path: OUT, clip: { x: 0, y: 0, width: SIZE, height: SIZE } });
} finally {
  await browser.close();
}
const png = readFileSync(OUT);
console.log(`render-og-image: wrote ${OUT} (${png.readUInt32BE(16)} × ${png.readUInt32BE(20)} px, ${png.length} bytes)`);
