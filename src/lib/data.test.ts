import { describe, expect, it } from 'vitest';
import { dataStateFor, type Loaded } from './data';

describe('useData state for the path a page asks for', () => {
  const ai: Loaded<{ id: string }> = { path: 'dossiers/2021-0106.json', data: { id: '2021-0106' }, error: undefined };

  it('gives a file once loaded from that path, and nothing while it loads', () => {
    expect(dataStateFor('dossiers/2021-0106.json', null)).toEqual({ data: undefined, error: undefined, loading: true });
    expect(dataStateFor('dossiers/2021-0106.json', ai)).toEqual({ data: { id: '2021-0106' }, error: undefined, loading: false });
  });

  it('never gives the file of the record a page showed before: it is loading the new one', () => {
    // a law's page opened from another law's page (the same page component, another address): the previous file was
    // shown under the new address, then taken for a malformed file ("We couldn't find this legislative file")
    expect(dataStateFor('dossiers/2025-0359.json', ai)).toEqual({ data: undefined, error: undefined, loading: true });
    const failed: Loaded<unknown> = { path: 'votes/1.json', data: undefined, error: new Error('HTTP 500') };
    expect(dataStateFor('votes/2.json', failed)).toEqual({ data: undefined, error: undefined, loading: true });
  });

  it('gives nothing, and is not loading, without a path', () => {
    expect(dataStateFor(null, ai)).toEqual({ data: undefined, error: undefined, loading: false });
  });
});
