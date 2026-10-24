import { Fragment } from 'react';
import type { EpVoteTitle, LangRun } from '../../types/data';

/** Text whose runs in another language (Parliament's French or German wording) carry their own `lang`. */
export function LangText({ text, parts }: { text: string; parts?: LangRun[] | null }) {
  if (!parts || parts.map((p) => p[1]).join('') !== text) return <>{text}</>;
  return (
    <>
      {parts.map(([lang, t], i) =>
        lang ? (
          <span key={i} lang={lang}>
            {t}
          </span>
        ) : (
          <Fragment key={i}>{t}</Fragment>
        ),
      )}
    </>
  );
}

/** What tells a vote apart in a list whose titles are cut short on phones (`.table--clamp`): the kind of vote, its
 * procedure reference and the distinction appended to its title, on a line that is never clamped. */
export function VoteRowMeta({ v }: { v: Pick<EpVoteTitle, 'kind_label' | 'procedure_ref' | 'distinction'> }) {
  const parts = [v.kind_label, v.procedure_ref, v.distinction].filter(Boolean);
  return parts.length ? (
    <span className="meta vote-row-meta" style={{ display: 'block' }}>
      {parts.join(' · ')}
    </span>
  ) : null;
}

/** A vote's readable title, with lang on any French passage left in it. */
export function VoteTitle({ v }: { v: Pick<EpVoteTitle, 'title' | 'display_title' | 'display_title_parts'> }) {
  return v.display_title ? <LangText text={v.display_title} parts={v.display_title_parts} /> : <>{v.title}</>;
}
