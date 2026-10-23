import { Fragment } from 'react';
import type { EpVoteSummary, LangRun } from '../../types/data';

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

/** A vote's readable title, with lang on any French passage left in it. */
export function VoteTitle({ v }: { v: Pick<EpVoteSummary, 'title' | 'display_title' | 'display_title_parts'> }) {
  return v.display_title ? <LangText text={v.display_title} parts={v.display_title_parts} /> : <>{v.title}</>;
}
