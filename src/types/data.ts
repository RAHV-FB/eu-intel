/**
 * Public data contract: the static JSON files under public/data/ produced by
 * `python -m pipeline build` (pipeline/build.py) and consumed by the frontend.
 *
 * Rules
 * - Dates are "YYYY-MM-DD" strings; timestamps are ISO 8601 UTC.
 * - Optional/nullable fields mean "not available in our sources" — the UI must say so,
 *   never guess. `basis` fields tell whether a statement is recorded at source or derived by us.
 * - Every institutional fact shown should be traceable through a SourceRef.
 *
 * Files (all paths relative to `${BASE_URL}data/`):
 *   meta.json                       Meta
 *   home.json                       HomeData
 *   dossiers/index.json             DossierSummary[]
 *   dossiers/<id>.json              DossierDetail            (id like "2021-0106")
 *   votes/index.json                EpVoteSummary[]          (roll-call votes on whole texts + final, mandate and
 *                                                            negotiation-decision votes linked to procedures)
 *   votes/<id>.json                 EpVoteDetail
 *   council/index.json              CouncilVote[]
 *   people/meps.json                MepSummary[]
 *   people/meps/<id>.json           MepDetail
 *   people/groups.json              GroupSummary[]
 *   people/groups/<id>.json         GroupDetail              (id = slug, e.g. "epp", "s-d", "renew")
 *   people/parties.json             PartySummary[]
 *   people/parties/<id>.json        PartyDetail              (id = EP org id)
 *   countries/index.json            CountrySummary[]
 *   countries/<code>.json           CountryDetail            (code = ISO alpha-2, e.g. "ES")
 *   topics.json                     Topic[]
 *   search.json                     SearchDoc[]
 *   activity.json                   ActivityItem[]
 *   feeds/updates.xml, feeds/<topic>.xml   Atom feeds
 */

export type ISODate = string;
export type ISODateTime = string;

export type Institution =
  | 'EP'
  | 'Council'
  | 'European Council'
  | 'Commission'
  | 'EUR-Lex'
  | 'OEIL'
  | 'LegislativeTrain'
  | 'CJEU';

export interface SourceRef {
  institution: Institution;
  url: string;
  label?: string | null;
  identifier?: string | null;
  retrieved_at?: ISODateTime | null;
  published?: ISODate | null;
}

export interface DocRef {
  id: string; // "COM(2021)0206", "A9-0188/2023"
  label?: string | null;
  kind?: string | null;
  date?: ISODate | null;
  url?: string | null;
}

// ---------------------------------------------------------------- meta

export interface SourceStatusInfo {
  id: string; // "ep_people", "ep_procedures", "ep_votes", "eurlex", "council", "implementation", "train"
  name: string; // "European Parliament – MEPs and political groups"
  institution: Institution;
  url: string; // documentation / landing page of the source
  licence: string; // short reuse/attribution statement
  status: 'ok' | 'partial' | 'failed' | 'unavailable';
  fetched_at?: ISODateTime | null; // last successful retrieval
  records: Record<string, number>;
  note?: string | null; // retrieval log from the pipeline (technical detail)
  summary?: string | null; // plain-language note: what this release holds from the source, known gaps
}

/** The limits of the dataset, stated next to lists and counts (meta.json `scope`). */
export interface CoverageScope {
  procedure_types: string[]; // ["COD", "CNS", "APP"]
  procedures_from_year?: number | null; // procedures with this reference year or later
  acts_from?: ISODate | null; // adopted acts dated on or after this
  ep_votes_from?: ISODate | null; // first and last Parliament vote listed
  ep_votes_to?: ISODate | null;
  ep_roll_call_votes: number; // all roll-call votes in the source data (incl. amendments)
  dossiers_without_topic: number; // files that no topic covers
}

