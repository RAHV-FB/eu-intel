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
 *   votes/index.json                EpVoteSummary[]          (final/resolution/motion votes + all votes linked to dossiers)
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
  note?: string | null;
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
  started?: ISODate | null; // proposal date
  last_event?: ISODate | null;
  adopted?: ISODate | null; // adoption: Council adoption / Parliament's second-reading approval, else the act's own date (never publication)
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
  entry_into_force_pending?: boolean; // EUR-Lex gives no entry-into-force date: the act takes effect on a condition not yet met
  application_dates: ISODate[]; // further dates recorded by EUR-Lex for (parts of) the act
  partial_application_dates?: ISODate[]; // those of application_dates from which only some provisions apply
  application_detail?: { date: ISODate; partial: boolean; provisions?: string | null }[]; // checked against the act's text
  dates_note?: { reason: string; sources: { label: string; url: string }[]; reviewed?: ISODate | null } | null; // why dates were corrected
  transposition_deadlines: ISODate[]; // directives only: deadlines to transpose (general and further), not application dates
  transposition?: TranspositionDateInfo[]; // directives only: every recorded date, classified
  future: boolean; // true if any of the above lies in the future
}

/** A directive's transposition date as classified from EUR-Lex's own annotations. */
export interface TranspositionDateInfo {
  date: ISODate;
  // deadline: general transposition deadline; further_deadline: later deadline for specific provisions;
  // application: a date from which national measures (must or may) apply
  kind: 'deadline' | 'further_deadline' | 'application';
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
  editorial?: EditorialInfo | null;
  status: DossierStatus;
  next_step: NextStep;
  stall?: Stall | null;
  application?: ApplicationInfo | null;
  timeline: TimelineEvent[]; // ascending by date
  acts: LegalActSummary[];
  ep_votes: EpVoteSummary[]; // votes linked to this dossier via official ids, newest first
  council_votes: CouncilVote[];
  implementation?: DossierImplementation | null; // directives only
  committees: { code: string; name?: string | null; role: string }[];
  rapporteurs: { mep_id?: string | null; name: string; group?: string | null; country?: string | null; role: string }[];
  documents: DocRef[];
  related: { id: string; title: string; relation: string }[]; // only officially established relations
  oeil_url: string;
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
export type VoteOutcome = 'adopted' | 'rejected' | 'lapsed' | 'unknown';

export interface VoteMargin {
  rule: 'votes_cast' | 'component_members' | 'two_thirds_cast';
  rule_label: string; // "Simple majority of votes cast (abstentions not counted)"
  threshold: number; // votes in favour needed
  distance: number; // votes_for - threshold (signed)
  relative: number; // distance / votes counted towards the threshold
  label: string; // "Passed with 12 votes more than needed"
}

export interface EpVoteSummary {
  id: string;
  date: ISODate;
  title: string; // EP label (may be technical); see `display_title`
  display_title: string; // human-readable: dossier title + what was voted
  kind: VoteKind;
  kind_label: string; // "Final vote on the text", "Amendment", ...
  outcome: VoteOutcome;
  // how the outcome was established: EP open data decision, the sitting's official minutes, or calculated from
  // the recorded counts under the applicable majority rule; null when unknown
  outcome_basis?: 'published' | 'minutes' | 'derived' | null;
  for: number | null;
  against: number | null;
  abstain: number | null;
  dossier_id?: string | null;
  dossier_ref?: string | null;
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

export interface EpVoteDetail extends EpVoteSummary {
  reference_text?: string | null;
  doc_ids: string[];
  attendees?: number | null;
  groups: GroupBreakdown[];
  countries: CountryBreakdown[];
  ballots: Ballot[]; // empty when has_ballots = false
  mep_names: Record<string, string>; // id -> display name for ballots
  reconciliation: { matches: boolean; note?: string | null }; // ballots vs official totals
}

// ---------------------------------------------------------------- Council votes

export type CouncilPosition = 'for' | 'against' | 'abstain' | 'not_participating';

export interface CouncilAssessment {
  rule: 'qmv' | 'unanimity' | 'simple_majority';
  states_for: number;
  states_required: number;
  population_for_pct?: number | null; // percentage 0–100 of the EU population (participating states)
  population_required_pct?: number | null; // percentage 0–100, e.g. 65
  adopted_by_rule?: boolean | null;
  blocking_minority_existed?: boolean | null;
  single_state_veto_possible: boolean; // true only under unanimity
  note: string;
  legal_basis?: string | null; // e.g. "TEU Art. 16(4)"; null when the threshold's legal basis is not established
  states_against?: number | null;
  states_abstain?: number | null;
  states_not_participating?: number | null; // not taking part under the Treaties (opt-outs); not abstentions
}

export interface CouncilVote {
  id: string;
  date: ISODate;
  title: string;
  dossier_id?: string | null;
  dossier_ref?: string | null;
  configuration?: string | null;
  stage?: string | null; // e.g. "Adoption of the legislative act" (verbatim from the voting-result document)
  meeting?: string | null; // meeting reference as published
  written_procedure?: boolean | null; // adopted by written procedure rather than at a meeting
  council_doc?: string | null; // e.g. "PE-CONS 24/24"
  voting_rule: 'qmv' | 'unanimity' | 'simple_majority' | 'unknown';
  outcome: 'adopted' | 'not_adopted' | 'unknown';
  positions: Record<string, CouncilPosition>; // ISO2 -> position
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
  council_votes: { vote_id: string; date: ISODate; title: string; pos: CouncilPosition; dossier_id?: string | null }[];
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
    infringements: InfringementInfo[];
  }[];
  nim_url: string; // EUR-Lex national transposition page
  source: SourceRef;
  note: string;
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
