import { Link } from 'react-router-dom';
import type { ActivityItem, HomeData, Meta, Topic } from '../types/data';
import { useData } from '../lib/data';
import { formatDate, formatNumber, noUpdateText, stillAhead } from '../lib/format';
import { asRetrieved, classifications, expiredReason, freshness, staleNote, type Classifications } from '../lib/freshness';
import { votesSince } from '../lib/scope';
import { PAGE_PLACEHOLDERS, SearchBox } from '../components/SearchBox';
import { ErrorState, Loading } from '../components/ui';
import { FeaturedCard } from '../features/home/FeaturedCard';
import { HomeLists } from '../features/home/HomeLists';
import { TopicGrid } from '../features/home/TopicGrid';
import { ThisWeek } from '../features/changes/ThisWeek';
import { useDocumentTitle } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import '../features/legislation/common.css';
import '../features/home/home.css';

// a "Stalled" file's subtitle, counted on the day the data was built (pipeline/build.py build_home)
const NO_UPDATE = /^No recorded procedural update in (\d+) days?$/;
// the badge of the files the Legislative Train reports as blocked in that list, and the part of its description on
// the files without a recorded update for a year or more (build_home)
const BLOCKED_BADGE = 'Officially blocked';
const THEN_INACTIVE = /, then o(rdinary-procedure files .+)$/;
const INACTIVE = 'Ordinary-procedure files with no recorded procedural update for a year or more.';

type HomeList = HomeData['lists'][number];

/** The "Stalled" list on the reader's date: the Legislative Train's reports dated by our copy of it while that is
 * current, and left out once it has expired (src/lib/freshness.ts), as on the files' pages and in the explorer. */
function stalledOn(l: HomeList, train: Classifications | null): HomeList {
  const blocked = l.items.filter((it) => it.badge === BLOCKED_BADGE);
  if (!blocked.length) return l;
  if (train?.current) return { ...l, description: `${l.description ?? ''} ${asRetrieved(train)}.`.trim() };
  const inactive = THEN_INACTIVE.exec(l.description ?? '');
  const rest = inactive ? `O${inactive[1]}` : INACTIVE;
  return {
    ...l,
    items: l.items.filter((it) => it.badge !== BLOCKED_BADGE),
    description: train
      ? `${rest} The files Parliament’s Legislative Train reports as blocked are not listed: ${expiredReason(train)}.`
      : rest,
  };
}

const EXAMPLES = ['AI Act', 'Migration', 'GDPR', 'Spain', 'EPP', 'Agriculture', 'Digital markets', 'Climate'];

