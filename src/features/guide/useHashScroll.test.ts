import { describe, expect, it } from 'vitest';
import { fragmentId } from './useHashScroll';

describe('the element id a URL fragment names', () => {
  it('is the fragment, percent-decoded', () => {
    expect(fragmentId('#timeline')).toBe('timeline');
    expect(fragmentId('#ep-votes')).toBe('ep-votes');
    expect(fragmentId('#r%C3%A9sum%C3%A9')).toBe('résumé');
    expect(fragmentId('')).toBe('');
  });

  it('is the fragment as written when it is not valid percent-encoding, rather than an error', () => {
    // decodeURIComponent throws a URIError on these: the page that read the fragment could not be displayed
    expect(fragmentId('#100%')).toBe('100%');
    expect(fragmentId('#%E0%A4%A')).toBe('%E0%A4%A');
    expect(fragmentId('#%ZZ')).toBe('%ZZ');
  });
});
