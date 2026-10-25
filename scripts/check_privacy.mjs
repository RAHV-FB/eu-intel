#!/usr/bin/env node
// Privacy & safety gate for the static build. Zero dependencies; runs in CI after `npm run build`.
//
//   node scripts/check_privacy.mjs [--dist dist] [--src src] [--allow-origin https://example.org]...
//
// Fails (exit 1) when the built site could make a visitor's browser contact a third party, or when the
// source introduces tracking or unsafe HTML injection:
//   dist/**/*.html  third-party URLs in resource-loading markup (script/link rel=stylesheet|icon|preload…/
//                   img/srcset/iframe/source/video/audio/embed/object/track/form/base/meta refresh), inline
//                   <style>/style="" url()s, a missing or non-'self' Content-Security-Policy meta or one with
//                   'unsafe-inline', and inline <style>/style="" (which that CSP blocks).
//                   Plain <a href> links to official sources are fine and are NOT flagged.
//   dist/**/*.css   third-party url(...) / @import (e.g. hosted web fonts).
//   dist/**/*.js    network calls to literal third-party URLs (fetch/XHR/import()), sendBeacon, WebSocket,
//                   EventSource, JSX resource elements with third-party src, known CDN/font/embed hosts.
//   dist/data/**    image-like fields (photo, image, logo…) pointing at third-party hosts.
//   everywhere      analytics/tracking code (Google Analytics/gtag/GTM, Plausible, Umami, Hotjar, Meta
//                   pixel, Matomo/Piwik, Clarity, Mixpanel, Segment, Cloudflare Insights, Sentry CDN) and
//                   document.cookie / cookieStore writes.
//   src/**          dangerouslySetInnerHTML, innerHTML/outerHTML assignment, insertAdjacentHTML,
//                   document.write, eval/new Function, dynamic <script>/<iframe> creation, third-party
//                   resource URLs in JSX or CSS.
// Patterns are code-shaped (e.g. "plausible.io", "gtag(") so prose such as "we do not use Google Analytics"
// on the privacy page is not a violation.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
};
const DIST = opt('--dist', 'dist');
const SRC = opt('--src', 'src');
const ALLOWED_ORIGINS = new Set(
  args.flatMap((a, i) => (a === '--allow-origin' && args[i + 1] ? [args[i + 1].replace(/\/$/, '')] : [])),
);

const violations = [];
const add = (file, index, text, rule, snippet) =>
  violations.push({ file: relative(process.cwd(), file), line: lineOf(text, index), rule, snippet: clip(snippet) });

function lineOf(text, index) {
  if (index == null || index < 0) return 0;
  let n = 1;
  for (let i = 0; i < index && i < text.length; i++) if (text.charCodeAt(i) === 10) n++;
  return n;
}
const clip = (s) => {
  const t = String(s).replace(/\s+/g, ' ').trim();
  return t.length > 160 ? `${t.slice(0, 157)}…` : t;
};

function* walk(dir) {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '.git') continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else yield p;
  }
}

