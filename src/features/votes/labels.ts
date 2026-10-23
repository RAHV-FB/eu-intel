import type { BallotPosition, EpVoteSummary, VoteKind, VoteOutcome } from '../../types/data';

export const OUTCOME_LABEL: Record<VoteOutcome, string> = {
  adopted: 'Adopted',
  rejected: 'Rejected',
  lapsed: 'Lapsed',
  unknown: 'Outcome not recorded',
};

export const OUTCOME_ICON: Record<VoteOutcome, string> = {
  adopted: '●',
  rejected: '✕',
  lapsed: '○',
  unknown: '○',
};

export const KIND_LABEL: Record<VoteKind, string> = {
  final: 'Final vote',
  mandate: 'Negotiating mandate',
  amendment: 'Amendment',
  split_or_separate: 'Split or separate vote',
  resolution: 'Resolution',
  motion: 'Motion',
  procedural: 'Procedural vote',
  other: 'Other vote',
};

/** One-sentence plain-language explanation of each kind of plenary vote. */
export const KIND_EXPLAINER: Record<VoteKind, string> = {
  final:
    'Parliament’s vote on a legislative text as a whole (for example its position, or its approval of a negotiated agreement). It decides Parliament’s stance on the law at that stage.',
  mandate:
    'Parliament’s vote on its amended version of a proposal, after which the file is referred back to committee to negotiate with the Council. It sets Parliament’s negotiating position; it is not the final vote on the law.',
  amendment:
    'A vote on a proposed change to part of a text. Amendments are voted before the text as a whole; a rejected amendment does not mean the law itself was rejected.',
  split_or_separate:
    'A vote on one part of a text or amendment, taken separately at a group’s or MEPs’ request. It decides only that part.',
  resolution:
    'A vote on a resolution: a text setting out Parliament’s view. Most resolutions are not legislation and do not create legal obligations.',
  motion:
    'A vote on a motion for a resolution or a similar request tabled in plenary, such as an objection or a motion of censure.',
  procedural:
    'A vote about how Parliament handles a file (for example referring it back to committee or opening negotiations), not about the content of the law.',
  other: 'A plenary vote that does not fit the categories above.',
};

export const POSITION_LABEL: Record<BallotPosition, string> = {
  for: 'For',
  against: 'Against',
  abstain: 'Abstained',
};

export const POSITION_ICON: Record<BallotPosition, string> = {
  for: '+',
  against: '−',
  abstain: '○',
};

/**
 * Close-vote rule, shared by the explorer filter and its methodology note.
 * A vote is "close" when its margin is known (the legal threshold is established) and the
 * distance from the threshold is at most 5% of the votes counted towards it.
 */
export const CLOSE_RELATIVE = 0.05;

export function isClose(v: Pick<EpVoteSummary, 'margin'>): boolean {
  return !!v.margin && Math.abs(v.margin.relative) <= CLOSE_RELATIVE;
}

export function outcomeTone(o: VoteOutcome): string {
  return o === 'adopted' ? 'done' : o === 'rejected' ? 'critical' : 'inactive';
}

/** "x% voted with the group majority" */
export function cohesionText(c: number | null | undefined): string {
  if (c == null) return '—';
  return `${Math.round(c * 100)}% voted with the group majority`;
}