export interface Meta {
  built_at: ISODateTime; // when public/data was generated
  snapshot_at?: ISODateTime | null; // latest successful source retrieval across sources
  sources: SourceStatusInfo[];
  counts: {
    dossiers: number;
    legal_acts: number;
    meps: number;
    meps_active: number;
    ep_votes: number;
    ep_votes_with_ballots: number;
    council_votes: number;
    national_measures: number;
    infringements: number;
  };
  coverage_notes: string[]; // plain-language statements of what is and isn't covered
  scope?: CoverageScope;
}

// ---------------------------------------------------------------- topics

export interface Topic {
  slug: string; // "tech"
  label: string; // "Technology & AI"
  description: string;
  count: number; // dossiers in this topic
}

// ---------------------------------------------------------------- dossiers

export type LifecycleStage =
  | 'proposed' // proposal tabled; under examination
  | 'parliament_position' // Parliament adopted its position; Council has not concluded
  | 'negotiations' // interinstitutional negotiations under way
  | 'provisional_agreement' // provisional agreement reached; awaiting formal adoption
  | 'adopted' // formally adopted; not yet published
  | 'published' // published in the Official Journal; not yet in force
  | 'in_force' // in force (some provisions may apply later)
  | 'takes_effect_on_notification' // decision addressed to specific recipients; EUR-Lex records no notification date
  | 'no_longer_in_force' // repealed, expired or otherwise no longer in force according to EUR-Lex
  | 'withdrawn'
  | 'rejected'
  | 'lapsed'
  | 'unknown';

export type Basis = 'source' | 'derived' | 'unknown';

export type LegalInstrument = 'regulation' | 'directive' | 'decision' | 'recommendation' | 'other';

export interface DossierSummary {
  id: string; // "2021-0106"
  ref: string; // "2021/0106(COD)"
  type: string; // "COD" | "CNS" | "APP" | ...
  type_label: string; // "Ordinary legislative procedure"
  title: string; // human-readable: curated short title if any, else cleaned official title
  official_title: string;
  short?: string | null; // one-sentence curated description (only for curated dossiers)
  topics: string[]; // topic slugs
  stage: LifecycleStage;
  status_label: string; // "Approved by Parliament", "In force", ...
  started?: ISODate | null; // proposal date: the earliest recorded proposal or COM document (a consent file's Commission proposal precedes the Council draft)
  last_event?: ISODate | null;
  // adoption: Parliament's second-reading approval, else the Council's adoption dated by its voting result; a Council act's own date
  // when no vote is linked; Parliament's decision for acts it adopts with the Council's consent (never after publication)
  adopted?: ISODate | null;
  published?: ISODate | null; // publication of the final act in the Official Journal
  next_date?: ISODate | null; // earliest legally fixed future date (application / transposition deadline), if any
  instrument?: LegalInstrument | null; // final act type if adopted, or proposed instrument if known
  celex: string[];
  featured: boolean;
  officially_blocked: boolean; // only true when an official source (Legislative Train) says so
  has_ep_votes: boolean;
  has_council_votes: boolean;
}

export interface DossierStatus {
  stage: LifecycleStage;
  label: string;
  explanation: string; // 1–2 plain sentences
  since?: ISODate | null;
  basis: Basis;
  named_acts?: NamedAct[]; // acts the explanation names by `label` (e.g. the repealing act), to link them
}

/** An act named in a status explanation. */
export interface NamedAct {
  celex: string;
  label: string; // "Directive (EU) 2021/555" (official title), "Regulation 2017/1430" (from the CELEX id), or the CELEX id
  url: string; // EUR-Lex
  dossier?: string | null; // its legislative file on this site, if any
}

export interface NextStep {
  text: string;
  institution?: Institution | null;
  basis: Basis;
}

export interface Stall {
  days_since_last_event: number;
  text?: string | null; // neutral description, e.g. "No recorded procedural update in 412 days"
  last_event_date?: ISODate | null;
  official_label?: string | null; // e.g. Legislative Train status, verbatim
  official_source_url?: string | null;
  official_label_date?: ISODate | null; // the Legislative Train file's "information updated as of" date
  official_text?: string | null; // sentence citing the official classification
}

