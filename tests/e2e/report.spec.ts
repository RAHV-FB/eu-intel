/**
 * "Report an error on this page" in the footer: GitHub's issue form for errors in the data
 * (.github/ISSUE_TEMPLATE/data-error.yml), with the page's own address in its `page` field, including the base path,
 * the query and the hash, and updated when the reader moves to another page. See playwright.config.ts to run.
 */
import { AI_ACT_ID, BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

const FORM = 'https://github.com/RAHV-FB/eu-intel/issues/new?template=data-error.yml&page=';

test('the footer links the error form with the address of the page being read', async ({ page }) => {
  await open(page, `legislation/${AI_ACT_ID}?tab=x#national`);
  const link = page.locator('.site-footer').getByRole('link', { name: /^Report an error on this page/ });
  const origin = new URL(page.url()).origin;
  await expect(link).toHaveAttribute('href', FORM + encodeURIComponent(`${origin}${BASE_PATH}legislation/${AI_ACT_ID}?tab=x#national`));
  await expect(link).toHaveAttribute('target', '_blank');
  // another page: the link follows it
  await page.locator('.site-footer').getByRole('link', { name: 'What changed' }).click();
  await expect(page).toHaveURL(/legislation\/changes/);
  await expect(link).toHaveAttribute('href', FORM + encodeURIComponent(`${origin}${BASE_PATH}legislation/changes`));
});
