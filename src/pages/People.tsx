import { Link, useSearchParams } from 'react-router-dom';
import type { MepSummary, PartySummary } from '../types/data';
import { useData } from '../lib/data';
import { EmptyState, ErrorState, Loading, LookupNotice, PageHeader } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { MepSearch } from '../features/people/MepSearch';
import { GroupsOverview, PartiesBrowse, PartyVsGroup } from '../features/people/GroupsAndParties';
import { useGroups } from '../features/people/labels';

type View = 'meps' | 'groups' | 'parties';
const VIEWS: { id: View; label: string }[] = [
  { id: 'meps', label: 'MEPs' },
  { id: 'groups', label: 'Political groups' },
  { id: 'parties', label: 'National parties' },
];

export default function People() {
  const [params] = useSearchParams();
  const view = (VIEWS.find((v) => v.id === params.get('view'))?.id ?? 'meps') as View;
  useDocumentTitle(view === 'meps' ? 'MEPs' : view === 'groups' ? 'Political groups' : 'National parties');

  const meps = useData<MepSummary[]>(view === 'meps' ? 'people/meps.json' : null);
  const parties = useData<PartySummary[]>(view === 'parties' ? 'people/parties.json' : null);
  const groups = useGroups();

  const state = view === 'meps' ? meps : view === 'parties' ? parties : groups;

  return (
    <div className="container page">
      <PageHeader
        eyebrow="European Parliament"
        title="People & Parties"
        lead="Members of the European Parliament (MEPs), the political groups they sit in, and the national parties they were elected for — from Parliament’s official records."
      />
      <PartyVsGroup />

      <nav aria-label="People and parties sections">
        <div className="segnav">
          {VIEWS.map((v) => (
            <Link key={v.id} to={v.id === 'meps' ? '/people' : `/people?view=${v.id}`} aria-current={v.id === view ? 'page' : undefined}>
              {v.label}
            </Link>
          ))}
        </div>
      </nav>

      {state.loading && <Loading />}
      {state.error && <ErrorState error={state.error} title="This list could not be loaded" />}
      {view !== 'groups' && <LookupNotice failed={groups.failed} what="Political group names" />}

      {view === 'meps' &&
        meps.data &&
        (meps.data.length ? <MepSearch meps={meps.data} groups={groups.byId} /> : <EmptyState title="No MEP data available in this build" />)}
      {view === 'groups' && groups.data && <GroupsOverview groups={groups.data} />}
      {view === 'parties' &&
        parties.data &&
        (parties.data.length ? (
          <PartiesBrowse parties={parties.data} groups={groups.byId} />
        ) : (
          <EmptyState title="No national party data available in this build" />
        ))}

      <p className="note" style={{ marginTop: 'var(--sp-6)' }}>
        We show only official records of membership, roles and recorded votes — no biographies or photos. Each MEP page links to their
        official profile on the European Parliament website.
      </p>
    </div>
  );
}
