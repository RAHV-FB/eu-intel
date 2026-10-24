/**
 * Short, accurate explanations shown inline via <Term id="...">.
 * Keep each `short` to 1–2 sentences. `href` points to the relevant section of /how-the-eu-works.
 * Keep ids stable: pages link to them.
 */
export interface GlossaryEntry {
  term: string;
  short: string;
  href?: string;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  commission: {
    term: 'European Commission',
    short: 'The EU’s executive. It proposes almost all EU laws and checks that Member States apply them.',
    href: '/how-the-eu-works#commission',
  },
  parliament: {
    term: 'European Parliament',
    short: 'Directly elected by EU citizens. It amends and votes on EU laws together with the Council.',
    href: '/how-the-eu-works#parliament',
  },
  council: {
    term: 'Council of the EU',
    short:
      'Government ministers from each Member State. It negotiates and adopts EU laws with Parliament. Not the same as the European Council.',
    href: '/how-the-eu-works#council',
  },
  'european-council': {
    term: 'European Council',
    short: 'The heads of state or government of the Member States. It sets political priorities but does not pass laws.',
    href: '/how-the-eu-works#european-council',
  },
  olp: {
    term: 'Ordinary legislative procedure',
    short:
      'The standard way EU laws are made: the Commission proposes, and Parliament and the Council must both agree on the same text.',
    href: '/how-the-eu-works#olp',
  },
  trilogue: {
    term: 'Interinstitutional negotiations',
    short:
      'Informal talks between Parliament, the Council and the Commission to agree a compromise text. Any deal must still be formally adopted.',
    href: '/how-the-eu-works#olp',
  },
  'provisional-agreement': {
    term: 'Provisional agreement',
    short: 'A compromise reached in negotiations. It is not yet law: Parliament and the Council must still formally adopt it.',
    href: '/how-the-eu-works#olp',
  },
  regulation: {
    term: 'Regulation',
    short: 'An EU law that applies directly in every Member State, without national laws to transpose it.',
    href: '/how-the-eu-works#instruments',
  },
  directive: {
    term: 'Directive',
    short: 'An EU law that sets goals each Member State must achieve by adopting its own national measures by a deadline.',
    href: '/how-the-eu-works#instruments',
  },
  transposition: {
    term: 'Transposition',
    short: 'Turning a directive into national law. Countries must notify the Commission of the measures they adopt.',
    href: '/how-the-eu-works#implementation',
  },
  infringement: {
    term: 'Infringement procedure',
    short:
      'A formal case the Commission can open when it considers a Member State is not applying EU law. An open case is not a court ruling.',
    href: '/how-the-eu-works#infringements',
  },
  qmv: {
    term: 'Qualified majority',
    short:
      'The Council’s usual voting rule: at least 55% of Member States (15 of 27) representing at least 65% of the EU population.',
    href: '/how-the-eu-works#council-voting',
  },
  unanimity: {
    term: 'Unanimity',
    short: 'All participating Member States must agree. A single “no” vote blocks the decision; abstaining does not.',
    href: '/how-the-eu-works#council-voting',
  },
  'roll-call': {
    term: 'Roll-call vote',
    short: 'A plenary vote where each MEP’s individual choice is recorded and published.',
    href: '/how-the-eu-works#parliament-voting',
  },
  'political-group': {
    term: 'Political group',
    short:
      'MEPs sit in groups by political affiliation, not by nationality. Each group brings together national parties from several countries.',
    href: '/how-the-eu-works#parliament',
  },
  'entry-into-force': {
    term: 'Entry into force',
    short:
      'The date from which an act is part of the EU legal order: the date the act sets or, if it sets none, the twentieth day after publication. Its rules may start to apply later, sometimes in phases.',
    href: '/how-the-eu-works#instruments',
  },
  celex: {
    term: 'CELEX number',
    short: 'The unique document number EUR-Lex uses for each EU legal act, e.g. 32024R1689 for the AI Act.',
  },
  'procedure-reference': {
    term: 'Procedure reference',
    short: 'The identifier Parliament uses for a legislative file, e.g. 2021/0106(COD): year, number, and procedure type.',
  },
  cjeu: {
    term: 'Court of Justice of the EU',
    short:
      'Interprets EU law so it is applied the same way everywhere, and rules on cases such as infringements. Only the Court can rule that a Member State has breached EU law.',
    href: '/how-the-eu-works#cjeu',
  },
  'special-procedure': {
    term: 'Special legislative procedure',
    short:
      'Used in some areas set by the treaties: the Council adopts the law after consulting Parliament (consultation) or with its approval (consent), often by unanimity.',
    href: '/how-the-eu-works#special',
  },
  'blocking-minority': {
    term: 'Blocking minority',
    short:
      'Under qualified majority voting, at least four Member States representing more than 35% of the EU population can stop a decision. One country cannot do so alone.',
    href: '/how-the-eu-works#council-voting',
  },
  'absolute-majority': {
    term: 'Majority of component members',
    short: 'A majority of all MEPs (361 of 720), however many take part in the vote. Needed for some decisions, such as second-reading amendments.',
    href: '/how-the-eu-works#parliament-voting',
  },
  decision: {
    term: 'Decision',
    short: 'An EU act that is binding in full on those it is addressed to, such as a Member State or a company.',
    href: '/how-the-eu-works#instruments',
  },
  'official-journal': {
    term: 'Official Journal of the EU',
    short:
      'The EU’s official publication. Adopted legislative acts are published in it. They enter into force on the date they set or, if they set none, on the twentieth day after publication.',
    href: '/how-the-eu-works#olp',
  },
  'reasoned-opinion': {
    term: 'Reasoned opinion',
    short:
      'A stage of an infringement procedure: the Commission’s formal request to a Member State to comply with EU law, explaining why it sees a breach.',
    href: '/how-the-eu-works#infringements',
  },
};