export interface ApplicationInfo {
  entry_into_force?: ISODate | null;
  entry_into_force_pending?: boolean; // EUR-Lex gives no entry-into-force date: the act enters into force on a condition not yet met
  entry_into_force_condition?: string | null; // that condition, when the Treaty or EUR-Lex states it (one sentence)
  effect_on_notification?: boolean; // a decision that takes effect on notification to its addressee; EUR-Lex records no date
  application_dates: ISODate[]; // further dates recorded by EUR-Lex for (parts of) the act
  partial_application_dates?: ISODate[]; // those of application_dates from which only some provisions apply
  application_detail?: { date: ISODate; partial: boolean; provisions?: string | null }[]; // checked against the act's text
  dates_note?: { reason: string; sources: { label: string; url: string }[]; reviewed?: ISODate | null } | null; // why dates were corrected
  transposition_deadlines: ISODate[]; // directives only: deadlines to transpose (general and further), not application or other dates
  transposition?: TranspositionDateInfo[]; // directives only: every recorded date, classified
  future: boolean; // true if any of the above lies in the future
  after_end_of_validity?: ISODate[]; // dates above that EUR-Lex records for after the end of the act's validity
}

/** A directive's transposition date as classified from EUR-Lex's own annotations (and, where they cannot tell, a
 * check of the act's text: data/curated/transposition.yaml). */
export interface TranspositionDateInfo {
  date: ISODate;
  // deadline: general transposition deadline; further_deadline: deadline for specific provisions (earlier or
  // later); application: a date from which national measures (must or may) apply; other: a date EUR-Lex records
  // whose role the data do not establish (e.g. an optional "may apply" date), never shown as a deadline
  kind: 'deadline' | 'further_deadline' | 'application' | 'other';
  articles: string[]; // "Art. 48(1)"
}

export type EventKind =
  | 'proposal'
  | 'referral'
  | 'committee_opinion'
  | 'committee_report'
  | 'negotiation_mandate'
  | 'plenary_debate'
  | 'plenary_vote'
  | 'ep_position'
  | 'provisional_agreement'
  | 'council_position'
  | 'council_adoption'
  | 'signature'
  | 'publication'
  | 'entry_into_force'
  | 'application'
  | 'transposition_deadline'
  | 'transposition_application'
  | 'withdrawal'
  | 'rejection'
  | 'lapsed'
  | 'other';

export interface TimelineEvent {
  id: string;
  date: ISODate;
  kind: EventKind;
  title: string; // plain English
  detail?: string | null;
  institution: Institution;
  state: 'done' | 'scheduled'; // 'scheduled' only for legally fixed future dates (application, transposition)
  key: boolean; // milestone worth showing in the compact timeline
  docs: DocRef[];
  source?: SourceRef | null;
  vote_id?: string | null; // EP vote linked to this event, if any
  after_end_of_validity?: ISODate | null; // an act's date recorded for after its validity ended (that end date)
}

export interface LegalActSummary {
  celex: string;
  eli?: string | null;
  act_type: LegalInstrument;
  title: string;
  date_document?: ISODate | null;
  date_publication?: ISODate | null;
  entry_into_force?: ISODate | null;
  other_application_dates: ISODate[];
  transposition_deadlines: ISODate[];
  in_force?: boolean | null;
  end_of_validity?: ISODate | null;
  eurlex_url: string;
  amends: string[];
  amended_by: string[];
  repeals: string[];
  repealed_by: string[];
  court_rulings: CourtRulingInfo[]; // Court of Justice judgments recorded by EUR-Lex as annulling / invalidating
}

export interface CourtRulingInfo {
  case_number?: string | null; // "C-19/23"
  celex: string;
  date?: ISODate | null;
  ecli?: string | null;
  effect: 'annulment' | 'invalidity';
  kind_label: string; // "Action for annulment" | "Preliminary ruling on validity"
  provisions: string[]; // "Article 5(1)"; empty when EUR-Lex does not record specific provisions
  summary: string;
  url: string;
}

