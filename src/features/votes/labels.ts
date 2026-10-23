import type { BallotPosition, EpVoteSummary, FinalRole, VoteKind, VoteKindDetail, VoteOutcome } from '../../types/data';

export const OUTCOME_LABEL: Record<VoteOutcome, string> = {
  adopted: 'Adopted',
  rejected: 'Rejected',
  lapsed: 'Lapsed',
  unknown: 'Outcome not established',
};

/** Shown next to an outcome we calculated because neither Parliament's open data nor the minutes give it. */
export const DERIVED_OUTCOME = 'Outcome calculated from the recorded counts';

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
    'Parliament’s vote on a text as a whole: for a proposed law, its position or its approval of an agreement negotiated with the Council; for other files, for example its consent to an international agreement, its opinion on a draft Council act, a budget or discharge decision, or a decision on its own organisation.',
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

/** Explanations that replace the final vote's when the procedure establishes what it decides (`final_role`). */
export const FINAL_ROLE_EXPLAINER: Record<FinalRole, string> = {
  legislative:
    'Parliament’s vote on a legislative text as a whole (for example its position, or its approval of a negotiated agreement). It decides Parliament’s stance on the law at that stage.',
  consent:
    'Parliament gives or refuses its consent to the proposed act in a single vote, without amendments. Without its consent the act cannot be adopted (for example the decision concluding an international agreement, Article 218(6)(a) TFEU).',
  consultation:
    'Parliament gives its opinion on the proposed act. The institution that adopts the act, usually the Council, consults Parliament before it decides, but is not bound by Parliament’s opinion.',
  budget:
    'Parliament’s vote, as one arm of the budgetary authority with the Council, on a budget text as a whole: the EU’s annual budget or an amending budget (Article 314 TFEU), or a decision to mobilise a special instrument such as the European Globalisation Adjustment Fund, the Solidarity Fund or the Flexibility Instrument.',
  discharge:
    'Parliament decides whether to grant, postpone or refuse discharge for how a budget was implemented in a given year: the EU general budget (Article 319 TFEU), including its sections for the other institutions, or the budget of an EU agency or other body. The vote is on the decision proposed in its committee’s report.',
  commission_election:
    'Parliament’s vote of consent on the Commission as a body: its President, the High Representative of the Union for Foreign Affairs and Security Policy and the other members. On the basis of this consent the European Council appoints the Commission (Article 17(7) TEU).',
  parliament_decision:
    'A decision of Parliament on its own organisation, its Rules of Procedure or an agreement with other institutions (for example setting up a committee or amending its Rules). It is not a vote on a law.',
};

/** Explanations that replace the kind's when Parliament's texts say what a motion or procedural vote decides. */
export const DETAIL_EXPLAINER: Record<VoteKindDetail, string> = {
  reject_proposal:
    'A motion to reject the Commission’s proposal outright. If the motion is adopted, Parliament rejects the proposal; if the motion is rejected, the proposal is not rejected.',
  reject_council_position:
    'At second reading, a motion to reject the Council’s position. It needs a majority of Parliament’s component Members; if it is adopted, the proposed act is deemed not to have been adopted (Article 294(7)(b) TFEU).',
  censure:
    'A motion of censure on the Commission (Article 234 TFEU). It needs two thirds of the votes cast, representing a majority of Parliament’s component Members; if it is carried, the Commission must resign as a body.',
  objection:
    'An objection to a measure the Commission adopts under powers given to it by a law. If the objection is adopted, Parliament objects. The effect depends on the procedure: a delegated act cannot enter into force (Article 290(2) TFEU); a measure under the regulatory procedure with scrutiny cannot be adopted; for a draft implementing act, the Commission must review it (Regulation (EU) No 182/2011, Article 11).',
  no_objection:
    'A recommendation by the committee responsible that Parliament declare, before the deadline for objections ends, that it has no objections to a measure the Commission adopts under powers given to it by a law (Parliament’s Rules of Procedure, Rule 111(6) in the 9th term). It is decided by a majority of the votes cast. If it is adopted, any later proposal to object to the measure is inadmissible.',
  negotiation_decision:
    'A vote on whether the committee responsible may open negotiations with the Council on the basis of its report. Plenary votes on this only when political groups or enough MEPs ask for it after the committee’s decision is announced.',
  grant_discharge:
    'A vote on the proposal in a discharge report to grant discharge for how a budget was implemented in a given year: the EU general budget (Article 319 TFEU), including its sections for the other institutions, or the budget of an EU agency or other body. If the proposal is adopted, discharge is granted.',
  postpone_discharge:
    'A vote on the proposal in a discharge report to postpone Parliament’s decision on discharge for how a budget was implemented in a given year: the EU general budget (Article 319 TFEU), including its sections for the other institutions, or the budget of an EU agency or other body. If the proposal is adopted, the decision on discharge is postponed.',
  refuse_discharge:
    'A vote on the proposal in a discharge report to refuse discharge for how a budget was implemented in a given year: the EU general budget (Article 319 TFEU), including its sections for the other institutions, or the budget of an EU agency or other body. If the proposal is adopted, discharge is refused.',
  recommendation:
    'A vote on a recommendation of Parliament as a whole: a recommendation on the Union’s external policies to the Council, the Commission or the High Representative of the Union for Foreign Affairs and Security Policy (Rule 118 of Parliament’s Rules of Procedure in the 9th term), or a committee of inquiry’s recommendation to EU institutions or bodies or to the Member States (Rule 208(12)). It sets out what Parliament asks of them; it is not legislation.',
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
 * Close-vote rule, shared by the explorer filter, its methodology note and the home page list (CLOSE_RELATIVE in
 * pipeline/build.py). A vote is "close" when its outcome is established (adopted or rejected), its margin is known
 * (the legal threshold is established) and the distance from the threshold is at most 5% of the votes counted
 * towards it.
 */
export const CLOSE_RELATIVE = 0.05;

export function isClose(v: Pick<EpVoteSummary, 'margin' | 'outcome'>): boolean {
  return !!v.margin && (v.outcome === 'adopted' || v.outcome === 'rejected') && Math.abs(v.margin.relative) <= CLOSE_RELATIVE;
}

export function outcomeTone(o: VoteOutcome): string {
  return o === 'adopted' ? 'done' : o === 'rejected' ? 'critical' : 'inactive';
}

/** "x% voted with the group majority" */
export function cohesionText(c: number | null | undefined): string {
  if (c == null) return '—';
  return `${Math.round(c * 100)}% voted with the group majority`;
}
