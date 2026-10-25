import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ExtLink, PageHeader, StatusBadge, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { PathwayDiagram } from '../features/guide/PathwayDiagram';
import { STATUS_LABEL_GROUPS } from '../features/guide/statusLabels';
import { useHashScroll } from '../features/guide/useHashScroll';
import '../features/guide/guide.css';
import '../features/votes/common.css';

const TOC: { group: string; items: { id: string; label: string }[] }[] = [
  {
    group: 'Who does what',
    items: [
      { id: 'commission', label: 'European Commission' },
      { id: 'parliament', label: 'European Parliament' },
      { id: 'council', label: 'Council of the EU' },
      { id: 'european-council', label: 'European Council' },
      { id: 'cjeu', label: 'Court of Justice of the EU' },
    ],
  },
  {
    group: 'How laws are made',
    items: [
      { id: 'olp', label: 'Ordinary legislative procedure' },
      { id: 'special', label: 'Special legislative procedures' },
      { id: 'status-labels', label: 'Status labels on this site' },
      { id: 'parliament-voting', label: 'How Parliament votes' },
      { id: 'council-voting', label: 'How the Council votes' },
    ],
  },
  {
    group: 'After adoption',
    items: [
      { id: 'instruments', label: 'Regulations, directives, decisions' },
      { id: 'implementation', label: 'Transposition & implementation' },
      { id: 'infringements', label: 'Infringement procedure' },
    ],
  },
];