export interface EditorialInfo {
  short_title: string;
  what: string;
  why: string;
  aliases: string[];
  sources: { label: string; url: string }[];
  reviewed: ISODate;
}

export interface DossierDetail extends DossierSummary {
  // act numbers, verified common names, and the package a file belongs to ("Pact on Migration and Asylum")
  known_as?: { acts: string[]; names: string[]; part_of?: string[] } | null;
  editorial?: EditorialInfo | null;
  status: DossierStatus;
  next_step: NextStep;
  stall?: Stall | null;
  application?: ApplicationInfo | null;
  timeline: TimelineEvent[]; // ascending by date
  acts: LegalActSummary[];
  ep_votes: EpVoteSummary[]; // votes linked to this dossier via official ids, newest first
  council_votes: CouncilVote[];
  // Split procedures only: Council votes that cite this (parent) reference, listed on the part whose act they adopted
  council_votes_in_parts?: { id: string; date: ISODate; dossier_id: string; dossier_ref: string }[];
  implementation?: DossierImplementation | null; // directives only
  committees: { code: string; name?: string | null; role: string }[];
  rapporteurs: { mep_id?: string | null; name: string; group?: string | null; country?: string | null; role: string }[];
  documents: DocRef[];
  related: { id: string; title: string; relation: string }[]; // only officially established relations
  dates_set_for?: { id: string; title: string; dates: ISODate[] }[]; // dates this file's act set for another act (checked)
  oeil_url: string | null; // null where OEIL has no file under this reference (e.g. a split procedure's parent)
  eurlex_only?: boolean; // built from the EUR-Lex act alone: the procedure's own steps are not in our data
  sources: SourceRef[];
  changes: ActivityItem[]; // verified changes detected between snapshots for this dossier
}

// ---------------------------------------------------------------- EP votes

export type VoteKind =
  | 'final'
  | 'mandate' // Parliament's negotiating mandate: amended text referred back to committee for negotiations
  | 'amendment'
  | 'split_or_separate'
  | 'resolution'
  | 'motion'
  | 'procedural'
  | 'other';
/** What a motion or procedural vote decides, where Parliament's published texts say so. */
export type VoteKindDetail =
  | 'reject_proposal' // motion to reject the Commission proposal: "adopted" = Parliament rejected the proposal
  | 'reject_council_position' // second reading: motion to reject the Council's position
  | 'censure' // motion of censure on the Commission
  | 'objection' // objection to a delegated or implementing act: "adopted" = Parliament objects
  | 'negotiation_decision'; // vote on a committee's decision to enter into interinstitutional negotiations
export type VoteOutcome = 'adopted' | 'rejected' | 'lapsed' | 'unknown';

export interface VoteMargin {
  rule: 'votes_cast' | 'component_members' | 'two_thirds_cast';
  rule_label: string; // "Simple majority of votes cast (abstentions not counted)"
  threshold: number; // votes in favour needed
  distance: number; // votes_for - threshold (signed)
  relative: number; // distance / votes counted towards the threshold
  label: string; // "Passed with 12 votes more than needed"
  component_members?: number | null; // Members in office on the day, for rules based on component Members
}

/** A run of text and its language ("fr", "de"), or null for the page language, references and names. */
export type LangRun = [lang: string | null, text: string];

export interface EpVoteSummary {
  id: string;
  date: ISODate;
  title: string; // EP label (may be technical, or the title in French, English and German); see `display_title`
  display_title: string; // human-readable: dossier title + what was voted
  // only when display_title is Parliament's own label with French passages: its runs, for lang attributes
  display_title_parts?: LangRun[];
  kind: VoteKind;
  kind_detail?: VoteKindDetail | null;
  kind_label: string; // "Final vote on the text", "Amendment", ...
  outcome: VoteOutcome;
  outcome_note?: string | null; // what the outcome means, e.g. for a motion to reject or an objection
  // how the outcome was established: EP open data decision, the sitting's official minutes, or calculated from
  // the recorded counts under the applicable majority rule; null when unknown
  outcome_basis?: 'published' | 'minutes' | 'derived' | null;
  for: number | null;
  against: number | null;
  abstain: number | null;
  dossier_id?: string | null;
  dossier_ref?: string | null;
  procedure_ref?: string | null; // official procedure reference, also when the procedure is not a tracked file
  topics: string[];
  margin?: VoteMargin | null; // null when the applicable threshold cannot be established
  has_ballots: boolean;
  source: SourceRef;
}

