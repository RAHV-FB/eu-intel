import { Link } from 'react-router-dom';
import type { HomeData, Meta, Topic } from '../types/data';
import { useData } from '../lib/data';
import { formatDateTime, formatNumber, noUpdateText, stillAhead } from '../lib/format';
import { votesSince } from '../lib/scope';
import { PAGE_PLACEHOLDERS, SearchBox } from '../components/SearchBox';
import { ErrorState, Loading } from '../components/ui';
import { FeaturedCard } from '../features/home/FeaturedCard';
import { HomeLists } from '../features/home/HomeLists';
import { TopicGrid } from '../features/home/TopicGrid';
import { useDocumentTitle } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import '../features/legislation/common.css';
import '../features/home/home.css';

// a "Stalled" file's subtitle, counted on the day the data was built (pipeline/build.py build_home)
const NO_UPDATE = /^No recorded procedural update in (\d+) days?$/;

const EXAMPLES = ['AI Act', 'Migration', 'GDPR', 'Spain', 'EPP', 'Agriculture', 'Digital markets', 'Climate'];

export default function Home() {
  useDocumentTitle(null);
  const home = useData<HomeData>('home.json');
  const meta = useData<Meta>('meta.json');
  // home.json carries topics; fall back to topics.json if it ever comes without them.
  const needTopics = !!home.data && !home.data.topics?.length;
  const topicsFallback = useData<Topic[]>(needTopics ? 'topics.json' : null);
  const topics = home.data?.topics?.length ? home.data.topics : (topicsFallback.data ?? []);
  const topicLabel = (slug: string) => topics.find((t) => t.slug === slug)?.label ?? slug;

  // "Coming up" was computed when the data was built: dates that have passed since are left out; the days since a
  // stalled file's last recorded step are counted on the visitor's date
  const today = todayISO();
  const lists = (home.data?.lists ?? []).map((l) =>
    l.id === 'upcoming'
      ? { ...l, items: stillAhead(l.items, today) }
      : l.id === 'stalled'
        ? {
            ...l,
            items: l.items.map((it) => {
              const n = it.subtitle && NO_UPDATE.exec(it.subtitle);
              return n ? { ...it, subtitle: noUpdateText(Number(n[1]), it.date, today) } : it;
            }),
          }
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
                <FeaturedCard key={f.dossier.id} item={f} topicLabel={topicLabel} />
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
            Read the guide (about 12 minutes)
          </Link>
        </section>
      </div>
    </div>
  );
}

function Freshness({ meta }: { meta: Meta | undefined }) {
  if (!meta) return null;
  const c = meta.counts;
  const fromYear = meta.scope?.procedures_from_year;
  const since = votesSince(meta.scope);
  return (
    <p className="home-hero__fresh">
      <span className="home-hero__fresh-dot" aria-hidden="true" />
      Data refreshed {formatDateTime(meta.snapshot_at ?? meta.built_at)}
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
  );
}
