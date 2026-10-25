/** Shared e2e constants (imported by playwright.config.ts and the specs). */
export const BASE_PATH = '/eu-intel/';
/** `vite preview` of dist/ (SPA fallback) — general navigation tests. Ports can be moved with E2E_PREVIEW_PORT and
 * E2E_PAGES_PORT, e.g. when another checkout's servers already use the defaults. */
export const PREVIEW_ORIGIN = `http://127.0.0.1:${process.env.E2E_PREVIEW_PORT || 4173}`;
/** tests/e2e/pages-server.mjs — GitHub Pages semantics (no rewrites) — deep-link tests. */
export const PAGES_ORIGIN = `http://127.0.0.1:${process.env.E2E_PAGES_PORT || 4174}`;
export const SITE_NAME = 'EU Legislative Intelligence';
/** EP procedure id of the AI Act, 2021/0106(COD). */
export const AI_ACT_ID = '2021-0106';