export type BallotPosition = 'for' | 'against' | 'abstain';

export interface PositionCounts {
  for: number;
  against: number;
  abstain: number;
}

export interface GroupBreakdown extends PositionCounts {
  group: string; // group slug ("epp"); group membership at the date of the vote
  group_code: string; // "EPP"
  majority?: BallotPosition | null; // position of the plurality of the group's recorded votes
  cohesion?: number | null; // share of the group's recorded votes matching its majority (0..1)
}

export interface CountryBreakdown extends PositionCounts {
  country: string; // MEPs' country of representation (NOT the Member State's Council position)
}

export interface Ballot {
  mep: string; // MEP id
  pos: BallotPosition;
  group?: string | null; // group slug at vote date
  country?: string | null;
  party?: string | null; // national party org id at vote date
  intended?: BallotPosition | null; // correction recorded after the vote (does not change the result)
}

/** An MEP with no recorded vote who stated afterwards how they had intended to vote. */
export interface VoteIntention {
  mep: string;
  intended: BallotPosition;
  group?: string | null;
  country?: string | null;
}

export interface EpVoteDetail extends EpVoteSummary {
  title_parts?: LangRun[] | null; // `title` in runs by language when it has French or German passages
  subject?: string | null; // what was voted, as published in English (vote item or minutes block title)
  procedure_url?: string | null; // Legislative Observatory (OEIL) file of procedure_ref
  reference_text?: string | null;
  doc_ids: string[];
  attendees?: number | null;
  groups: GroupBreakdown[];
  countries: CountryBreakdown[];
  ballots: Ballot[]; // empty when has_ballots = false
  intentions?: VoteIntention[]; // stated intentions of MEPs without a recorded vote
  mep_names: Record<string, string>; // id -> display name for ballots
  reconciliation: { matches: boolean; note?: string | null }; // ballots vs official totals
}

// ---------------------------------------------------------------- Council votes

export type CouncilPosition = 'for' | 'against' | 'abstain' | 'not_participating';

export interface CouncilAssessment {
  rule: 'qmv' | 'unanimity' | 'simple_majority';
  states_for: number;
  states_required: number;
  // Only when legal_basis is null under QMV: Member States needed if the Council did NOT act on a Commission
  // proposal (72%, TFEU Art. 238(2)); states_required is then the figure for a Commission proposal (55%)
  states_required_alt?: number | null;
  // Percentage 0–100 of the population of the Member States TAKING PART in the vote. Equal to the share of
  // the EU population only when states_not_participating is 0.
  population_for_pct?: number | null;
  population_required_pct?: number | null; // percentage 0–100, e.g. 65
  adopted_by_rule?: boolean | null;
  blocking_minority_existed?: boolean | null;
  single_state_veto_possible: boolean; // true only under unanimity
  note: string;
  legal_basis?: string | null; // e.g. "TEU Art. 16(4)"; null when the threshold's legal basis is not established
  states_against?: number | null;
  states_abstain?: number | null;
  states_not_participating?: number | null; // not taking part under the Treaties (opt-outs); not abstentions
  states_participating?: number | null; // thresholds are computed over these Member States only
  // Minimum number of Member States in a blocking minority under the applicable rule (4 under TEU Art. 16(4);
  // computed under TFEU Art. 238(3)(a)); null where no such clause applies or the legal basis is not established
  blocking_minority_min_states?: number | null;
}

/**
 * What the Council voted on. 'first_reading_position': the Council's position at first reading — the act is NOT
 * adopted by this vote (Parliament must still approve it at second reading). 'act': adoption of the act itself.
 * 'other': another item (budget procedure, approval of a joint text or statement, consent, ...).
 */
