/**
 * Illustrative path of a law under the ordinary legislative procedure. Plain HTML ordered list,
 * styled as a diagram, so it reads correctly with any assistive technology.
 */
import './guide.css';

export const STEPS: { title: string; who: string; text: string }[] = [
  {
    title: 'Commission proposes',
    who: 'European Commission',
    text: 'Drafts a proposal for a regulation, directive or decision and sends it to Parliament and the Council.',
  },
  {
    title: 'Parliament & Council examine and negotiate',
    who: 'European Parliament · Council of the EU',
    text: 'Each sets its position and proposes changes; they usually negotiate a compromise text.',
  },
  {
    title: 'Formal adoption',
    who: 'European Parliament · Council of the EU',
    text: 'Both institutions adopt the same text. If either does not, the proposal does not become law.',
  },
  {
    title: 'Signature & publication',
    who: 'Presidents of Parliament and Council · Official Journal',
    text: 'The act is signed and published in the Official Journal. Entry into force is a separate step.',
  },
  {
    title: 'Entry into force & application',
    who: 'Dates set in the act',
    text: 'It enters into force on the date it specifies or, if it specifies none, on the twentieth day after publication. Its rules may apply later, sometimes in phases.',
  },
  {
    title: 'Implementation & enforcement',
    who: 'Member States · Commission · courts',
    text: 'Countries apply it (and transpose directives); the Commission monitors and can open infringement cases.',
  },
];

export function PathwayDiagram() {
  return (
    <figure className="pathway">
      <ol className="pathway__steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="pathway__step">
            <span className="pathway__n" aria-hidden="true">
              {i + 1}
            </span>
            <span className="pathway__title">{s.title}</span>
            <span className="pathway__who">{s.who}</span>
            <span className="pathway__text">{s.text}</span>
          </li>
        ))}
      </ol>
      <figcaption className="pathway__caption">
        Illustrative path of a law under the ordinary legislative procedure. Real files can go through several readings, pause for long
        periods, or end without becoming law (withdrawn by the Commission or rejected).
      </figcaption>
    </figure>
  );
}
