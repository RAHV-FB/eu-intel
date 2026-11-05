import { COUNTRY_NAMES } from './format';
import { loadData } from './data';

/**
 * The data files a page reads as soon as it opens, by its address (relative to the site's base path, as the router
 * sees it). Requesting them when the address is known, instead of when the page has rendered, takes them off the
 * page's critical path: a page's code is a lazy chunk, so its own requests would start only after the main bundle, the
 * chunk and its style sheets had loaded and the page had rendered once (on a slow phone connection, about a second
 * later). loadData keeps each request, so the page's own useData gets the same response and nothing is fetched twice.
 *
 * Only files a page reads on (nearly) every visit are listed. A file a page asks for only once another has loaded is
 * listed where nearly all such pages ask for it: the vote tables of MEP, group and party pages (votes/titles.json),
 * a group's members (people/meps.json, 9 of the 10 groups) and the national parties of a vote with individual votes.
 * Each page's own useData calls stay the source of truth: a file missing here is only requested later, and
 * src/lib/routeData.test.ts checks that each file listed is one its page reads.
 */
const DOSSIER_ID = /^\d{4}-\d{4}[A-Z]{0,2}$/; // as src/pages/Dossier.tsx
const CELEX_ID = /^[0-9][0-9]{4}[A-Z]{1,2}[0-9]{4}(\(\d{2}\))?$/;
const VOTE_ID = /^\d+$/; // as src/pages/Vote.tsx
const ENTITY_ID = /^[\w-]+$/; // MEP and party ids (digits), group slugs ("s-d")
const MEMBER_STATES = new Set(Object.keys(COUNTRY_NAMES).filter((c) => c !== 'GB')); // as src/pages/Country.tsx

export function routeData(pathname: string, search = ''): string[] {
  const parts = pathname
    .split('/')
    .filter(Boolean)
    .map((p) => {
      try {
        return decodeURIComponent(p);
      } catch {
        return '\u0000'; // matches no id
      }
    });
  const [section = '', id, sub] = parts;
  const files = ['meta.json']; // the header and footer (src/components/Layout.tsx)
  const page = (...more: string[]) => files.concat(more);
  if (parts.length > 3) return files;
  switch (section) {
    case '':
      return page('home.json', 'activity.json');
    case 'legislation':
      if (id === undefined) return page('dossiers/index.json', 'topics.json');
      if (sub !== undefined) return files;
      if (id === 'changes') return page('activity.json', 'dossiers/index.json', 'topics.json');
      if (DOSSIER_ID.test(id)) return page(`dossiers/${id}.json`, 'topics.json');
      if (CELEX_ID.test(id)) return page('dossiers/index.json');
      return files;
    case 'votes':
      if (id === undefined) return page('votes/index.json', 'topics.json');
      // 2,996 of the 3,000 votes listed on 5 Nov 2026 have individual votes, which the table by national party names
      return sub === undefined && VOTE_ID.test(id) ? page(`votes/${id}.json`, 'people/groups.json', 'people/parties.json') : files;
    case 'search':
      return id === undefined ? page('search.json') : files;
    case 'insights':
      return id === undefined ? page('insights.json', 'countries/index.json') : files;
    case 'countries':
      if (id === undefined) return page('countries/index.json');
      if (sub !== undefined) return files;
      if (MEMBER_STATES.has(id.toUpperCase())) return page(`countries/${id.toUpperCase()}.json`, 'people/groups.json');
      return id.toUpperCase() === 'GB' ? page('people/meps.json') : files;
    case 'about':
      return id === undefined ? page('countries/index.json') : files;
    case 'people': {
      if (id === undefined) {
        const view = new URLSearchParams(search).get('view');
        const list = view === 'parties' ? ['people/parties.json'] : view === 'groups' ? [] : ['people/meps.json'];
        return page(...list, 'people/groups.json');
      }
      if (sub === undefined || !ENTITY_ID.test(sub)) return files;
      // 1,270 of 1,280 MEPs, every group and 519 of 528 party records have votes listed (votes/titles.json)
      if (id === 'meps') return page(`people/meps/${sub}.json`, 'people/groups.json', 'votes/titles.json');
      if (id === 'groups') return page(`people/groups/${sub}.json`, 'people/meps.json', 'votes/titles.json');
      if (id === 'parties') return page(`people/parties/${sub}.json`, 'people/groups.json', 'votes/titles.json');
      return files;
    }
    default:
      return files;
  }
}

/** Request the data files of the page at this address (see routeData). Failures are left to the page, which asks for
 * the same file and shows its own error. */
export function preloadRouteData(pathname: string, search = ''): void {
  for (const path of routeData(pathname, search)) loadData(path).catch(() => {});
}