export type CouncilVoteOn = 'act' | 'first_reading_position' | 'other';

export interface CouncilVote {
  id: string;
  date: ISODate;
  title: string;
  dossier_id?: string | null;
  dossier_ref?: string | null;
  configuration?: string | null;
  stage?: string | null; // item(s) voted on as listed in the voting-result document, "; "-separated
  vote_on?: CouncilVoteOn | null; // normalised from the subject; null when the document names no item
  // Set when vote_on differs from what the voting-result document's own label says, citing the procedure
  // record that shows it (e.g. its reference document is the Council's first-reading position)
  vote_on_note?: string | null;
  meeting?: string | null; // meeting reference as published
  written_procedure?: boolean | null; // adopted by written procedure rather than at a meeting
  council_doc?: string | null; // e.g. "PE-CONS 24/24"
  voting_rule: 'qmv' | 'unanimity' | 'simple_majority' | 'unknown';
  outcome: 'adopted' | 'not_adopted' | 'unknown';
  positions: Record<string, CouncilPosition>; // ISO2 -> position
  // Only when positions is empty: why we could not read them from the published voting sheet (the Council
  // does publish them). Plain language, specific.
  positions_note?: string | null;
  assessment?: CouncilAssessment | null;
  statements: string[];
  source: SourceRef;
}

// ---------------------------------------------------------------- people

export interface MepSummary {
  id: string;
  name: string;
  sort: string;
  country: string; // ISO2
  group?: string | null; // group slug: current, or last known for former MEPs
  group_code?: string | null;
  party?: string | null; // party org id (current or last)
  party_label?: string | null;
  active: boolean;
  terms: number[];
}

export interface MembershipPeriod {
  id: string; // org id or slug
  label: string;
  code?: string | null;
  from?: ISODate | null;
  to?: ISODate | null; // null = ongoing
  role?: string | null;
}

export interface MepDetail extends MepSummary {
  groups: MembershipPeriod[];
  parties: MembershipPeriod[];
  committees: MembershipPeriod[];
  rapporteur_for: { dossier_id: string; title: string; role: string }[];
  votes: { vote_id: string; pos: BallotPosition }[]; // positions on indexed votes with ballots, newest first
  official_url: string;
  source: SourceRef;
}

export interface GroupSummary {
  id: string; // slug
  code: string; // "EPP"
  name: string; // full official name
  active: boolean; // exists in current term
  terms: number[];
  members: number; // current members (active MEPs)
  countries: Record<string, number>; // current members by country
}

export interface GroupDetail extends GroupSummary {
  member_ids: string[]; // current members
  parties: { id: string; label: string; country: string; members: number }[];
  votes: { vote_id: string; majority?: BallotPosition | null; cohesion?: number | null; counts: PositionCounts }[];
  source: SourceRef;
}

export interface PartySummary {
  id: string;
  label: string;
  code?: string | null;
  country: string;
  members_active: number;
  members_total: number; // all MEPs in our dataset ever recorded in this party
  groups: string[]; // group slugs its MEPs belonged to (all periods in dataset)
}

export interface PartyDetail extends PartySummary {
  meps: { id: string; name: string; active: boolean; from?: ISODate | null; to?: ISODate | null }[];
  group_history: { group: string; from?: ISODate | null; to?: ISODate | null; meps: number }[];
  source: SourceRef;
}

// ---------------------------------------------------------------- countries

export interface CountryIndicatorValue {
  indicator: string;
  label: string;
  value: number | null;
  unit: string;
  period: string;
  definition: string;
  source: SourceRef;
}

export interface CountrySummary {
  code: string;
  name: string;
  meps_active: number;
  groups: Record<string, number>; // active MEPs by group slug
  council_positions: { for: number; against: number; abstain: number; not_participating: number };
  indicators: CountryIndicatorValue[];
  open_infringements?: number | null; // null if infringement data unavailable
}