export default function Home() {
  useDocumentTitle(null);
  const homeFile = useData<HomeData>('home.json');
  // the latest changes (activity.json) open the page: its sections are shown once both files have been read (or the
  // changes could not be), so that the strip does not push them down when it arrives
  const activity = useData<ActivityItem[]>('activity.json');
  const home = homeFile.data && activity.loading ? { data: undefined, error: undefined, loading: true } : homeFile;
  const meta = useData<Meta>('meta.json');
  // home.json carries topics; fall back to topics.json if it ever comes without them.
  const needTopics = !!home.data && !home.data.topics?.length;
  const topicsFallback = useData<Topic[]>(needTopics ? 'topics.json' : null);
  const topics = home.data?.topics?.length ? home.data.topics : (topicsFallback.data ?? []);
  const topicLabel = (slug: string) => topics.find((t) => t.slug === slug)?.label ?? slug;

  // "Coming up" and the scheduled steps were computed when the data was built: dates that have passed since are left
  // out (a deadline and a planned step only once their day is over); the days since a stalled file's last recorded step
  // are counted on the visitor's date
  const today = todayISO();
  // the Legislative Train's "blocked" reports are shown as current only while our copy of it is (src/lib/freshness.ts)
  const train = classifications(meta.data, Date.now());
  const lists = (home.data?.lists ?? []).map((l) =>
    l.id === 'upcoming' || l.id === 'scheduled'
      ? { ...l, items: stillAhead(l.items, today) }
      : l.id === 'stalled'
        ? stalledOn(
            {
              ...l,
              items: l.items.map((it) => {
                const n = it.subtitle && NO_UPDATE.exec(it.subtitle);
                return n ? { ...it, subtitle: noUpdateText(Number(n[1]), it.date, today) } : it;
              }),
            },
            train,
          )
        : l,
  );
  const featured = home.data?.featured ?? [];

  return (
    <div className="home">
      <section className="home-hero" aria-labelledby="hero-title">
        <div className="container">
          <h1 id="hero-title" className="home-hero__title">
            European legislation, made clear.
          </h1>
          <p className="home-hero__lead">
            What the EU is deciding, where a law stands, who voted for it and what happens next — in plain
            language, with every fact linked to the official record.
          </p>
          <p className="home-hero__independent">
            An independent, nonpartisan project — not an official EU website. <Link to="/about">About this site</Link>
          </p>
          <div className="home-hero__search">
            <SearchBox placeholder={PAGE_PLACEHOLDERS} />
          </div>
          <div className="home-hero__examples">
            <span className="home-hero__try" id="try-label">
              Try
            </span>
            <ul aria-labelledby="try-label">
              {EXAMPLES.map((q) => (
                <li key={q}>
                  <Link className="lx-chip" to={`/search?q=${encodeURIComponent(q)}`}>
                    {q}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <p className="home-hero__guide">
            New to the EU? <Link to="/how-the-eu-works">How EU laws are made</Link>
          </p>
          <Freshness meta={meta.data} />
        </div>
      </section>

      <div className="container">
        {home.loading && <Loading label="Loading the latest legislative data…" />}
        {home.error && <ErrorState error={home.error} title="The legislative data could not be loaded" />}
        {/* what the latest refresh recorded, first: activity.json, read on the reader's date */}
        {home.data && <ThisWeek items={activity.data} />}

        {featured.length > 0 && (
          <section className="section home__featured" aria-labelledby="featured-title">
            <div className="lx-head">
              <div>
                <p className="lx-kicker">Editorial selection</p>
                <h2 id="featured-title">Selected major legislation</h2>
              </div>
              <p className="lx-head__note">
                Chosen by our editors for public interest, not ranked.{' '}
                <Link to="/about#selection">How we select</Link>. Status and dates come from official records.
              </p>
            </div>
            <div className={`fcards${featured.length % 3 === 0 ? ' fcards--3' : ''}`}>
              {featured.slice(0, 6).map((f) => (
                <FeaturedCard key={f.dossier.id} item={f} topicLabel={topicLabel} blockedShown={!!train?.current} />
              ))}
            </div>
          </section>
        )}

        {topics.length > 0 && (
          <section className="section" aria-labelledby="topics-title">
            <div className="lx-head">
              <div>
                <h2 id="topics-title">Explore by topic</h2>
              </div>
              <p className="lx-head__note">
                Each topic page is a shareable, filterable list. Topics follow Parliament’s subject codes
                {meta.data?.scope?.dossiers_without_topic ? (
                  <>
                    ; <Link to="/legislation?topic=none">{formatNumber(meta.data.scope.dossiers_without_topic)} files</Link> fall
                    outside the ten topics
                  </>
                ) : null}
                . <Link to="/about#methodology">How topics are assigned</Link>.
              </p>
            </div>
            <TopicGrid topics={topics} />
          </section>
        )}

        {lists.length > 0 && (
          <section className="section" aria-labelledby="lists-title">
            <div className="lx-head">
              <div>
                <p className="lx-kicker">From the official records</p>
                <h2 id="lists-title">What’s moving</h2>
              </div>
              <p className="lx-head__note">
                Generated automatically from Parliament, Council and EUR-Lex data.{' '}
                <Link to="/about#selection">How these lists are built</Link>.
              </p>
            </div>
            {/* "Stalled" leads to the stuck view, which does not depend on the Legislative Train's copy */}
            <HomeLists lists={lists} />
          </section>
        )}

        <section className="section home__guide" aria-labelledby="guide-title">
          <h2 id="guide-title">New to how EU laws are made?</h2>
          <p>
            The European Commission proposes, the European Parliament and the Council of the EU amend and decide, and
            Member States apply the result. Our short guide explains each step and the words you’ll meet on this site.
          </p>
          <Link to="/how-the-eu-works" className="btn">
            Read the guide (about 14 minutes)
          </Link>
        </section>
      </div>
    </div>
  );
}

/** The date up to which statuses, votes and acts are current, and the sources not up to date on the reader's date. */
function Freshness({ meta }: { meta: Meta | undefined }) {
  if (!meta) return null;
  const c = meta.counts;
  const fromYear = meta.scope?.procedures_from_year;
  const since = votesSince(meta.scope);
  const f = freshness(meta, Date.now());
  return (
    <>
      <p className="home-hero__fresh">
        <span className={`home-hero__fresh-dot${f.coreStale ? ' is-stale' : ''}`} aria-hidden="true" />
        {f.coreAt ? <>Procedures, votes and acts current to {formatDate(f.coreAt)}</> : <>Data built {formatDate(meta.built_at)}</>}
        {c?.dossiers ? (
          <>
            {' '}
            · {formatNumber(c.dossiers)} legislative files
            {fromYear ? <> (proposed from {fromYear}, or adopted since {fromYear})</> : null}
          </>
        ) : null}
        {c?.ep_votes ? <> · {formatNumber(c.ep_votes)} Parliament votes{since ? <> since {since}</> : null}</> : null} ·{' '}
        <Link to="/about#coverage">What’s covered</Link>
      </p>
      {f.stale.length > 0 && (
        <p className="meta home-hero__stale">
          <Link to="/about#sources">{staleNote(f)}</Link>
        </p>
      )}
    </>
  );
}
