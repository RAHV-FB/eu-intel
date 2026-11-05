/**
 * The data files requested from a page's address (src/lib/routeData.ts), before the page's code has loaded: the files
 * of each kind of page, and that each one is a file the page itself reads (in its source, or in the shared hook it
 * reads it with), so that the list cannot drift into fetching what no page uses.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { routeData } from './routeData';

const SRC = new URL('../', import.meta.url);
const read = (f: string) => readFileSync(new URL(f, SRC), 'utf8');
// where each kind of page reads its data: the page, and the shared hooks it uses (useTopics, useGroups, loadSearch;
// meta.json is the header's and footer's, src/components/Layout.tsx)
const READERS: [address: string, files: string[]][] = [
  ['/', ['pages/Home.tsx']],
  ['/legislation', ['pages/Legislation.tsx', 'features/legislation/labels.ts']],
  ['/legislation/changes', ['pages/Changes.tsx', 'features/legislation/labels.ts']],
  ['/legislation/2021-0106', ['pages/Dossier.tsx', 'features/legislation/labels.ts']],
  ['/legislation/32024R1689', ['pages/Dossier.tsx']],
  ['/votes', ['pages/Votes.tsx', 'features/legislation/labels.ts']],
  ['/votes/166051', ['pages/Vote.tsx', 'features/people/labels.ts']],
  ['/search', ['pages/Search.tsx', 'lib/search.ts']],
  ['/insights', ['pages/Insights.tsx']],
  ['/countries', ['pages/Countries.tsx']],
  ['/countries/ie', ['pages/Country.tsx', 'features/people/labels.ts']],
  ['/countries/GB', ['pages/Country.tsx']],
  ['/about', ['pages/About.tsx']],
  ['/people', ['pages/People.tsx', 'features/people/labels.ts']],
  ['/people?view=parties', ['pages/People.tsx', 'features/people/labels.ts']],
  ['/people/meps/197400', ['pages/Mep.tsx', 'features/people/labels.ts']],
  ['/people/groups/epp', ['pages/Group.tsx']],
  ['/people/parties/6848', ['pages/Party.tsx', 'features/people/labels.ts']],
];

/** The ways a page names a data file: 'votes/index.json', or `votes/${…}.json` for one of a folder's files. */
function named(source: string, file: string): boolean {
  if (source.includes(`'${file}'`)) return true;
  const folder = /^(.*\/)[^/]+\.json$/.exec(file)?.[1];
  return !!folder && source.includes(`\`${folder}\${`);
}

describe('routeData', () => {
  it('lists the files each kind of page reads as it opens', () => {
    expect(routeData('/')).toEqual(['meta.json', 'home.json', 'activity.json']);
    expect(routeData('')).toEqual(['meta.json', 'home.json', 'activity.json']);
    expect(routeData('/legislation/')).toEqual(['meta.json', 'dossiers/index.json', 'topics.json']);
    expect(routeData('/legislation/2021-0106/')).toEqual(['meta.json', 'dossiers/2021-0106.json', 'topics.json']);
    expect(routeData('/legislation/2016-0282A')).toEqual(['meta.json', 'dossiers/2016-0282A.json', 'topics.json']);
    expect(routeData('/legislation/32024R1689')).toEqual(['meta.json', 'dossiers/index.json']);
    expect(routeData('/votes/')).toEqual(['meta.json', 'votes/index.json', 'topics.json']);
    expect(routeData('/votes/166051/')).toEqual(['meta.json', 'votes/166051.json', 'people/groups.json', 'people/parties.json']);
    expect(routeData('/search/', '?q=climate')).toEqual(['meta.json', 'search.json']);
    expect(routeData('/countries/BE/')).toEqual(['meta.json', 'countries/BE.json', 'people/groups.json']);
    expect(routeData('/countries/be')).toEqual(['meta.json', 'countries/BE.json', 'people/groups.json']);
    expect(routeData('/people/', '?view=parties')).toEqual(['meta.json', 'people/parties.json', 'people/groups.json']);
    expect(routeData('/people/', '?view=groups')).toEqual(['meta.json', 'people/groups.json']);
    expect(routeData('/people/meps/197400/')).toEqual(['meta.json', 'people/meps/197400.json', 'people/groups.json', 'votes/titles.json']);
  });

  it('asks for nothing a page would not: an address that is no page, or not one of its files, gets the header’s file only', () => {
    for (const address of [
      '/legislation/not-a-file',
      '/legislation/2021-0106/extra',
      '/votes/index',
      '/votes/166051/extra',
      '/countries/XX',
      '/people/meps/..%2F..%2Fmeta',
      '/people/committees/1',
      '/following',
      '/privacy',
      '/how-the-eu-works',
      '/no/such/page/here',
      '/votes/%E0%A4%A',
    ]) {
      expect(routeData(address), address).toEqual(['meta.json']);
    }
  });

  it('each file listed is one its page (or the shared hook it uses) reads', () => {
    const layout = read('components/Layout.tsx');
    for (const [address, readers] of READERS) {
      const [path, search = ''] = address.split('?');
      const source = readers.map(read).join('\n');
      for (const file of routeData(path, search ? `?${search}` : '')) {
        expect(named(file === 'meta.json' ? layout : source, file), `${address}: ${file} in ${readers.join(', ')}`).toBe(true);
      }
    }
  });
});