export interface CountryDetail extends CountrySummary {
  meps: { id: string; name: string; group?: string | null; party_label?: string | null }[];
  parties: { id: string; label: string; members_active: number }[];
  council_votes: {
    vote_id: string;
    date: ISODate;
    title: string; // official title, as published
    display_title?: string; // the official title without leading legal-form boilerplate (pipeline: council_display_title)
    pos: CouncilPosition;
    dossier_id?: string | null;
    vote_on?: CouncilVoteOn | null;
  }[];
  transposition: {
    celex: string;
    title: string;
    dossier_id?: string | null;
    deadline?: ISODate | null;
    measures: number; // notified measures in the dataset
    status: TranspositionStatus;
  }[];
  infringements: InfringementInfo[];
}

export type TranspositionStatus =
  | 'measures_notified' // at least one national measure in the dataset
  | 'none_found' // no measures found in the available dataset (NOT proof of non-compliance)
  | 'deadline_not_reached'
  | 'no_deadline' // EUR-Lex records no transposition deadline (e.g. codifications)
  | 'not_participating' // recorded as not participating in the Council's adoption (Treaty opt-out): not bound
  | 'unavailable';

export interface InfringementInfo {
  id: string;
  country: string;
  celex?: string | null;
  title: string;
  non_communication?: boolean | null;
  latest_stage?: string | null;
  latest_decision_date?: ISODate | null;
  status: 'open' | 'closed' | 'unknown';
  source: SourceRef;
}

export interface DossierImplementation {
  celex: string;
  deadline?: ISODate | null;
  countries: {
    country: string;
    measures: number;
    status: TranspositionStatus;
    latest_notification?: ISODate | null; // latest date a measure was notified to the Commission
    opted_in?: string | null; // CELEX of the Commission decision confirming the country took part after adoption
    infringements: InfringementInfo[];
  }[];
  nim_url: string; // EUR-Lex national transposition page
  source: SourceRef;
  note: string;
  participation_unknown?: string[]; // DK/IE: neither the recitals nor a Council vote say whether they are bound
}

// ---------------------------------------------------------------- home & activity

export interface ActivityItem {
  id: string;
  date: ISODate; // date of the underlying event (not the detection date)
  detected_at?: ISODateTime | null; // when our snapshot first recorded it (null for the first snapshot)
  kind:
    | 'new_dossier'
    | 'milestone'
    | 'ep_vote'
    | 'council_vote'
    | 'status_change'
    | 'publication'
    | 'deadline'
    | 'implementation';
  title: string;
  dossier_id?: string | null;
  vote_id?: string | null;
  source?: SourceRef | null;
}

export interface HomeListItem {
  dossier_id?: string | null;
  vote_id?: string | null;
  title: string;
  subtitle?: string | null;
  date?: ISODate | null;
  badge?: string | null;
}

export interface FeaturedItem {
  dossier: DossierSummary;
  what: string;
  why: string;
  status: DossierStatus;
  latest?: TimelineEvent | null;
  next_step: NextStep;
  source: SourceRef;
  oeil_url?: string | null; // the human-readable procedure file on the Legislative Observatory
}

export interface HomeData {
  featured: FeaturedItem[];
  lists: {
    id: 'recently_adopted' | 'under_debate' | 'close_votes' | 'rejected' | 'stalled' | 'upcoming';
    title: string;
    description: string;
    items: HomeListItem[];
  }[];
  topics: Topic[];
}

// ---------------------------------------------------------------- search

export type SearchKind = 'dossier' | 'act' | 'mep' | 'group' | 'party' | 'country' | 'topic' | 'vote' | 'page';

export interface SearchDoc {
  id: string; // unique within kind
  k: SearchKind;
  t: string; // title
  s?: string; // subtitle (status, country, group...)
  a?: string; // aliases / alternative names, space-separated
  x?: string; // extra keywords (identifiers, subjects)
  u: string; // app route, e.g. "/legislation/2021-0106"
  w?: number; // static boost (e.g. featured dossiers, active MEPs)
  d?: ISODate; // relevant date for display/sorting
}
