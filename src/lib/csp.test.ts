/**
 * The Content-Security-Policy of every page (index.html, copied into each prerendered shell) allows no inline styles or
 * scripts, and scripts/check_privacy.mjs, which CI and the deploy run on the built site, fails a build that would
 * bring them back. React sets its `style` props through the CSSOM, which the policy does not restrict; the browser
 * tests check that no page reports a violation (tests/e2e/metadata.spec.ts).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = new URL('../../', import.meta.url);
const INDEX = readFileSync(new URL('index.html', ROOT), 'utf8');
const policy = /http-equiv="Content-Security-Policy" content="([^"]*)"/.exec(INDEX)?.[1] ?? '';

/** check_privacy.mjs on a built site of one page; returns its exit status and report. */
function checkPage(html: string): { status: number | null; report: string } {
  const dir = mkdtempSync(join(tmpdir(), 'csp-'));
  mkdirSync(join(dir, 'dist'));
  mkdirSync(join(dir, 'src'));
  writeFileSync(join(dir, 'dist', 'index.html'), html);
  const r = spawnSync(process.execPath, [new URL('scripts/check_privacy.mjs', ROOT).pathname, '--dist', 'dist', '--src', 'src'], {
    cwd: dir,
    encoding: 'utf8',
  });
  rmSync(dir, { recursive: true, force: true });
  return { status: r.status, report: `${r.stdout}${r.stderr}` };
}

describe('the Content-Security-Policy', () => {
  it("allows styles and scripts from the site's own files only", () => {
    const directives = Object.fromEntries(policy.split(';').map((d) => d.trim().split(/\s+/)).map(([k, ...v]) => [k, v]));
    expect(directives['style-src']).toEqual(["'self'"]);
    expect(directives['script-src']).toEqual(["'self'"]);
    expect(policy).not.toContain('unsafe-');
  });

  it('passes the privacy check, which fails a policy with unsafe-inline and an inline style', () => {
    expect(checkPage(INDEX).status).toBe(0);
    const unsafe = checkPage(INDEX.replace("style-src 'self';", "style-src 'self' 'unsafe-inline';"));
    expect(unsafe.status).toBe(1);
    expect(unsafe.report).toContain("CSP style-src allows 'unsafe-inline'");
    const attribute = checkPage(INDEX.replace('<div id="root"></div>', '<div id="root" style="color: red"></div>'));
    expect(attribute.status).toBe(1);
    expect(attribute.report).toContain('inline style (blocked by the CSP)');
    expect(checkPage(INDEX.replace('</head>', '<style>body { color: red }</style></head>')).report).toContain('inline style');
  });
});