/** True when `url` would be fetched from somewhere other than the site itself. */
function isThirdParty(url) {
  const u = url.trim().replace(/^['"]|['"]$/g, '');
  if (!/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(u)) return false; // relative, data:, blob:, #fragment, mailto:
  try {
    const origin = new URL(u.startsWith('//') ? `https:${u}` : u).origin;
    return !ALLOWED_ORIGINS.has(origin);
  } catch {
    return true;
  }
}

// ------------------------------------------------------------------ shared patterns

const ANALYTICS = [
  [/google-analytics\.com|googletagmanager\.com|\bgtag\s*\(\s*['"](?:config|js|event|set|consent)['"]|\bdataLayer\s*\.\s*push\s*\(/i, 'Google Analytics / Tag Manager'],
  [/plausible\.io|\bplausible\s*\(\s*['"]/i, 'Plausible'],
  [/umami\.is|cloud\.umami|data-website-id|\bumami\s*\.\s*track\s*\(/i, 'Umami'],
  [/hotjar\.(?:com|io)|_hjSettings/i, 'Hotjar'],
  [/connect\.facebook\.net|\bfbq\s*\(\s*['"](?:init|track)|facebook\.com\/tr\b/i, 'Meta (Facebook) pixel'],
  [/matomo\.(?:js|php)|piwik\.(?:js|php)|\b_paq\s*\.\s*push\s*\(/i, 'Matomo / Piwik'],
  [/clarity\.ms/i, 'Microsoft Clarity'],
  [/mixpanel\.com|cdn\.mxpnl\.com|\bmixpanel\s*\.\s*(?:init|track)\s*\(/i, 'Mixpanel'],
  [/cdn\.segment\.(?:com|io)|\banalytics\s*\.\s*(?:track|page|identify)\s*\(/i, 'Segment'],
  [/static\.cloudflareinsights\.com|data-cf-beacon/i, 'Cloudflare Web Analytics'],
  [/browser\.sentry-cdn\.com|js\.sentry-cdn\.com|ingest\.sentry\.io/i, 'Sentry'],
  [/cdn\.amplitude\.com|api\.amplitude\.com|stats\.wp\.com|static\.addtoany\.com|platform\.twitter\.com\/widgets/i, 'third-party tracker/widget'],
];
const COOKIE_WRITE = /document\s*\.\s*cookie\s*\+?=(?!=)|\bcookieStore\s*\.\s*set\s*\(/;
const CDN_HOSTS =
  /\/\/(?:fonts\.googleapis\.com|fonts\.gstatic\.com|ajax\.googleapis\.com|cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|use\.typekit\.net|p\.typekit\.net|use\.fontawesome\.com|kit\.fontawesome\.com|code\.jquery\.com|stackpath\.bootstrapcdn\.com|maxcdn\.bootstrapcdn\.com|maps\.googleapis\.com|www\.youtube(?:-nocookie)?\.com\/embed|player\.vimeo\.com|www\.gravatar\.com|secure\.gravatar\.com|polyfill\.io|esm\.sh|cdn\.skypack\.dev)/i;
const RESOURCE_RELS =
  /\b(?:stylesheet|icon|apple-touch-icon|mask-icon|preload|prefetch|modulepreload|preconnect|dns-prefetch|prerender|manifest)\b/i;

function scanAll(file, text, label) {
  for (const [re, name] of ANALYTICS) {
    const m = re.exec(text);
    if (m) add(file, m.index, text, `analytics/tracking code (${name})`, text.slice(Math.max(0, m.index - 40), m.index + 80));
  }
  const c = COOKIE_WRITE.exec(text);
  if (c) add(file, c.index, text, 'cookie write', text.slice(Math.max(0, c.index - 40), c.index + 60));
  if (label !== 'json') {
    const h = CDN_HOSTS.exec(text);
    if (h) add(file, h.index, text, 'third-party CDN / font / embed host', text.slice(Math.max(0, h.index - 60), h.index + 80));
  }
}

function scanCssUrls(file, text, offset = 0, whole = text) {
  for (const m of text.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi)) {
    if (isThirdParty(m[2])) add(file, offset + m.index, whole, 'third-party url() in CSS', m[0]);
  }
  for (const m of text.matchAll(/@import\s+(?:url\(\s*)?['"]?([^'");\s]+)/gi)) {
    if (isThirdParty(m[1])) add(file, offset + m.index, whole, 'third-party @import in CSS', m[0]);
  }
}

// ------------------------------------------------------------------ dist

function attrs(tag) {
  const out = {};
  for (const m of tag.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?/g)) {
    out[m[1].toLowerCase()] = m[2] ? m[2].replace(/^['"]|['"]$/g, '') : '';
  }
  return out;
}

function checkCsp(file, html) {
  const m = /<meta\s[^>]*http-equiv\s*=\s*["']?content-security-policy["']?[^>]*>/i.exec(html);
  if (!m) {
    add(file, 0, html, 'missing Content-Security-Policy <meta>', '(no CSP meta tag)');
    return;
  }
  const policy = attrs(m[0]).content ?? '';
  const directives = Object.fromEntries(
    policy
      .split(';')
      .map((d) => d.trim().split(/\s+/))
      .filter((d) => d[0])
      .map(([k, ...v]) => [k.toLowerCase(), v]),
  );
  if (!directives['default-src']) add(file, m.index, html, "CSP lacks default-src", policy);
  const FETCH = ['default-src', 'script-src', 'script-src-elem', 'style-src', 'style-src-elem', 'img-src', 'connect-src', 'font-src', 'media-src', 'frame-src', 'child-src', 'worker-src', 'manifest-src', 'object-src', 'prefetch-src'];
  for (const d of FETCH) {
    for (const src of directives[d] ?? []) {
      const ok = ["'self'", "'none'", 'data:', 'blob:'].includes(src);
      if (!ok && !ALLOWED_ORIGINS.has(src.replace(/\/$/, ''))) {
        add(file, m.index, html, src.startsWith("'unsafe-") ? `CSP ${d} allows ${src}` : `CSP ${d} allows a non-self source`, `${d} ${src}`);
      }
    }
  }
}

function scanHtml(file, html) {
  scanAll(file, html, 'html');
  checkCsp(file, html);
  for (const m of html.matchAll(/<(script|link|img|iframe|frame|source|video|audio|embed|object|track|input|form|base|meta|image|use)\b[^>]*>/gi)) {
    const tag = m[1].toLowerCase();
    const a = attrs(m[0]);
    const urls = [];
    if (tag === 'link') {
      if (RESOURCE_RELS.test(a.rel ?? '')) urls.push(a.href);
      if (a.imagesrcset) urls.push(...a.imagesrcset.split(',').map((s) => s.trim().split(/\s+/)[0]));
    } else if (tag === 'meta') {
      const refresh = /^\s*refresh\s*$/i.test(a['http-equiv'] ?? '') && /url\s*=\s*([^;]+)/i.exec(a.content ?? '');
      if (refresh) urls.push(refresh[1]);
    } else if (tag === 'form') {
      urls.push(a.action);
    } else if (tag === 'base') {
      urls.push(a.href);
    } else {
      urls.push(a.src, a.data, a.poster, a.href, a['xlink:href']);
      if (a.srcset) urls.push(...a.srcset.split(',').map((s) => s.trim().split(/\s+/)[0]));
    }
    for (const u of urls.filter(Boolean)) {
      if (isThirdParty(u)) add(file, m.index, html, `third-party URL in <${tag}>`, m[0]);
    }
  }
  for (const m of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) scanCssUrls(file, m[1], m.index, html);
  for (const m of html.matchAll(/\sstyle\s*=\s*("[^"]*"|'[^']*')/gi)) scanCssUrls(file, m[1], m.index, html);
  // the CSP has no 'unsafe-inline': a <style> element or style="" attribute in a page would not be applied
  for (const m of html.matchAll(/<style\b|<[a-z][^>]*?\sstyle\s*=/gi)) add(file, m.index, html, 'inline style (blocked by the CSP)', html.slice(m.index, m.index + 80));
}

function scanJs(file, js) {
  scanAll(file, js, 'js');
  const Q = '[`\'"]';
  const ABS = `${Q}(?:https?:)?\\/\\/`;
  const rules = [
    [new RegExp(`\\bfetch\\s*\\(\\s*${ABS}`, 'g'), 'fetch() to a literal third-party URL'],
    [new RegExp(`\\bimport\\s*\\(\\s*${ABS}`, 'g'), 'dynamic import() from a third-party URL'],
    [new RegExp(`\\.open\\s*\\(\\s*${Q}[A-Za-z]+${Q}\\s*,\\s*${ABS}`, 'g'), 'XMLHttpRequest to a third-party URL'],
    [/\bsendBeacon\s*\(/g, 'navigator.sendBeacon (beaconing)'],
    [/\bnew\s+WebSocket\s*\(/g, 'WebSocket connection'],
    [/\bnew\s+EventSource\s*\(/g, 'EventSource connection'],
    [/\bimportScripts\s*\(/g, 'importScripts()'],
    [
      new RegExp(
        `\\bjsxs?\\s*\\(\\s*${Q}(?:img|script|iframe|source|video|audio|embed|object|track|link|image)${Q}\\s*,\\s*\\{[^}]{0,600}?\\b(?:src|srcSet|href|data|poster)\\s*:\\s*${ABS}`,
        'g',
      ),
      'resource element with a third-party URL',
    ],
  ];
  for (const [re, rule] of rules) {
    for (const m of js.matchAll(re)) {
      const tail = js.slice(m.index, m.index + m[0].length + 120);
      const url = /(?:https?:)?\/\/[^`'"\s)]+/.exec(tail.slice(m[0].length - 10))?.[0];
      if (url && !isThirdParty(url)) continue;
      add(file, m.index, js, rule, tail);
    }
  }
}

const IMAGE_KEY = /^(?:photo|photos|image|images|img|thumbnail|thumb|logo|avatar|icon|picture|portrait|banner|cover)(?:_?url|_?src)?$/i;
function scanJson(file, text) {
  scanAll(file, text, 'json');
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return; // not our concern here; build/validate own JSON validity
  }
  const stack = [data];
  while (stack.length) {
    const v = stack.pop();
    if (Array.isArray(v)) stack.push(...v);
    else if (v && typeof v === 'object') {
      for (const [k, x] of Object.entries(v)) {
        if (typeof x === 'string' && IMAGE_KEY.test(k) && isThirdParty(x)) {
          add(file, text.indexOf(x), text, `third-party image URL in data field "${k}" (would be hot-linked)`, x);
        } else if (x && typeof x === 'object') stack.push(x);
      }
    }
  }
}

// ------------------------------------------------------------------ src

function scanSrc(file, text) {
  scanAll(file, text, 'src');
  const rules = [
    [/dangerouslySetInnerHTML/g, 'dangerouslySetInnerHTML (render text, never raw HTML)'],
    [/\.(?:inner|outer)HTML\s*\+?=(?!=)/g, 'innerHTML/outerHTML assignment'],
    [/\binsertAdjacentHTML\s*\(/g, 'insertAdjacentHTML()'],
    [/\bdocument\s*\.\s*write(?:ln)?\s*\(/g, 'document.write()'],
    [/(?<![\w.])eval\s*\(|\bnew\s+Function\s*\(/g, 'eval / new Function'],
    [/\bcreateElement\s*\(\s*['"`](?:script|iframe)['"`]/g, 'dynamic <script>/<iframe> creation'],
    [/\bsendBeacon\s*\(|\bnew\s+(?:WebSocket|EventSource)\s*\(/g, 'beacon / socket connection'],
    [/<(?:img|script|iframe|source|video|audio|embed|object|track|link|image)\b[^>]*?\b(?:src|srcSet|href|data|poster)\s*=\s*\{?\s*[`'"](?:https?:)?\/\//g, 'third-party resource URL in JSX'],
    [/\bfetch\s*\(\s*[`'"](?:https?:)?\/\//g, 'fetch() to a third-party URL (visitors must not contact external APIs)'],
  ];
  for (const [re, rule] of rules) {
    for (const m of text.matchAll(re)) add(file, m.index, text, rule, text.slice(Math.max(0, m.index - 30), m.index + 120));
  }
  if (extname(file) === '.css') scanCssUrls(file, text);
}

// ------------------------------------------------------------------ main

if (!existsSync(DIST)) {
  console.error(`check_privacy: ${DIST}/ not found — run \`npm run build\` first.`);
  process.exit(2);
}
let files = 0;
for (const f of walk(DIST)) {
  const ext = extname(f).toLowerCase();
  if (!['.html', '.htm', '.css', '.js', '.mjs', '.json', '.xml', '.svg', '.webmanifest', '.txt'].includes(ext)) continue;
  const text = readFileSync(f, 'utf8');
  files++;
  if (ext === '.html' || ext === '.htm') scanHtml(f, text);
  else if (ext === '.css') {
    scanAll(f, text, 'css');
    scanCssUrls(f, text);
  } else if (ext === '.js' || ext === '.mjs') scanJs(f, text);
  else if (ext === '.json' || ext === '.webmanifest') scanJson(f, text);
  else if (ext === '.svg') {
    scanAll(f, text, 'svg');
    for (const m of text.matchAll(/\b(?:href|xlink:href)\s*=\s*["']([^"']+)["']/gi)) {
      if (isThirdParty(m[1])) add(f, m.index, text, 'third-party reference in SVG', m[0]);
    }
  } else scanAll(f, text, 'json'); // .xml feeds / .txt: tracking code only; feed links are plain links
}
for (const f of [...walk(SRC), 'index.html']) {
  if (!existsSync(f) || !/\.(?:[cm]?[jt]sx?|css|html)$/.test(f) || /\.(?:test|spec)\.[jt]sx?$/.test(f)) continue;
  files++;
  scanSrc(f, readFileSync(f, 'utf8'));
}

if (violations.length) {
  const seen = new Set();
  console.error(`check_privacy: ${violations.length} violation(s) in ${files} files scanned:\n`);
  for (const v of violations) {
    const key = `${v.file}:${v.line}:${v.rule}`;
    if (seen.has(key)) continue;
    seen.add(key);
    console.error(`  ${v.file}${v.line ? `:${v.line}` : ''}  ${v.rule}\n      ${v.snippet}`);
    if (process.env.GITHUB_ACTIONS) console.log(`::error file=${v.file},line=${v.line || 1}::${v.rule}`);
  }
  process.exit(1);
}
console.log(`check_privacy: OK — ${files} files scanned in ${DIST}/ and ${SRC}/; no third-party loads, trackers, cookie writes or raw-HTML injection.`);
