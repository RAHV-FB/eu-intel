/**
 * formatNumber (src/lib/format.ts) writes numbers as toLocaleString('en-GB') does, with one formatter made once: a
 * formatter made on each call costs about 20 times as much, which the tables of a vote page (about 1,300 numbers) feel.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatNumber, plural } from './format';

describe('formatNumber', () => {
  afterEach(() => vi.restoreAllMocks());

  it('writes numbers as toLocaleString("en-GB") does, and a missing one as a dash', () => {
    for (const n of [0, 7, -5, 999, 1000, 1234.5678, 0.1 + 0.2, 1e21, -0, 12345678901, Number.NaN, Infinity]) {
      expect(formatNumber(n), String(n)).toBe(n.toLocaleString('en-GB'));
    }
    expect(formatNumber(1234567)).toBe('1,234,567');
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(plural(1200, 'vote')).toBe('1,200 votes');
  });

  it('does not set up a formatter for each number', () => {
    const perCall = vi.spyOn(Number.prototype, 'toLocaleString');
    const made = vi.spyOn(Intl, 'NumberFormat');
    for (let i = 0; i < 1000; i++) formatNumber(i * 1000);
    expect(perCall).not.toHaveBeenCalled();
    expect(made).not.toHaveBeenCalled();
  });
});
