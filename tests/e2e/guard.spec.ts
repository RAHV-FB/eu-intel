/**
 * The guard of every test (fixtures.ts) judges what the page does while the test runs. After a test has failed,
 * Playwright takes its failure screenshot, and in WebKit that screenshot appends a <style> to the page, which the site's
 * CSP refuses with a console error: listed beside the real failure, it made every WebKit failure read as a CSP flake.
 */
import { expect, test } from '@playwright/test';
import { watchPage } from './fixtures';

// the site's policy (index.html): no inline styles
const PAGE = `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'"><p>A page</p>`;

test('the guard records what the page logs while the test runs, and nothing once the test has failed', async ({ page }) => {
  let running = true;
  const { errors } = watchPage(page, () => running);
  await page.route('http://site.test/', (route) => route.fulfill({ contentType: 'text/html', body: PAGE }));
  await page.goto('http://site.test/');
  const logged = (text: string) => page.waitForEvent('console', (m) => m.type() === 'error' && m.text() === text);

  let message = logged('while the test runs');
  await page.evaluate(() => console.error('while the test runs'));
  await message;
  expect(errors).toEqual([expect.stringMatching(/^console\.error: while the test runs /)]);

  // the test fails; then, what WebKit's failure screenshot does (playwright-core, screenshotter.js), and a console error
  running = false;
  message = logged('after the test failed');
  await page.evaluate(() => {
    const style = document.createElement('style');
    style.textContent = 'body {}';
    document.head.appendChild(style);
    document.documentElement.getBoundingClientRect();
    style.remove();
    console.error('after the test failed');
  });
  await message;
  expect(errors, 'nothing recorded after the failure').toHaveLength(1);
});
