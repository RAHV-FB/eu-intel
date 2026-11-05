import { describe, expect, it } from 'vitest';
import { NotFoundError } from '../../lib/data';
import { isMissing } from './missing';
import { isMissing as isMissingFile } from '../legislation/labels';

describe('a data file that does not exist, and one that cannot be read', () => {
  it('a 404, or the SPA page a dev server answers for a missing path, is a missing file (loadData: NotFoundError)', () => {
    expect(isMissing(new NotFoundError('dossiers/2099-0001.json'))).toBe(true);
  });

  it('a file that is not valid JSON is not a missing record: its page says it could not be loaded', () => {
    // a truncated or corrupted file: "We couldn't find this legislative file … It may not be in our dataset yet" was
    // shown for a file that is there
    let parseError: unknown;
    try {
      JSON.parse('{"id": "2021-0106", "ti');
    } catch (e) {
      parseError = e;
    }
    expect(parseError).toBeInstanceOf(SyntaxError);
    expect(isMissing(parseError)).toBe(false);
    expect(isMissing(new Error('Could not load dossiers/2021-0106.json (HTTP 500)'))).toBe(false);
    expect(isMissing(new TypeError('Failed to fetch'))).toBe(false);
  });

  it('is one rule for every page (the law and Following pages import it from the legislation labels)', () => {
    expect(isMissingFile).toBe(isMissing);
  });
});