function Section({ id, kicker, title, official, children }: { id: string; kicker?: string; title: string; official?: { href: string; label: string }[]; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`}>
      {kicker && <p className="kicker">{kicker}</p>}
      <h2 id={`${id}-h`}>{title}</h2>
      {children}
      {official && official.length > 0 && (
        <p className="official">
          Official explanation:{' '}
          {official.map((o, i) => (
            <span key={o.href}>
              {i > 0 && ' · '}
              <ExtLink href={o.href}>{o.label}</ExtLink>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

export default function HowEuWorks() {
  useDocumentTitle('How the EU works');
  useHashScroll();

  return (
    <div className="container page">
      <PageHeader
        eyebrow="Explainer"
        title="How the EU works"
        lead="A short guide to who proposes, negotiates, adopts and enforces EU laws — and what the terms used on this site mean. Each section links to the institutions’ own explanations."
      />

      <div className="guide">
        <nav className="toc" aria-label="On this page">
          <p className="toc__title">On this page</p>
          <ol>
            {TOC.map((g) => (
              <li key={g.group}>
                <span className="toc__group">{g.group}</span>
                <ol>
                  {g.items.map((i) => (
                    <li key={i.id}>
                      <a href={`#${i.id}`}>{i.label}</a>
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ol>
        </nav>

        <div className="prose">
          {/* ------------------------------------------------------------ institutions */}
          <Section
            id="commission"
            kicker="Who does what"
            title="European Commission"
            official={[{ href: 'https://commission.europa.eu/about_en', label: 'About the European Commission' }]}
          >
            <p>
              The Commission is the EU’s executive. It is a college of 27 Commissioners — one from each Member State — led by a President.
              Commissioners are not national representatives: they are bound to act independently, in the interest of the EU as a whole.
            </p>
            <ul>
              <li>
                <strong>Proposes laws.</strong> Almost all EU legislation starts as a Commission proposal; under the treaties, most EU laws
                can only be adopted on the basis of one. The Commission can also withdraw a proposal.
              </li>
              <li>
                <strong>Manages and implements</strong> EU policies and the budget, and adopts detailed implementing rules where laws allow.
              </li>
              <li>
                <strong>Enforces EU law.</strong> It checks that Member States apply EU law and can open{' '}
                <a href="#infringements">infringement procedures</a>.
              </li>
            </ul>
            <p>
              The European Council proposes a candidate for Commission President, whom Parliament elects; Parliament then approves the
              whole College of Commissioners.
            </p>
          </Section>

          <Section
            id="parliament"
            title="European Parliament"
            official={[{ href: 'https://www.europarl.europa.eu/about-parliament/en', label: 'About Parliament' }]}
          >
            <p>
              The only directly elected EU institution. Its members (MEPs) are elected in each Member State every five years; 720 MEPs were
              elected in June 2024. Each country has a fixed number of seats, from 6 (Cyprus, Luxembourg, Malta) to 96 (Germany).
            </p>
            <ul>
              <li>
                <strong>Makes laws with the Council.</strong> Under the <a href="#olp">ordinary legislative procedure</a> Parliament
                amends and adopts laws on an equal footing with the Council of the EU.
              </li>
              <li>
                <strong>Shares budget powers</strong> with the Council and approves how the budget was spent.
              </li>
              <li>
                <strong>Oversees the Commission</strong>: it elects the Commission President, approves the College, and can dismiss it by a
                motion of censure.
              </li>
            </ul>
            <p>
              MEPs sit in <Term id="political-group">political groups</Term> by political affiliation, not by nationality. A group needs at
              least 23 MEPs elected in at least seven Member States; MEPs who join no group are “non-attached”. Each MEP still votes
              individually. Detailed work happens in specialised committees, which prepare reports for the full Parliament (the plenary).
              See <Link to="/people">People &amp; Parties</Link>.
            </p>
          </Section>

          <Section
            id="council"
            title="Council of the European Union"
            official={[{ href: 'https://www.consilium.europa.eu/en/council-eu/', label: 'Council of the EU' }]}
          >
            <p>
              Government ministers from each Member State, meeting in different configurations depending on the subject — for example
              agriculture ministers, or finance ministers. Each minister can commit their government. The presidency of the Council
              rotates between Member States every six months, except in the Foreign Affairs Council, which the EU’s High Representative
              chairs.
            </p>
            <ul>
              <li>
                <strong>Negotiates and adopts EU laws</strong> together with Parliament, and in some areas alone after consulting Parliament
                or with its consent.
              </li>
              <li>
                <strong>Coordinates</strong> Member States’ policies, adopts the EU budget with Parliament, and develops the common foreign
                and security policy.
              </li>
            </ul>
            <p>
              A Council vote records each <strong>government’s</strong> position. This is different from how MEPs elected in that country
              voted in Parliament. See <a href="#council-voting">how the Council votes</a>.
            </p>
          </Section>

          <Section
            id="european-council"
            title="European Council"
            official={[{ href: 'https://www.consilium.europa.eu/en/european-council/', label: 'European Council' }]}
          >
            <p>
              The heads of state or government of the 27 Member States, together with its own President and the President of the
              Commission. It meets in summits several times a year to set the EU’s overall political direction and priorities, and usually
              decides by consensus.
            </p>
            <p>
              <strong>It does not adopt laws.</strong> The treaties state that it does not exercise legislative functions: it can ask the
              Commission to make proposals, but laws are adopted by Parliament and the Council of the EU.
            </p>
            <div className="not-same">
              <strong>Three different “councils”.</strong> The <em>European Council</em> (leaders’ summits) and the{' '}
              <em>Council of the EU</em> (ministers, co-legislator) are both EU institutions. The <em>Council of Europe</em> is a separate
              international organisation, not part of the EU, best known for the European Convention on Human Rights.
            </div>
          </Section>

          <Section
            id="cjeu"
            title="Court of Justice of the European Union"
            official={[{ href: 'https://curia.europa.eu/jcms/jcms/j_6/en/', label: 'Court of Justice of the EU' }]}
          >
            <p>
              Based in Luxembourg, the Court of Justice of the EU (CJEU) is made up of the <strong>Court of Justice</strong> and the{' '}
              <strong>General Court</strong>. It interprets EU law so that it is applied the same way in every Member State. Among other
              things it:
            </p>
            <ul>
              <li>answers questions from national courts about how EU law should be interpreted (preliminary rulings);</li>
              <li>rules on cases the Commission brings against Member States for failing to meet their obligations (infringements);</li>
              <li>can annul EU acts that breach the treaties or fundamental rights.</li>
            </ul>
            <p>Only the Court can rule that a Member State has failed to fulfil its obligations under EU law.</p>
          </Section>

          {/* ------------------------------------------------------------ procedures */}
          <Section
            id="olp"
            kicker="How laws are made"
            title="The ordinary legislative procedure"
            official={[
              { href: 'https://www.europarl.europa.eu/olp/en/ordinary-legislative-procedure/overview', label: 'European Parliament' },
              { href: 'https://www.consilium.europa.eu/en/council-eu/decision-making/ordinary-legislative-procedure/', label: 'Council of the EU' },
            ]}
          >
            <p>
              Most EU laws are made this way (Article 294 of the Treaty on the Functioning of the EU). Parliament and the Council are equal
              co-legislators: a law is adopted only if both agree on the same text. Procedure references for these files end in{' '}
              <span className="mono">(COD)</span>, for example <span className="mono">2021/0106(COD)</span>.
            </p>
            <PathwayDiagram />
            <h3>The readings</h3>
            <ol>
              <li>
                <strong>First reading.</strong> Parliament adopts its position, usually with amendments. If the Council approves
                Parliament’s position, the act is adopted. Otherwise the Council adopts its own first-reading position.
              </li>
              <li>
                <strong>Second reading.</strong> Within three months, extendable by up to a month, Parliament can approve the Council’s
                position or take no decision (the act is adopted), reject it by a majority of all its members (the procedure ends), or
                amend it by that majority. If the Council approves all the amendments within the same time limits, the act is adopted; if
                not, conciliation follows.
              </li>
              <li>
                <strong>Conciliation and third reading.</strong> If they still disagree, a committee with equal numbers from both tries to
                agree a joint text, which both must then approve. If not, the act is not adopted.
              </li>
            </ol>
            <p>
              In practice, most files are agreed at first reading after informal{' '}
              <Term id="trilogue">interinstitutional negotiations</Term> (“trilogues”) between Parliament, the Council and the Commission.
              The resulting <Term id="provisional-agreement">provisional agreement</Term> is not yet law: both institutions must still
              formally adopt it.
            </p>
            <p>
              Once adopted, the act is signed by the Presidents of Parliament and the Council and published in the{' '}
              <em>Official Journal of the EU</em> (Article 297(1) TFEU). Adoption, signature and publication are separate steps from
              entry into force: the act enters into force on the date it specifies or, if it specifies none, on the twentieth day after
              publication. Its rules may apply from a later date.
            </p>
          </Section>

          <Section
            id="special"
            title="Special legislative procedures"
            official={[
              { href: 'https://eur-lex.europa.eu/EN/legal-content/glossary/special-legislative-procedure.html', label: 'EUR-Lex glossary' },
            ]}
          >
            <p>In some areas the treaties set a different procedure, in which the Council usually acts as the main legislator:</p>
            <ul>
              <li>
                <strong>Consultation</strong> — the Council adopts the act after receiving Parliament’s opinion, which is not binding. Used
                for example for taxation. Procedure references end in <span className="mono">(CNS)</span>.
              </li>
              <li>
                <strong>Consent</strong> — Parliament can approve or reject, but not amend. Used for example for the EU’s long-term budget
                (multiannual financial framework), new Member States joining, and many international agreements. References for legislative
                consent files end in <span className="mono">(APP)</span>.
              </li>
            </ul>
            <p>
              In these areas the Council often has to decide by <Term id="unanimity">unanimity</Term>. In a few cases Parliament adopts an
              act itself with the Council’s consent, for example on the rules governing MEPs’ duties.
            </p>
          </Section>

          <Section id="status-labels" title="Status labels on this site">
            <p>
              A file’s label says how far its procedure has come, worked out from the steps recorded by Parliament and EUR-Lex (see{' '}
              <Link to="/about#methodology">how status is worked out</Link>). An act is usually adopted, signed and published before it
              enters into force and, from the date it sets, applies; the labels are grouped by which of these steps it has reached. Labels
              of other steps before adoption, such as “Committee report adopted”, mean that the act has not been adopted yet.
            </p>
            {STATUS_LABEL_GROUPS.map((g) => (
              <div key={g.id} className="statuslabels">
                <h3>{g.heading}</h3>
                <dl>
                  {g.rows.map((r) => (
                    <div key={r.labels[0].label} className="statuslabels__row">
                      <dt>
                        {r.labels.map((x) => (
                          <StatusBadge key={x.label} stage={x.stage} label={x.label} />
                        ))}
                      </dt>
                      <dd>
                        {r.text}
                        {r.also && <span className="statuslabels__also"> Also shown as: {r.also.map((x) => `“${x.label}”`).join(', ')}.</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
            <p>
              “Officially reported as blocked” beside a label is the classification of Parliament’s Legislative Train Schedule, not a
              stage. See where every file stands in <Link to="/legislation">the legislation explorer</Link>.
            </p>
          </Section>

          <Section
            id="parliament-voting"
            title="How Parliament votes"
            official={[
              { href: 'https://www.europarl.europa.eu/doceo/document/RULES-10-2024-07-16-TOC_EN.html', label: 'Parliament’s Rules of Procedure' },
            ]}
          >
            <p>Votes take place in plenary sessions. Different decisions need different majorities:</p>
            <div className="thresholds">
              <div className="threshold">
                <span className="threshold__n">Votes cast</span>
                <span className="threshold__l">
                  Most votes: more MEPs in favour than against. Abstentions are not counted towards the majority.
                </span>
              </div>
              <div className="threshold">
                <span className="threshold__n">Majority of all members</span>
                <span className="threshold__l">
                  More than half of all MEPs in office (360 when 719 of the 720 seats are filled), whoever is present — needed for example
                  to reject or amend the Council’s position at second reading, or to elect the Commission President.
                </span>
              </div>
              <div className="threshold">
                <span className="threshold__n">Two thirds</span>
                <span className="threshold__l">
                  Of the votes cast, representing a majority of all members — needed to pass a motion of censure on the Commission.
                </span>
              </div>
            </div>
            <ul>
              <li>
                <strong>Amendments come first.</strong> On a report, Parliament usually votes on amendments and separate parts before the
                final vote on the whole text. <strong>A rejected amendment does not mean the law was rejected.</strong>
              </li>
              <li>
                <strong>Roll-call votes</strong> record each MEP’s vote by name. Final votes on legislative proposals are taken by{' '}
                <Term id="roll-call">roll call</Term>, and a political group or a minimum number of MEPs can request one on other votes.
                For votes by show of hands only the result is recorded; for other electronic votes, only the totals.
              </li>
              <li>
                <strong>Corrections.</strong> After a vote, MEPs can state that they intended to vote differently. These corrections are
                published but do not change the result.
              </li>
              <li>
                <strong>Not voting is not abstaining.</strong> An abstention is a recorded choice; an MEP who was absent or did not vote has
                no recorded position.
              </li>
            </ul>
            <p>
              Parliament’s vote alone does not make a law: under the ordinary procedure the Council must agree too. See{' '}
              <Link to="/votes">Votes</Link>.
            </p>
          </Section>

          <Section
            id="council-voting"
            title="How the Council votes"
            official={[
              { href: 'https://www.consilium.europa.eu/en/council-eu/voting-system/', label: 'Council voting system' },
              { href: 'https://www.consilium.europa.eu/en/council-eu/voting-system/qualified-majority/', label: 'Qualified majority' },
            ]}
          >
            <p>
              The voting rule depends on the subject and is set by the treaties. Most legislation is adopted by{' '}
              <Term id="qmv">qualified majority</Term>.
            </p>
            <div className="thresholds">
              <div className="threshold">
                <span className="threshold__n">55%</span>
                <span className="threshold__l">of Member States in favour — in practice 15 of 27</span>
              </div>
              <div className="threshold">
                <span className="threshold__n">65%</span>
                <span className="threshold__l">of the EU population represented by those in favour</span>
              </div>
              <div className="threshold">
                <span className="threshold__n">≥ 4 states</span>
                <span className="threshold__l">
                  needed for a blocking minority: more than 35% of the population, or 13 states whatever their population
                </span>
              </div>
            </div>
            <ul>
              <li>
                <strong>Qualified majority:</strong> both thresholds must be met. Because a blocking minority needs at least four Member
                States, <strong>a single country’s vote cannot block a qualified-majority decision</strong>, however large the country.
                Under this rule an abstention has the same effect as a vote against. When the Council acts without a proposal from the
                Commission or the High Representative, a higher threshold applies (72% of Member States).
              </li>
              <li>
                <strong>Unanimity:</strong> required in sensitive areas such as taxation, foreign and security policy, EU membership and the
                long-term budget. Any one Member State voting against blocks the decision — this is what is often called a “veto”. An
                abstention does not prevent adoption.
              </li>
              <li>
                <strong>Exceptions.</strong> Outside unanimity, one government can halt a decision in a few cases: in foreign and security
                policy it can stop a qualified-majority vote for vital and stated reasons of national policy (Article 31(2) TEU), and on
                some social-security and criminal-justice laws it can have the draft referred to the European Council, which suspends the
                procedure (the “emergency brake”, Articles 48, 82(3) and 83(3) TFEU).
              </li>
              <li>
                <strong>Simple majority</strong> (14 Member States) is used mainly for procedural decisions.
              </li>
            </ul>
            <p>
              Where some Member States do not take part in a measure (for example because of an opt-out), the thresholds are calculated
              among those taking part. Council votes on legislation are public.
            </p>
          </Section>

          {/* ------------------------------------------------------------ after adoption */}
          <Section
            id="instruments"
            kicker="After adoption"
            title="Regulations, directives and decisions"
            official={[{ href: 'https://commission.europa.eu/law/law-making-process/types-eu-law_en', label: 'Types of EU law' }]}
          >
            <div className="compare">
              <div>
                <h3>
                  <Term id="regulation">Regulation</Term>
                </h3>
                <p>Binding in full and directly applicable in every Member State, without national law needed to bring it into effect.</p>
              </div>
              <div>
                <h3>
                  <Term id="directive">Directive</Term>
                </h3>
                <p>
                  Sets a result that Member States must achieve, leaving them to choose how. Each country must adopt national measures by a
                  deadline (<a href="#implementation">transposition</a>).
                </p>
              </div>
              <div>
                <h3>Decision</h3>
                <p>Binding in full on those it is addressed to (for example a Member State or a company), or generally if it names none.</p>
              </div>
            </div>
            <p>
              <strong>Recommendations and opinions</strong> have no binding force. An act’s <Term id="entry-into-force">entry into force</Term>{' '}
              is the date it becomes part of the legal order; the date from which its rules <em>apply</em> can be later, and different
              provisions can apply at different dates.
            </p>
          </Section>

          <Section
            id="implementation"
            title="Transposition and implementation"
            official={[{ href: 'https://commission.europa.eu/law/application-eu-law_en', label: 'Application of EU law' }]}
          >
            <p>
              EU law is applied day to day by national authorities and enforced by national courts. For a{' '}
              <Term id="directive">directive</Term>, each Member State must first <Term id="transposition">transpose</Term> it: adopt or
              adapt national laws by the deadline, and notify the Commission of the measures it has taken. EUR-Lex publishes the national
              measures that countries notify.
            </p>
            <ul>
              <li>
                A notified measure shows that a country reported something — <strong>not</strong> that transposition is complete or correct.
                The Commission checks completeness and conformity separately.
              </li>
              <li>
                Finding no notified measure in a dataset is not, on its own, proof that a country is failing to comply: some directives do
                not require new measures from every country, and datasets can be incomplete or delayed.
              </li>
            </ul>
            <p>
              See the implementation section of each <Link to="/countries">country page</Link>.
            </p>
          </Section>

          <Section
            id="infringements"
            title="The infringement procedure"
            official={[
              {
                href: 'https://commission.europa.eu/law/application-eu-law/implementing-eu-law/infringement-procedure_en',
                label: 'Infringement procedure',
              },
            ]}
          >
            <p>
              If the Commission considers that a Member State is not applying EU law — for example because it has not notified measures
              transposing a directive on time — it can open a formal <Term id="infringement">infringement procedure</Term> (Article 258 of
              the Treaty on the Functioning of the EU). It often first tries to resolve the problem through dialogue. The formal stages are:
            </p>
            <ol className="stages">
              <li>
                <span>
                  <strong>Letter of formal notice</strong>
                  The Commission asks the Member State for information; it has a set period (usually two months) to reply.
                </span>
              </li>
              <li>
                <span>
                  <strong>Reasoned opinion</strong>
                  A formal request to comply, explaining why the Commission considers EU law is being breached.
                </span>
              </li>
              <li>
                <span>
                  <strong>Referral to the Court of Justice</strong>
                  If the country still does not comply, the Commission can take the case to the Court. For failures to notify transposition
                  measures, it can already ask the Court to impose financial penalties (Article 260(3)).
                </span>
              </li>
              <li>
                <span>
                  <strong>Judgment and follow-up</strong>
                  If the Court finds a breach, the country must comply. If it does not, the Commission can refer the case again and ask for
                  financial penalties (Article 260(2)).
                </span>
              </li>
            </ol>
            <p>
              <strong>An open infringement case is not a court ruling.</strong> Most cases are closed before reaching the Court, often
              because the country resolves the issue. Case stages on this site are shown exactly as the Commission publishes them.
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
