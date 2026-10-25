import { Link } from 'react-router-dom';
import { ExtLink, PageHeader } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import '../features/guide/guide.css';
import '../features/votes/common.css';

const GITHUB_PRIVACY = 'https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement';
/** The project's issue tracker (About.tsx REPOSITORY), where errors are reported and questions asked. */
const ISSUES = 'https://github.com/RAHV-FB/eu-intel/issues';

export default function Privacy() {
  useDocumentTitle('Privacy');
  return (
    <div className="container page">
      <PageHeader
        eyebrow="Privacy"
        title="Privacy notice"
        lead="This site is designed to work without collecting information about you. Here is exactly what happens when you use it."
      />
      <div className="prose">
        <section aria-labelledby="short-h">
          <h2 id="short-h">In short</h2>
          <ul>
            <li>
              <strong>No analytics, no tracking, no cookies.</strong> We do not measure visits, build profiles or use advertising.
            </li>
            <li>
              <strong>No third-party content.</strong> No external fonts, scripts, embeds or social-media widgets are loaded. Every file the
              site needs comes from the same website.
            </li>
            <li>
              <strong>Your browser does the work.</strong> Search and filters run in your browser, and the site does not send what you
              type anywhere. The search terms and filters you use are part of the page address, though, so they appear in your
              browser history and in any link you share. GitHub, the host, receives that address when a page is loaded from it; no
              other third party does (see “Hosting”).
            </li>
            <li>
              <strong>“Follow” stays on your device.</strong> If you choose to follow a legislative file, the list is stored only in your
              browser.
            </li>
          </ul>
        </section>

        <section aria-labelledby="hosting-h">
          <h2 id="hosting-h">Hosting</h2>
          <p>
            The site is a set of static files hosted on GitHub Pages, a service of GitHub, Inc. As with any website, your browser has to
            connect to the hosting servers to load pages. GitHub may process technical connection data — such as your IP address, the
            pages requested (the full address, including any search terms or filters in it) and your browser’s user agent — for example
            in server logs, to deliver the site and keep the service secure. We do not receive or use this data. GitHub’s processing is
            described in the <ExtLink href={GITHUB_PRIVACY} official={false}>
              GitHub General Privacy Statement
            </ExtLink>.
          </p>
          <p>
            The same applies if you subscribe to one of our Atom feeds: your feed reader fetches the feed file from GitHub Pages.
          </p>
          <p>
            Search terms and filters are written into the page address (for example <span className="mono">/search?q=climate</span>) so
            that the Back button works and a link can be shared. Your browser keeps that address in its history, like any other. GitHub
            receives it whenever the page is loaded from it: when you reload, open a bookmark or restore a tab, or when someone opens a
            link you shared. No other third party receives it, and our external links are set not to pass on the address of the page
            you came from.
          </p>
        </section>

        <section aria-labelledby="follow-h">
          <h2 id="follow-h">The “Follow” feature and browser storage</h2>
          <p>
            Nothing is kept in your browser until you click <strong>Follow</strong> on a legislative file. When you do, the site uses your
            browser’s local storage to remember:
          </p>
          <ul>
            <li>the identifiers of the files you follow (for example the procedure number of a proposal);</li>
            <li>when you followed each file and when you last viewed it;</li>
            <li>the status you last saw for each file, so the site can show you what has changed since.</li>
          </ul>
          <p>
            This information never leaves your device: it is not sent to us or to anyone else, and it is not a cookie. You can remove
            individual files or clear the whole list on the <Link to="/following">Following</Link> page, or by clearing this site’s data
            in your browser settings. If your browser blocks storage, the feature simply does not save anything.
          </p>
          <p>
            The share link on the Following page is the exception, and only when you copy and send it: the identifiers of the files you
            follow are then part of that link’s address, with the same consequences as for search terms (see “Hosting”).
          </p>
        </section>

        <section aria-labelledby="data-h">
          <h2 id="data-h">Information about public officials</h2>
          <p>
            The site shows official, publicly available information about Members of the European Parliament acting in their public role:
            their political group and national party memberships, committee roles and recorded votes, as published by the European
            Parliament. We do not publish biographies, photos or contact details, and we link to each MEP’s official profile for anything
            else.
          </p>
        </section>

        <section aria-labelledby="links-h">
          <h2 id="links-h">Links to other websites</h2>
          <p>
            The site links to official EU websites (such as those of the European Parliament, the Council, the Commission and EUR-Lex) and
            occasionally to other sites. Those websites have their own privacy policies and may use cookies or analytics; please check them
            when you visit. Our external links open in a new tab and are set not to send the address of the page you came from.
          </p>
        </section>

        <section aria-labelledby="who-h">
          <h2 id="who-h">Who “we” are</h2>
          <p>
            “We” on this page means the site’s maintainer, RAHV-FB (see <Link to="/about#contact">who maintains the site</Link>).
            Questions about this notice can be asked in the project’s{' '}
            <ExtLink href={ISSUES} official={false}>issue tracker on GitHub</ExtLink>; issues there are public.
          </p>
        </section>

        <section aria-labelledby="changes-h">
          <h2 id="changes-h">Changes to this notice</h2>
          <p>
            If the site’s handling of information changes, this page will be updated before the change takes effect. See also{' '}
            <Link to="/about">About this project</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}
