#!/usr/bin/env node
// Minimal static server that behaves like GitHub Pages for a project site, so e2e tests catch
// deep-link problems that `vite preview` (which has an SPA fallback) would hide.
//
//   node tests/e2e/pages-server.mjs [dir=dist] [port=4174]      (env BASE_PATH, default "/eu-intel/")
//
// Behaviour mirrored from Pages:
//   - the site is served only under BASE_PATH; anything else is a plain 404
//   - "/base/foo"  -> 301 to "/base/foo/" when foo is a directory
//   - "/base/foo/" -> foo/index.html (200), or 404 if the directory has no index.html
//   - "/base/foo"  -> foo.html when that file exists (Pages serves extensionless .html)
//   - anything missing -> 404 status with the site's 404.html as the body (the SPA fallback)
// No rewrites, no SPA fallback with status 200 — exactly what a visitor on Pages would get.
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, resolve, sep } from 'node:path';

const ROOT = resolve(process.argv[2] ?? 'dist');
const PORT = Number(process.argv[3] ?? process.env.PORT ?? 4174);
const BASE = (process.env.BASE_PATH ?? '/eu-intel/').replace(/\/?$/, '/');

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
};

if (!existsSync(join(ROOT, 'index.html'))) {
  console.error(`pages-server: ${ROOT}/index.html not found — build the site first`);
  process.exit(1);
}

const isFile = (p) => existsSync(p) && statSync(p).isFile();
const isDir = (p) => existsSync(p) && statSync(p).isDirectory();

function send(req, res, status, file, headers = {}) {
  res.writeHead(status, {
    'Content-Type': TYPES[extname(file).toLowerCase()] ?? 'application/octet-stream',
    'Content-Length': statSync(file).size,
    'Cache-Control': 'no-cache',
    ...headers,
  });
  if (req.method === 'HEAD') return res.end();
  createReadStream(file).pipe(res);
}

function notFound(req, res) {
  const page = join(ROOT, '404.html');
  if (isFile(page)) return send(req, res, 404, page);
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('404 Not Found');
}

const server = createServer((req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    return res.end();
  }
  const url = new URL(req.url ?? '/', 'http://localhost');
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return notFound(req, res);
  }
  if (`${pathname}/` === BASE) {
    res.writeHead(301, { Location: BASE + url.search });
    return res.end();
  }
  if (!pathname.startsWith(BASE)) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    return res.end('404 Not Found (outside the project site base path)');
  }
  const target = resolve(ROOT, `.${sep}${pathname.slice(BASE.length)}`);
  if (target !== ROOT && !target.startsWith(ROOT + sep)) return notFound(req, res); // path traversal

  if (isDir(target)) {
    if (!pathname.endsWith('/')) {
      res.writeHead(301, { Location: `${url.pathname}/${url.search}` });
      return res.end();
    }
    const index = join(target, 'index.html');
    return isFile(index) ? send(req, res, 200, index) : notFound(req, res);
  }
  if (isFile(target)) return send(req, res, 200, target);
  if (isFile(`${target}.html`)) return send(req, res, 200, `${target}.html`);
  return notFound(req, res);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`pages-server: serving ${ROOT} at http://127.0.0.1:${PORT}${BASE} (GitHub Pages semantics)`);
});
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => server.close(() => process.exit(0)));
