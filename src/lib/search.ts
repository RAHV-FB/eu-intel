/**
 * Client-side search over public/data/search.json (SearchDoc[]).
 *
 * Ranking, strongest first (a weaker tier never outranks a stronger one):
 *   1. exact identifier      procedure "2021/0106(COD)" or "2021/0106", a part of a split procedure "2016/0224A(COD)"
 *                            or "2016/0224A", CELEX "32024R1689" or "CELEX:32024R1689", "COM(2021)206", act number
 *                            "2024/1689", "Regulation (EU) 2024/1689", "Directive 2014/24/EU", also as readers write
 *                            it: "EU Regulation 2016/679", "Reg. (EU) 2016/679", "Dir 2019/1937", "EU 2016/679";
 *                            as its official title begins ("Regulation (EU) 2016/679 of the European Parliament and of
 *                            the Council of 27 April 2016 on …"); an act's EUR-Lex or ELI address ("…?uri=CELEX:
 *                            32016R0679", "…/eli/reg/2016/679/oj"); a file's id as in its address, "2023-0134"
 *   2. exact name            title or alias equals the query ("AI Act", "EPP", "Spain", "Spanish"), also after "EU"
 *                            ("EU GDPR"), or after "European" or "EU" in the name for a query of two or more words
 *                            ("climate law": "European Climate Law"); a country, group or party next to the words
 *                            for MEPs ("Spanish MEPs", "EPP MEPs", "Patriots for Europe MEPs"), flagged `meps`; not
 *                            one of several names
 *                            holding a word ("party MEPs"), nor a group for the Parliament ("European Parliament MEPs")
 *   3. name starts with the query as whole words, or contains it as a phrase; a file's name next to another act
 *      type than its own ("GDPR directive"), unless a file of that act type has the other words
 *   4. every meaningful word matches a whole word, exactly or as its singular/plural ("battery" ~ "batteries");
 *      "EU" need not match, but counts ("EU Data Act"); "MEP(s)" is "Member(s) of the European Parliament", not
 *      "Member States", and so is that phrase; the act type of a file's acts ("directive") is matched as that whole
 *      word only; two words written apart that the index has as one match as that word ("cyber security"), in
 *      people's names only when the words as typed match no one ("Chris Mac Manus": "MacManus"; "Anna Maria" is
 *      not "Annamária").
 *      Only when no document matches that way, one word may match an everyday synonym ("ai law" -> "act"), or an
 *      act type another ("USB-C regulation" -> the "directive" a file's entry has for its act).
 *      A generic word ("rules", "law") also matches through its synonyms one step below ("asylum rules" ->
 *      "asylum ... regulation"), unless the query is itself a name ("rule of law", "climate law")
 *   5. the last word matched only as the start of a longer word ("artific" -> "artificial", "Spa" -> "Spain"):
 *      in as-you-type suggestions (`typing`, 3+ letters), or on the results page when nothing matched whole words.
 *      While a last word of one or two letters matches nothing ("minimum wa"), the suggestions are those of the words
 *      before it.
 *      On the results page, legislation, topics and guides also match related forms of query words of 4+
 *      letters that are not abbreviations (typed with a capital after the first letter, in a query that is not all
 *      capitals: "AMLA regulation", "MiCA") ("fish" -> "fisheries", "farming" -> "farm", "banning" -> "ban",
 *      "trade" -> "trading", "labeled" -> "labelling"), below every whole-word match and flagged `partial` (and
 *      `wordStart` for the word starts of the fallback)
 *   6. at least one word matched only approximately (typo tolerance): a word that is not in the index matches
 *      index words within one or two edits ("migraton" -> "migration"). A word one edit from an index word is
 *      taken as a typo and its word family is not used ("packageing" is "packaging", not "package"), unless it
 *      is a regular form of index words ("travelers": "travel"); a word two edits away keeps its word family.
 *      A word family ranks above the approximate matches ("blocked": "blocking" first)
 *   7. all but one word matched exactly (queries of three or more meaningful words, name particles such as
 *      "von" or "der" and single letters not counted)
 * Tiers 6 and 7 are flagged `approximate` (with the `similar` index words of tier 6), below every other match.
 * A query that is an identifier or an act citation ("2023/0134(COD)", "COM(2016) 26", "Directive 2014/24/EU")
 * matches only through tiers 1-3, so a number fragment ("26", "2016") does not match other files; the names
 * citing the number ("... amending Regulation (EU) 2024/1689") still do. One that no file owns as typed matches
 * the identifiers it begins, up to a word boundary; while typing, an identifier no file owns yet ("2023/01")
 * completes to those it begins, and a reference whose type is not finished ("2021/0106(CO") is its number.
 * An identifier among other words ("GDPR 2016/679") ranks the file that owns it with tier 1 when that file
 * matches the other words too; an act citation naming the act type ("Council Decision No 376/2014/EU") ranks
 * the act of that type first.
 * Inside a tier: field weight (title > alias > keyword), match quality, then the static boost `w`
 * (featured dossiers, active MEPs, countries, groups), then shorter titles and newer dates.
 * People's names are not singularised ("Carlos" is not "Carlo").
 * Apostrophes do not leave one-letter words: "children's" is "children", "d'Italia" is "italia"; "S&D" is one word.
 *
 * Input conventions (pipeline/build.py): `a` = alternative names separated by " | ";
 * `x` = space-separated keywords and identifiers (multi-word keywords joined by "-"); a file's keyword
 * "regulation", "directive" or "decision" is the type of its acts.
 */
import type { SearchDoc, SearchKind } from '../types/data';
import { loadData } from './data';

export interface SearchOptions {
  kinds?: SearchKind[];
  limit?: number;
  /** As-you-type suggestions: the last word (3+ letters) may also match the start of a longer word. */
  typing?: boolean;
}

export interface SearchHit {
  doc: SearchDoc;
  score: number;
  /** Matched only through the start of a longer word or a related word form (tier 5), not through whole words. */
  partial?: boolean;
  /** With `partial`: found on the results page only because nothing matched whole words, through words starting
   * with those typed ("Spa" -> "Spain"), not through another form of a word. */
  wordStart?: boolean;
  /** Matched only approximately: through a similar word (tier 6, typo tolerance) or on all but one word (tier 7).
   * Ranked below every other match. */
  approximate?: boolean;
  /** The index words a tier-6 match has in place of a query word ("macro" for "Macron"). */
  similar?: string[];
  /** A country, group or party that the query names next to the words for MEPs ("Spanish MEPs"): the reader is
   * looking for its MEPs. */
  meps?: boolean;
}

export interface SearchEngine {
  search(query: string, opts?: SearchOptions): SearchHit[];
  size: number;
}

const SPECIAL: Record<string, string> = {
  ß: 'ss', æ: 'ae', œ: 'oe', ø: 'o', ł: 'l', đ: 'd', ð: 'd', þ: 'th', ı: 'i', ħ: 'h',
};

const APOSTROPHE = "['’‘`ʼ´]";
// "children's", "Union’s": the word itself; elided articles before a word ("d'Italia", "l’Union", "dell'Unione")
const POSSESSIVE = new RegExp(`(\\p{L})${APOSTROPHE}s(?![\\p{L}\\p{N}])`, 'gu');
const ELISION = new RegExp(`(?<![\\p{L}\\p{N}])(?:d|l|qu|n|s|j|c|m|t|dell|dall|all|nell|sull|un)${APOSTROPHE}(?=\\p{L})`, 'gu');

/** Lowercase, strip accents and punctuation (keeps "/", "(", ")" and "-" for identifiers, and "&" between letters:
 * "S&D"). A possessive "'s" and an elided article ("d'", "l'") are dropped, so they leave no one-letter words. */
export function normalize(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[ßæœøłđðþıħ]/g, (c) => SPECIAL[c] ?? c)
    // a session document number typed with another dash is the official one with a hyphen: "A10–0049/2025"
    .replace(/\b([abc]\d{1,2})[‐-―−](\d{4}\/\d{4})/g, '$1-$2')
    .replace(POSSESSIVE, '$1')
    .replace(ELISION, '')
    .replace(/[^\p{L}\p{N}/()&-]+/gu, ' ')
    .replace(/&(?!\p{L})|(?<!\p{L})&/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** A name or label as the "contains" filters of lists compare it, accent- and case-insensitively, with hyphens as
 * spaces and other punctuation kept (so that a name being typed, "Fratelli d", still matches): "García-Margallo" ->
 * "garcia margallo", "Sinn Féin" -> "sinn fein", "Dragoș" and "Dragoş" -> "dragos", "Łukasz" -> "lukasz". */
export function filterKey(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[ßæœøłđðþıħ]/g, (c) => SPECIAL[c] ?? c)
    .replace(new RegExp(APOSTROPHE, 'g'), "'")
    .replace(/[\s‐-―−-]+/g, ' ')
    .trim();
}

/** Words of a normalized string ("s&d" is one word). */
export function words(s: string): string[] {
  return normalize(s)
    .split(/[^\p{L}\p{N}&]+/u)
    .filter(Boolean);
}

/** Canonical form for identifier comparison: normalized, no spaces. */
function idKey(s: string): string {
  return normalize(s).replace(/\s+/g, '');
}

const ID_RE = /^(?:\d{4}\/\d{4}[a-z]?(?:\([a-z]{3}\))?|\d{1,4}\/\d{1,4}|\d{5}[a-z]{1,2}\d{1,4}(?:\(\d+\))?|com[/(]?\d{4}[)/]?\d+)$/;

// How official texts cite an act: "CELEX:32024R1689", "Regulation (EU) 2024/1689", "Regulation (EU) No 1316/2013",
// "Commission Implementing Decision (EU) 2024/123", "Directive 2014/24/EU", "Decision (EU, Euratom) 2020/2053";
// and as readers often write it: "EU Regulation 2016/679", "Regulation EU 2016/679", "Reg. (EU) 2016/679",
// "Dir 2019/1937", "EU 2016/679", "Regulation 2016/679 EU"
const ACT_CITATION_HEAD =
  /^(?:celex\s*)?(?:(?:eu|ec|eec)\s+)?(?:(?:commission|council)\s+)?(?:(?:implementing|delegated)\s+)?(?:(?:regulation|directive|decision|reg|dir|dec)s?\s*)?(?:\((?:eu|ec|eec|euratom)(?:\s+euratom)?\)\s*|(?:eu|ec|eec|euratom)(?:\s+euratom)?\s+)?(?:(?:no|nr|n)\s+)?/;
const ACT_CITATION_TAIL = /(\d)(?:\/(?:eu|ec|eec|euratom|jha|cfsp)(?:\s+euratom)?|\s+\(?(?:eu|ec|eec)\)?)$/;
// what follows an act's number in its official title, as copied from EUR-Lex or the Official Journal: "Regulation (EU)
// 2016/679 of the European Parliament and of the Council of 27 April 2016 on the protection of natural persons …"
const ACT_TITLE_REST = /^(.*?\d{1,4}\/\d{1,4}(?:\/[a-z]+)?(?:\s+euratom|\s+\(?(?:eu|ec|eec)\)?)?)\s+(?:of|on)\s.*$/;

/** A normalized act citation without the institutions, date and subject its official title adds after the number;
 * other text as it is ("2/2024 on Gaza" is no citation). */
export function citationHead(n: string): string {
  return ACT_CITATION_TYPE.test(n) ? n.replace(ACT_TITLE_REST, '$1') : n;
}

/** An act citation reduced to its number: "Regulation (EU) 2024/1689" -> "2024/1689". */
function bareCitation(query: string): string {
  return citationHead(normalize(query)).replace(ACT_CITATION_HEAD, '').replace(ACT_CITATION_TAIL, '$1');
}

const ELI_TYPE: Record<string, string> = { reg: 'r', dir: 'l', dec: 'd' };

/** The act an EUR-Lex or ELI address names, as its CELEX number: "https://eur-lex.europa.eu/legal-content/EN/TXT/
 * ?uri=CELEX:32016R0679" or "http://data.europa.eu/eli/reg/2016/679/oj" -> "32016r0679". */
function addressCelex(query: string): string | null {
  const celex = /\bcelex(?::|%3a)\s*(\d{5}[a-z]{1,2}\d{1,4})/i.exec(query);
  if (celex) return celex[1].toLowerCase();
  const eli = /\beli\/(reg|dir|dec)(?:_impl|_del)?\/(\d{4})\/(\d{1,4})(?![\d])/i.exec(query);
  return eli ? `3${eli[2]}${ELI_TYPE[eli[1].toLowerCase()]}${eli[3].padStart(4, '0')}` : null;
}

/** Identifier forms of a query: as typed, with an act citation reduced to its number ("2024/1689"), and the CELEX
 * number of an act's address. */
function idCandidates(query: string): string[] {
  return [...new Set([idKey(normalize(query)), idKey(bareCitation(query)), addressCelex(query) ?? ''])].filter(Boolean);
}

/** The whole query is an identifier or an act citation ("2023/0134(COD)", "COM(2016) 26", "Directive 2014/24/EU"). */
export function isIdentifier(query: string): boolean {
  return idCandidates(query).some((k) => ID_RE.test(k));
}

const CELEX_TYPE: Record<string, string> = { regulation: 'r', directive: 'l', decision: 'd', reg: 'r', dir: 'l', dec: 'd' };
const ACT_CITATION_TYPE =
  /^(?:celex\s*)?(?:(?:eu|ec|eec)\s+)?(?:(?:commission|council)\s+)?(?:(?:implementing|delegated)\s+)?(regulation|directive|decision|reg|dir|dec)s?\b/;

/** The act an act citation names, as CELEX type letter, year and number: "Council Decision No 376/2014/EU" ->
 * "d2014/376", "Directive 2014/24/EU" -> "l2014/24", "Regulation (EU) 2024/1689" -> "r2024/1689". Before 2015
 * regulations and decisions were numbered "number/year", directives "year/number". */
function citedActKeys(query: string): string[] {
  const n = citationHead(normalize(query));
  const type = ACT_CITATION_TYPE.exec(n);
  const num = /(\d{1,4})\/(\d{1,4})(?:\/[a-z]+)?(?:\s+euratom|\s+\(?(?:eu|ec|eec)\)?)?$/.exec(n);
  if (!type || !num) return [];
  const t = CELEX_TYPE[type[1]];
  const year = (s: string) => s.length === 4 && Number(s) >= 1950;
  const out: string[] = [];
  if (year(num[1])) out.push(`${t}${num[1]}/${Number(num[2])}`);
  if (year(num[2])) out.push(`${t}${num[2]}/${Number(num[1])}`);
  return out;
}

/** The act keys ("r2014/376") of a sector-3 CELEX number ("32014R0376"). */
function celexActKey(k: string): string | null {
  const m = /^3(\d{4})([rld])0*(\d+)$/.exec(k);
  return m ? `${m[2]}${m[1]}/${m[3]}` : null;
}

/** Words typed with a capital letter after the first ("AMLA regulation", "SAFE loans", "MiCA", "eIDAS"):
 * abbreviations, which are matched as whole words only. None in a query typed all in capitals ("FISH", "CHILDREN"),
 * whose letter case says nothing about its words (caps lock). */
export function typedAbbreviations(query: string): Set<string> {
  const out = new Set<string>();
  if (!/\p{Ll}/u.test(query)) return out;
  for (const raw of query.split(/[^\p{L}\p{N}&]+/u)) if (/\p{Lu}/u.test(raw.slice(1))) out.add(normalize(raw));
  return out;
}

// Name particles: not counted as matched words in tier 7, so "von der Leyen" does not find "von der Schulenburg".
const PARTICLES = new Set([
  'von', 'van', 'der', 'den', 'de', 'del', 'della', 'des', 'di', 'da', 'du', 'la', 'le', 'les', 'los', 'las', 'ten',
  'ter', 'zu', 'af',
]); // prettier-ignore

// Word families (tier 5 on the results page): a word of 4+ letters also matches longer words built on it, and
// the word without a common ending matches its other forms. The rest of the longer word must be a common ending
// or a word of its own of 6+ letters: "fish" -> "fisheries", "fishing"; "cyber" -> "cybersecurity"; "farming" ->
// "farm", "farmers"; "children" -> "child"; but "euro" not -> "european" or "eurojust", "bank" not -> "bankruptcy".
const FAMILY_IRREGULAR: Record<string, string> = { children: 'child' };
const FAMILY_STRIP = /(?:eries|ery|ings|ing|ers|er|ations|ation|ed)$/;
const FAMILY_ENDINGS = new Set([
  '', 's', 'es', 'd', 'ed', 'r', 'rs', 'er', 'ers', 'ing', 'ings', 'ery', 'eries', 'ermen', 'ren', 'ation', 'ations',
  'ion', 'ions', 'ment', 'ments', 'ness', 'ship', 'ships', 'hood', 'y', 'ies',
]); // prettier-ignore
// Names (people, parties, groups, countries) have no word families: "olive" must not find Oliver Schenk.
const FAMILY_KINDS = new Set<SearchKind>(['dossier', 'act', 'topic', 'page']);

/** The stems whose word family a query word matches: the word itself and the word without a common ending,
 * also with a doubled final consonant undone ("banning" -> "bann", "ban"; "travelled" -> "travel"). */
export function familyStems(w: string): string[] {
  const out = [w];
  const irregular = FAMILY_IRREGULAR[w];
  if (irregular) out.push(irregular);
  const s = w.replace(FAMILY_STRIP, '');
  if (s !== w && s.length >= 4) {
    out.push(s);
    if (/([b-df-hj-np-rtv-z])\1$/.test(s)) out.push(s.slice(0, -1));
  }
  return out;
}

// Other spellings of a stem before an ending, each with the only endings it takes: a final "e" after a consonant
// goes before "-ing" ("trade" -> "trading", "charge" -> "charging"), and a final "l" after a vowel is doubled
// before a verb ending, as in British spelling ("label" -> "labelling", "cancel" -> "cancellation", "fuel" ->
// "fuelled"). Not other endings: "rate" is not "rats", "national" not "nationally".
const DROP_E_ENDINGS = new Set(['ing', 'ings']);
const DOUBLE_L_ENDINGS = new Set(['ing', 'ings', 'ed', 'er', 'ers', 'ation', 'ations']);

/** The other spellings of a stem of 4+ letters before an ending, with the endings each takes. */
export function stemSpellings(stem: string): [string, Set<string>][] {
  if (stem.length < 4) return [];
  if (/[^aeiou]e$/.test(stem)) return [[stem.slice(0, -1), DROP_E_ENDINGS]];
  if (/[aeiou]l$/.test(stem)) return [[`${stem}l`, DOUBLE_L_ENDINGS]];
  return [];
}

/** Words that need not match (they carry little meaning on their own). Name particles such as "de", "la",
 * "le" or "von" are not here: "Le Pen" must not match any "pen…" word on its own. */
const STOP = new Set([
  'the', 'of', 'and', 'for', 'on', 'in', 'to', 'a', 'an', 'by', 'with', 'or', 'at', 'from', 'as', 'vs', 'versus',
]);

/** Generic everyday synonyms (curated, dossier-specific aliases come from the data). Used for at most one
 * query word, and only when no document matches all the words as typed. */
const SYNONYMS: Record<string, string[]> = {
  law: ['act', 'regulation', 'directive', 'legislation'],
  laws: ['act', 'regulation', 'directive', 'legislation'],
  legislation: ['act', 'regulation', 'directive'],
  rules: ['regulation', 'directive'],
  rule: ['regulation', 'directive'],
  ban: ['prohibition', 'prohibiting', 'prohibited'],
  eu: ['european', 'union'],
  europe: ['european'],
};

/** Generic words for a law: with another meaningful word they also match through their synonyms, one step
 * below the literal matches ("asylum rules" finds the asylum regulations, not only a file saying "rules"). */
const GENERIC = new Set(['law', 'laws', 'legislation', 'rules', 'rule']);

/** Act types, which each file's search entry carries ("directive" for a file that produced a directive): like a
 * synonym, one may stand for another when no document matches all the words as typed ("USB-C regulation" finds
 * the Directive on the common charger), but not in names ("Batteries Regulation" is not "Batteries Directive"). */
const ACT_TYPES: Record<string, string[]> = {
  regulation: ['directive', 'decision'],
  directive: ['regulation', 'decision'],
  decision: ['regulation', 'directive'],
};

/** The types of a file's acts as EUR-Lex records them, from its keywords (["regulation"]). */
export function actTypes(doc: SearchDoc): string[] {
  return doc.k === 'dossier' ? (doc.x ?? '').split(/\s+/).filter((t) => ACT_TYPES[t]) : [];
}

/** "EU" qualifies a name on a site where every file is EU legislation: like a stop word it need not match
 * ("EU GDPR", "EU Data Act"), and it ranks the files that have it higher. */
const QUALIFIERS = new Set(['eu']);

// "MEP" stands for "Member of the European Parliament", as a file's name may say ("Statute for Members of the
// European Parliament"); "Member States" is not an MEP. Next to a country, a group or a party ("Spanish MEPs",
// "MEPs from Spain", "EPP MEPs"), the words for MEPs name that country's, group's or party's MEPs.
const MEP_WORDS = new Set(['mep', 'meps']);
const MEP_QUALIFIERS = new Set(['mep', 'meps', 'member', 'members']);
const MEP_PHRASE = 'member of the european parliament';
const MEP_KINDS = new Set<SearchKind>(['country', 'group', 'party']);
// "members of the European Parliament", "members of parliament", "European Parliament members" (normalized, spaced)
const MEP_LONG = / (?:members? (?:of )?(?:the )?(?:european )?parliament|(?:european )?parliament members?) /g;
// the Parliament the MEPs sit in, which names none of its groups ("European Parliament MEPs", "MEPs in parliament")
const MEP_PARLIAMENT = / (?:members? of )?(?:the )?(?:european parliament|parliament|ep) /g;

/** The words of a text, with "members of the European Parliament" (or "members of parliament") as "meps", so that
 * "members" does not match "Member States". */
export function mepWords(text: string): string[] {
  return ` ${words(text).join(' ')} `.replace(MEP_LONG, ' meps ').split(' ').filter(Boolean);
}

/** The query asks for MEPs ("MEPs", "Spanish MEPs", "members of the European Parliament", "members of parliament"). */
export function isMepQuery(query: string): boolean {
  return mepWords(query).some((w) => MEP_WORDS.has(w));
}

// Words ending in "s" that are not plurals of a shorter word.
const NOT_PLURAL = new Set(['news', 'means', 'series', 'species', 'lens', 'goods', 'arms', 'politics', 'economics']);
// Plurals in "-es" of words in "-is"
const PLURAL_IS: Record<string, string> = {
  crises: 'crisis', analyses: 'analysis', diagnoses: 'diagnosis', hypotheses: 'hypothesis', syntheses: 'synthesis',
}; // prettier-ignore
// Plurals in "-ves" and "-oes" (a general rule would turn "directives" into "directif" and "shoes" into "sho");
// not "leaves", which is also a verb
const PLURAL_IRREGULAR: Record<string, string> = {
  wolves: 'wolf', halves: 'half', calves: 'calf', shelves: 'shelf', knives: 'knife', wives: 'wife', thieves: 'thief',
  vetoes: 'veto', embargoes: 'embargo', potatoes: 'potato', tomatoes: 'tomato', heroes: 'hero', echoes: 'echo',
  volcanoes: 'volcano',
}; // prettier-ignore
// Plurals in "-ses" of words in "-s" (a general rule would turn "cases" into "cas" and "uses" into "us")
const PLURAL_SES: Record<string, string> = {
  gases: 'gas', buses: 'bus', minibuses: 'minibus', trolleybuses: 'trolleybus', omnibuses: 'omnibus', bonuses: 'bonus',
  viruses: 'virus', statuses: 'status', censuses: 'census', prospectuses: 'prospectus', surpluses: 'surplus',
  campuses: 'campus', consensuses: 'consensus',
}; // prettier-ignore

/** Light English singular form, applied to index and query words alike: batteries -> battery, cars -> car,
 * taxes -> tax, processes -> process, crises -> crisis, wolves -> wolf, vetoes -> veto, gases -> gas. Not a full
 * stemmer: other inflections are left alone. */
export function singular(w: string): string {
  if (w.length <= 3 || /\d/.test(w) || NOT_PLURAL.has(w)) return w;
  if (PLURAL_IS[w]) return PLURAL_IS[w];
  if (PLURAL_IRREGULAR[w]) return PLURAL_IRREGULAR[w];
  if (PLURAL_SES[w]) return PLURAL_SES[w];
  if (w.endsWith('ies') && w.length > 4) return `${w.slice(0, -3)}y`;
  if (/(?:ss|sh|ch|x)es$/.test(w)) return w.slice(0, -2);
  if (w.endsWith('s') && !/(?:ss|us|is)$/.test(w)) return w.slice(0, -1);
  return w;
}

/** Meaningful words of a query for whole-word list filters (stop words dropped unless nothing else is left). */
export function keywordTokens(query: string): string[] {
  const all = words(query);
  const req = all.filter((w) => !STOP.has(w));
  return req.length ? req : all;
}

/** The words of some texts, with their singular forms, for `hasWord`. */
export function wordSet(...texts: (string | null | undefined)[]): Set<string> {
  const out = new Set<string>();
  for (const t of texts) {
    if (!t) continue;
    for (const w of words(t)) {
      out.add(w);
      out.add(singular(w));
    }
  }
  return out;
}

/** Whole-word test against a `wordSet` (singular/plural-insensitive); with `prefix` (3+ letters), the
 * token may also be the start of a longer word. */
export function hasWord(set: Set<string>, token: string, prefix = false): boolean {
  if (set.has(token) || set.has(singular(token))) return true;
  if (!prefix || token.length < 3) return false;
  for (const w of set) if (w.startsWith(token)) return true;
  return false;
}

const W_TITLE = 3;
const W_ALIAS = 2.5;
const W_KEY = 1.5;

const M_EXACT = 1;
const M_PLURAL = 0.97;
const M_SYN = 0.8;
const M_PREFIX = 0.6;
const M_FUZZY = 0.3;

const TITLE_BONUS = 500;
const ACT_TYPE_BONUS = 3000; // above any static boost: the cited act type decides between acts sharing a number

const TIER = {
  id: 1e8,
  exact: 1e7,
  starts: 5e6,
  phrase: 3e6,
  all: 1e6,
  syn: 8e5, // all words, a generic one through a synonym, while other files match literally
  prefix: 5e5,
  fuzzy: 1e5,
  partial: 1e4,
};

interface Prepared {
  doc: SearchDoc;
  title: string; // normalized words joined by spaces
  names: string[]; // title + aliases (normalized phrases)
  namesSing: string[]; // the same with every word in its singular form
  titleLen: number;
}

const singularPhrase = (phrase: string) => phrase.split(' ').map(singular).join(' ');

interface WordMatch {
  base: Map<number, number>; // doc -> best weighted quality (exact, singular/plural, or prefix)
  syn: Map<number, number>; // doc -> best weighted quality through a synonym
  fuzzy: boolean; // base holds approximate matches only
  similar: Map<number, string[]>; // with `fuzzy`: doc -> the index words it matched approximately
  typo: boolean; // with `fuzzy`: an index word is one edit away
  prefixOnly: Set<number>; // docs in `base` matched only as the start of a longer word
  formOnly: Set<number>; // of those, the docs matched only through another form of the word ("farming" -> "farm")
}

/** The scores of one pass, and the index words that tier-6 matches have in place of query words. */
interface RunResult {
  scores: Map<number, number>;
  similar: Map<number, Set<string>>; // doc -> index words it matched approximately
  typos: Set<string>; // query words that matched only approximately, one edit from an index word
  forms: Set<number>; // docs matched only partly, through another form of a word (not a word starting with it)
  meps: Set<number>; // countries, groups and parties named next to the words for MEPs
}

/** Optimal string alignment distance, bounded by `max` (returns max + 1 when exceeded). */
function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const n = b.length;
  let prev2: number[] = [];
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2] + 1);
      cur.push(v);
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[n];
}

function lowerBound(arr: string[], x: string): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The phrase with one word replaced by a synonym, e.g. ["ai", "law"] -> "ai act", "ai regulation". */
function phraseVariants(qWords: string[]): string[] {
  const out: string[] = [];
  qWords.forEach((w, k) => {
    for (const s of SYNONYMS[w] ?? []) {
      if (s !== w) out.push([...qWords.slice(0, k), s, ...qWords.slice(k + 1)].join(' '));
    }
  });
  return out.slice(0, 16);
}

/** Build a search engine over SearchDoc[] (exported for tests). */
export function createSearchEngine(docs: SearchDoc[]): SearchEngine {
  const prepared: Prepared[] = [];
  const postings = new Map<string, Map<number, number>>(); // word -> doc -> best field weight
  const byId = new Map<string, number[]>();
  const byName = new Map<string, number[]>();
  const byNameSing = new Map<string, number[]>(); // singular-form names: "battery regulation" ~ "batteries regulation"

  const post = (w: string, i: number, weight: number) => {
    let m = postings.get(w);
    if (!m) postings.set(w, (m = new Map()));
    if ((m.get(i) ?? 0) < weight) m.set(i, weight);
  };
  const add = <K>(map: Map<K, number[]>, k: K, i: number) => {
    const l = map.get(k);
    if (!l) map.set(k, [i]);
    else if (l[l.length - 1] !== i) l.push(i);
  };

  const actKeys = new Map<number, Set<string>>(); // doc -> its acts' CELEX type, year and number ("r2014/376")
  // act type ("directive") -> the files whose acts are of that type (the keyword build_search_docs adds), kept
  // out of `postings`: matched as that whole word only, never through the start, the word family or a
  // misspelling of another word ("regulated" does not find every file that produced a regulation)
  const actTypeDocs = new Map<string, Map<number, number>>();

  docs.forEach((doc, i) => {
    const titleWords = words(doc.t);
    const title = titleWords.join(' ');
    const aliases = (doc.a ?? '')
      .split('|')
      .map((s) => words(s).join(' '))
      .filter(Boolean);
    const names = [title, ...aliases];
    // a person's name has no plural: "Carlos" is not "Carlo"
    const namesSing = doc.k === 'mep' ? names : names.map(singularPhrase);
    prepared.push({ doc, title, names, namesSing, titleLen: titleWords.length });
    for (const n of names) add(byName, n, i);
    if (doc.k !== 'mep') for (const n of namesSing) add(byNameSing, n, i);
    for (const w of titleWords) post(w, i, W_TITLE);
    for (const a of aliases) for (const w of a.split(' ')) post(w, i, W_ALIAS);
    for (const raw of (doc.x ?? '').split(/\s+/)) {
      if (!raw) continue;
      if (doc.k === 'dossier' && ACT_TYPES[raw]) {
        if (!actTypeDocs.has(raw)) actTypeDocs.set(raw, new Map());
        actTypeDocs.get(raw)!.set(i, W_KEY);
        continue;
      }
      const k = idKey(raw);
      if (ID_RE.test(k)) {
        add(byId, k, i);
        // a procedure by its number, and a part of a split procedure by its number and letter ("2016/0224A")
        const num = k.match(/^(\d{4}\/\d{4})([a-z]?)\(/);
        if (num) add(byId, num[1], i);
        if (num?.[2]) add(byId, num[1] + num[2], i);
        const act = celexActKey(k);
        if (act) {
          if (!actKeys.has(i)) actKeys.set(i, new Set());
          actKeys.get(i)!.add(act);
        }
      }
      for (const w of words(raw)) post(w, i, W_KEY);
      if (raw.includes('-')) add(byName, words(raw).join(' '), i); // multi-word keyword phrase
    }
  });
  const vocab = [...postings.keys()].sort();
  const idKeys = [...byId.keys()].sort();
  // the files named after Members of the European Parliament, whom "MEP" stands for
  const mepNamed = new Map<number, number>();
  prepared.forEach((p, i) => {
    if (p.doc.k === 'mep') return;
    p.namesSing.forEach((n, k) => {
      const fw = k === 0 ? W_TITLE : W_ALIAS;
      if (` ${n} `.includes(` ${MEP_PHRASE} `) && (mepNamed.get(i) ?? 0) < fw) mepNamed.set(i, fw);
    });
  });

  /** The files with an identifier that continues `k`: at any point (`any`, while typing: "2025/013" ->
   * "2025/0134(cod)"), or after a word boundary ("2016/0224a" -> "2016/0224a(cod)", not "2016/02241"). */
  function idPrefixOwners(k: string, any: boolean): Set<number> {
    const out = new Set<number>();
    for (let j = lowerBound(idKeys, k); j < idKeys.length && idKeys[j].startsWith(k) && out.size < 400; j++) {
      const next = idKeys[j].charAt(k.length);
      if (next && (any || !/[\p{L}\p{N}]/u.test(next))) for (const i of byId.get(idKeys[j]) ?? []) out.add(i);
    }
    return out;
  }
  const bySingular = new Map<string, string[]>(); // singular form -> index words with that form
  for (const w of vocab) {
    const s = singular(w);
    const l = bySingular.get(s);
    if (l) l.push(w);
    else bySingular.set(s, [w]);
  }

  /** The index words of a stem's word family: the stem with a common ending (or one of the `endings` given), or
   * (`compounds`) with a word of its own of 6+ letters ("cyber" + "security", not "safe" + "guard"). A stem left by
   * undoing a doubled consonant ("ban", from "banning") is shorter than other stems: only it and its plural. */
  function familyWords(stem: string, compounds: boolean, endings?: Set<string>): string[] {
    const out: string[] = [];
    let n = 0;
    for (let j = lowerBound(vocab, stem); j < vocab.length && vocab[j].startsWith(stem) && n < 400; j++, n++) {
      const rest = vocab[j].slice(stem.length);
      const ending = endings ? endings.has(rest) : stem.length >= 4 ? FAMILY_ENDINGS.has(rest) : rest === '' || rest === 's';
      const compound = compounds && stem.length >= 4 && singular(rest).length >= 6 && bySingular.has(singular(rest));
      if (ending || compound) out.push(vocab[j]);
    }
    return out;
  }

  /** A word missing from the index that is a regular form of index words ("travelers": "travel", "promoted":
   * "promotion", "banning": "ban"), not a misspelling: a final "e" goes before an ending, so "packageing" is not
   * "package" + "ing". */
  const inflected = (qw: string) =>
    familyStems(qw)
      .slice(1)
      .some(
        (stem) =>
          !/[^e]e$/.test(stem) &&
          (familyWords(stem, false).length > 0 || stemSpellings(stem).some(([v, e]) => familyWords(v, false, e).length > 0)),
      );

  function wordMatches(qw: string, allowPrefix: boolean, family = false): WordMatch {
    const base = new Map<number, number>();
    const syn = new Map<number, number>();
    const whole = new Set<number>();
    const starts = new Set<number>(); // docs with a word starting with qw
    const putIn = (
      into: Map<number, number>,
      p: Map<number, number> | undefined,
      w: string,
      quality: number,
      only?: (i: number) => boolean,
    ) => {
      if (!p) return;
      for (const [i, fw] of p) {
        if (only && !only(i)) continue;
        const s = fw * quality;
        if ((into.get(i) ?? 0) < s) into.set(i, s);
        if (into === base && quality > M_PREFIX) whole.add(i);
        if (into === base && w.startsWith(qw)) starts.add(i);
      }
    };
    const put = (into: Map<number, number>, w: string, quality: number, only?: (i: number) => boolean) =>
      putIn(into, postings.get(w), w, quality, only);
    put(base, qw, M_EXACT);
    const notPerson = (i: number) => prepared[i].doc.k !== 'mep';
    for (const w of bySingular.get(singular(qw)) ?? []) if (w !== qw) put(base, w, M_PLURAL, notPerson);
    // the type of a file's acts, as the whole word ("directive", "directives"); "MEP", as the files' names say it
    const type = singular(qw);
    if (ACT_TYPES[type]) putIn(base, actTypeDocs.get(type), type, type === qw ? M_EXACT : M_PLURAL);
    if (MEP_WORDS.has(qw)) putIn(base, mepNamed, MEP_PHRASE, M_PLURAL);
    for (const s of [...(SYNONYMS[qw] ?? []), ...(ACT_TYPES[type] ?? [])]) {
      put(syn, s, M_SYN);
      putIn(syn, actTypeDocs.get(s), s, M_SYN);
    }
    if (allowPrefix) {
      let n = 0;
      for (let j = lowerBound(vocab, qw); j < vocab.length && vocab[j].startsWith(qw) && n < 400; j++, n++) {
        if (vocab[j] !== qw) put(base, vocab[j], M_PREFIX);
      }
    }
    if (family) {
      const familyDoc = (i: number) => FAMILY_KINDS.has(prepared[i].doc.k);
      for (const stem of familyStems(qw)) {
        for (const w of familyWords(stem, true)) put(base, w, M_PREFIX, familyDoc);
        for (const [v, endings] of stemSpellings(stem)) {
          for (const w of familyWords(v, false, endings)) put(base, w, M_PREFIX, familyDoc);
        }
      }
    }
    const prefixOnly = new Set([...base.keys()].filter((i) => !whole.has(i)));
    const formOnly = new Set([...prefixOnly].filter((i) => !starts.has(i)));
    const similar = new Map<number, string[]>();
    // a word of the index (if only in a person's name: "Costa", from "Costas") is not a typo
    const known = bySingular.has(singular(qw));
    if (base.size > 0 || syn.size > 0 || known || qw.length < 4 || /\d/.test(qw)) {
      return { base, syn, fuzzy: false, similar, typo: false, prefixOnly, formOnly };
    }
    const max = qw.length >= 7 ? 2 : 1;
    let typo = false;
    for (const w of vocab) {
      if (Math.abs(w.length - qw.length) > max || w[0] !== qw[0]) continue;
      const d = editDistance(qw, w, max);
      if (d <= max) {
        put(base, w, M_FUZZY);
        for (const i of postings.get(w)?.keys() ?? []) similar.set(i, [...(similar.get(i) ?? []), w]);
        if (d === 1) typo = true;
      }
    }
    // a regular form of index words is not a typo ("travelers": "travel", not only "travellers")
    if (typo && inflected(qw)) typo = false;
    return { base, syn, fuzzy: base.size > 0, similar, typo, prefixOnly, formOnly };
  }

  /** prefix: "last" = the word being typed may be the start of a longer word (suggestions); "all" = any word
   * may (results page, only once nothing matched whole words). Never for words under 3 letters. "family" (and
   * "all") = words of 4+ letters that are not abbreviations also match their word family (tier 5), except the
   * `typos` (words that the first pass took as typos of an index word). */
  function run(query: string, prefix: 'none' | 'last' | 'all' | 'family', typos?: Set<string>): RunResult {
    const qWords = words(query);
    const scores = new Map<number, number>();
    const similar = new Map<number, Set<string>>();
    const result: RunResult = { scores, similar, typos: new Set(), forms: new Set(), meps: new Set() };
    if (!qWords.length) return result;
    const phrase = qWords.join(' ');
    const phraseSing = singularPhrase(phrase);
    const lastTyped = qWords[qWords.length - 1];
    // "chat control" must not match "chatbots", "ai" must not match "air" or "aid"
    const prefixLast = (prefix === 'last' || prefix === 'all') && lastTyped.length >= 3;
    const prefixWord = (w: string) => w.length >= 3 && (prefix === 'all' || (prefix === 'last' && w === lastTyped));
    const abbreviations = typedAbbreviations(query);
    const familyWord = (w: string) =>
      (prefix === 'family' || prefix === 'all') && w.length >= 4 && !/\d/.test(w) && !abbreviations.has(w) && !typos?.has(w);
    const bump = (i: number, s: number) => {
      if ((scores.get(i) ?? -Infinity) < s) scores.set(i, s);
    };
    const boost = (i: number) => (prepared[i].doc.w ?? 1) * 400 - Math.min(prepared[i].titleLen, 40) * 2;

    // 1. identifiers; an act citation that names the act type puts the act of that type first
    const cited = citedActKeys(query);
    // while typing, a procedure reference whose type is not finished ("2021/0106(CO") is the procedure's number
    const unfinished = prefix === 'last' ? /^(\d{4}\/\d{4}[a-z]?)\([a-z]{0,3}$/.exec(idKey(query)) : null;
    // a file's id as in the site's addresses ("2023-0134", also "2023 0134") is its procedure number; other pairs
    // of numbers are not ("2021-2027")
    const dashed = /^(\d{4})[-\s](\d{4}[a-z]?)$/.exec(normalize(query));
    const fileId = dashed && byId.has(`${dashed[1]}/${dashed[2]}`) ? `${dashed[1]}/${dashed[2]}` : null;
    const candidates = [...idCandidates(query), ...(unfinished ? [unfinished[1]] : []), ...(fileId ? [fileId] : [])];
    for (const k of candidates) {
      for (const i of byId.get(k) ?? []) {
        const typed = cited.some((a) => actKeys.get(i)?.has(a)) ? ACT_TYPE_BONUS : 0;
        bump(i, TIER.id + boost(i) + typed);
      }
    }
    const owned = scores.size > 0;
    // the whole query is an identifier or an act citation: only names citing it match besides its owner, by the
    // number as cited ("2024/1689" in "Amending Regulations (EU) 2017/745 and (EU) 2024/1689"); while typing, an
    // identifier no file owns may still be unfinished ("2023/01")
    const idQuery = isIdentifier(query) || unfinished !== null || fileId !== null;
    const identifier = idQuery && (prefix !== 'last' || owned);
    let named = false; // the query is (part of) a name: "rule of law", "climate law"

    // 2-3. names (title / aliases / multi-word keywords), singular/plural-insensitive; a name after "EU" too, just
    // below ("EU GDPR", "EU Data Act")
    const namesOf = (ph: string) => new Set([...(byName.get(ph) ?? []), ...(byNameSing.get(singularPhrase(ph)) ?? [])]);
    const exactNames = (ph: string, below: number) => {
      for (const i of namesOf(ph)) {
        // after "EU", not a party's code or a person ("EU act" is not the party ACT)
        if (below && (prepared[i].doc.k === 'party' || prepared[i].doc.k === 'mep')) continue;
        const isTitle = prepared[i].namesSing[0] === (prepared[i].doc.k === 'mep' ? ph : singularPhrase(ph));
        // a topic's alias is an everyday word ("AI", "data"): it ranks with names starting with the query,
        // with the bonus of a title match
        const topicAlias = prepared[i].doc.k === 'topic' && !isTitle;
        const asTyped = prepared[i].names.includes(ph) ? 10 : 0;
        bump(i, (topicAlias ? TIER.starts : TIER.exact) + boost(i) + (isTitle || topicAlias ? 300 : 0) + asTyped - below);
        named = true;
      }
    };
    exactNames(phrase, 0);
    const unqualified = qWords.filter((w) => !QUALIFIERS.has(w)).join(' ');
    if (unqualified && unqualified !== phrase) exactNames(unqualified, 20);
    // a name that is the query after "European" or "EU", as such names are shortened ("climate law": the "European
    // Climate Law"), just below; not for one word ("council" is not the European Council)
    if (unqualified.includes(' ')) for (const q of ['european', 'eu']) exactNames(`${q} ${unqualified}`, 40);
    // the MEPs of a country, group or party ("Spanish MEPs", "MEPs from Spain", "EPP MEPs", "members of the
    // European Parliament from Greece", "Patriots for Europe MEPs"): that country, group or party, as for its name.
    // The Parliament names none of them ("European Parliament MEPs", "members of parliament" ask for all MEPs).
    if (qWords.some((w) => MEP_QUALIFIERS.has(w))) {
      const rest = (s: string) => {
        const left = s.split(' ').filter((w) => w && !MEP_QUALIFIERS.has(w));
        // stop words in a name are kept ("Socialists and Democrats"), not those around it ("MEPs from Spain")
        while (left.length && STOP.has(left[0])) left.shift();
        while (left.length && STOP.has(left[left.length - 1])) left.pop();
        return [left.join(' '), left.filter((w) => !STOP.has(w)).join(' ')];
      };
      const rests = rest(` ${phrase} `.replace(MEP_PARLIAMENT, ' ')).filter((r) => r && r !== phrase);
      // a name with the words for the Parliament in it: "The Left group in the European Parliament - GUE/NGL MEPs"
      for (const r of new Set([rest(phrase)[0], ...rests].filter(Boolean))) {
        for (const i of new Set([...namesOf(r), ...namesOf(`the ${r}`)])) {
          if (!MEP_KINDS.has(prepared[i].doc.k)) continue;
          bump(i, TIER.exact + boost(i));
          result.meps.add(i);
        }
        if (result.meps.size) break;
      }
      // or the one name holding it ("Fidesz MEPs": "Fidesz-Magyar Polgári Szövetség-…", recorded for each term); not
      // a word of several names, which names none of them ("party MEPs", "Europe MEPs")
      for (const r of result.meps.size ? [] : new Set(rests)) {
        const holding = [...prepared.keys()].filter(
          (i) => MEP_KINDS.has(prepared[i].doc.k) && prepared[i].names.some((n) => ` ${n} `.includes(` ${r} `)),
        );
        if (new Set(holding.map((i) => prepared[i].title)).size !== 1) continue;
        for (const i of holding) {
          bump(i, TIER.starts + boost(i));
          result.meps.add(i);
        }
        break;
      }
    }
    // synonym variants of the whole phrase ("ai law" -> "ai act"), just below exact names
    if (qWords.length <= 4) {
      for (const v of phraseVariants(qWords)) {
        for (const i of byName.get(v) ?? []) bump(i, TIER.starts + 100 + boost(i));
      }
    }
    if (phrase.length >= 2) {
      prepared.forEach((p, i) => {
        let best = 0;
        for (const [k, n] of p.names.entries()) {
          const fw = k === 0 ? 300 : 200;
          const ns = p.namesSing[k];
          const ps = p.doc.k === 'mep' ? phrase : phraseSing; // a person's name has no plural
          if (n.startsWith(phrase + ' ') || ns.startsWith(ps + ' ')) {
            best = Math.max(best, TIER.starts + fw);
          } else if (phrase.length >= 3 && (` ${n} `.includes(` ${phrase} `) || ` ${ns} `.includes(` ${ps} `))) {
            best = Math.max(best, TIER.phrase + fw);
          } else if (prefixLast && n.length > phrase.length && n.startsWith(phrase)) {
            best = Math.max(best, TIER.prefix + fw); // "spa" -> "spain"
          }
        }
        if (best) bump(i, best + boost(i));
        if (best >= TIER.phrase) named = true;
      });
    }
    if (idQuery) {
      // an act citation: also the names citing the act by its number ("Regulation 2024/1689" finds "... (EU) 2024/1689"),
      // while it is typed too ("EU Regulation No 1316/2013")
      const bare = words(bareCitation(query)).join(' ');
      if (bare !== phrase) {
        prepared.forEach((p, i) => {
          const k = p.names.findIndex((n) => ` ${n} `.includes(` ${bare} `));
          if (k >= 0) bump(i, TIER.phrase + (k === 0 ? 300 : 200) + boost(i));
        });
      }
      if (identifier && owned) return result;
    }
    if (idQuery) {
      // an identifier no file owns as typed: the files whose identifiers start with it, up to a word boundary
      // ("2016/0224 A" -> "2016/0224A(COD)"), or anywhere while it is being typed ("2025/013" -> "2025/0134(COD)");
      // never files that only share some of its numbers ("COM(2008) 40" is not "Directive 2008/115/EC ... COM(2025)0101")
      const tier = prefix === 'last' ? TIER.prefix : TIER.starts;
      for (const k of candidates) for (const i of idPrefixOwners(k, prefix === 'last')) bump(i, tier + boost(i));
      return result;
    }

    // 4-7. words; "EU" next to other words need not match, like a stop word, but counts as one ("eu" or "european");
    // "members of the European Parliament" is "MEPs", not "Member States" and "European Parliament" anywhere
    const wq = mepWords(query);
    const meaningful = wq.filter((w) => !STOP.has(w));
    const required = meaningful.some((w) => !QUALIFIERS.has(w)) ? meaningful.filter((w) => !QUALIFIERS.has(w)) : meaningful;
    const req = required.length ? required : wq;
    const per = req.map((w) => wordMatches(w, prefixWord(w), familyWord(w)));
    const optional = wq
      .filter((w) => required.length && !required.includes(w))
      .map((w) => wordMatches(w, false))
      .map((m) => new Map([...m.syn, ...m.base]));
    const extra = (i: number) => optional.reduce((acc, m) => acc + (m.get(i) ?? 0) * 0.2, 0);

    // every word matched as typed (whole word, singular/plural, prefix of the last word, or typo)
    const full = (expand: number, tier = TIER.all): number => {
      let n = 0;
      const [first, ...rest] = per.map((m, k) => (k === expand ? new Map([...m.syn, ...m.base]) : m.base));
      for (const [i, s0] of first) {
        let sum = s0;
        let ok = true;
        for (const m of rest) {
          const s = m.get(i);
          if (s === undefined) {
            ok = false;
            break;
          }
          sum += s;
        }
        if (!ok) continue;
        n++;
        const fuzzy = per.some((m) => m.fuzzy);
        const partial = per.some((m, k) => m.prefixOnly.has(i) && !(k === expand && m.syn.has(i)));
        if (partial && per.some((m, k) => m.formOnly.has(i) && !(k === expand && m.syn.has(i)))) result.forms.add(i);
        // every word is a whole word of the title ("battery" in "Batteries and waste batteries")
        const inTitle = per.every((m) => (m.base.get(i) ?? 0) >= W_TITLE * M_PLURAL) ? TITLE_BONUS : 0;
        bump(i, (fuzzy ? TIER.fuzzy : partial ? TIER.prefix : tier) + (sum + extra(i)) * 100 + inTitle + boost(i));
        if (fuzzy) {
          const set = similar.get(i) ?? new Set<string>();
          for (const m of per) for (const w of m.similar.get(i) ?? []) set.add(w);
          similar.set(i, set);
        }
      }
      return n;
    };
    per.forEach((m, k) => {
      if (m.fuzzy && m.typo) result.typos.add(req[k]);
    });
    let anyFull = full(-1) > 0;
    // no document has all the words: let one word match a synonym ("ai law" -> "act"), never two at once
    if (!anyFull) {
      per.forEach((m, k) => {
        if (m.syn.size && full(k) > 0) anyFull = true;
      });
    } else if (!named && req.some((w) => !GENERIC.has(w))) {
      // a generic word next to a subject word also matches through its synonyms, below the literal matches:
      // "asylum rules" finds the asylum regulations, not only the one file that says "rules"
      per.forEach((m, k) => {
        if (m.syn.size && GENERIC.has(req[k])) full(k, TIER.syn);
      });
    }

    // a file's name and another act type than its own ("GDPR directive", "simplification omnibus regulation"):
    // the file named ranks first, above files that only happen to mention both words ("... GDPR reform ...
    // Directives 2002/58/EC ..."), unless a file whose act is of that type has the name in its own ("packaging
    // waste directive": "... Directive 94/62/EC on packaging and packaging waste"); then it is listed after the
    // literal matches. Of the files named, those matching all the words come first.
    const typeAt = req.findIndex((w) => ACT_TYPES[singular(w)]);
    if (typeAt >= 0 && req.length > 1) {
      const rest = qWords.filter((w) => w !== req[typeAt]);
      const name = rest.join(' ');
      const bare = rest.filter((w) => !QUALIFIERS.has(w)).join(' ');
      const phrases = [...new Set([name, bare].filter(Boolean).map(singularPhrase))];
      const ofType = [...(actTypeDocs.get(singular(req[typeAt]))?.keys() ?? [])];
      const hasName = (i: number) => prepared[i].namesSing.some((n) => phrases.some((ph) => ` ${n} `.includes(` ${ph} `)));
      const literal = ofType.some(hasName);
      for (const i of new Set([...namesOf(name), ...(bare && bare !== name ? namesOf(bare) : [])])) {
        if (prepared[i].doc.k !== 'dossier') continue;
        const all = (scores.get(i) ?? 0) >= TIER.all ? 100 : 0;
        bump(i, (literal ? TIER.syn : TIER.phrase) + boost(i) + all);
      }
    }

    // an identifier among other words ("GDPR 2016/679"): the file it identifies, when it matches the other
    // words too, ranks with the identifier matches, above files that only mention the number
    const tokens = normalize(query).split(' ');
    if (tokens.length > 1) {
      for (const t of tokens) {
        const k = idKey(t);
        if (!ID_RE.test(k)) continue;
        for (const i of byId.get(k) ?? []) {
          const s = scores.get(i) ?? 0;
          if (s >= TIER.all && s < TIER.id) bump(i, TIER.id + boost(i));
        }
      }
    }

    // all but one word: name particles and single letters do not count ("von der Leyen" is not "von der
    // Schulenburg", "Plan B rules" is not every file with a "b")
    const counted = (w: string) => !PARTICLES.has(w) && w.length > 1;
    const content = req.filter(counted);
    if (!anyFull && scores.size === 0 && content.length >= 3) {
      const counts = new Map<number, { exactN: number; sum: number }>();
      per.forEach(({ base, fuzzy, prefixOnly }, k) => {
        if (fuzzy || !counted(req[k])) return;
        for (const [i, s] of base) {
          if (s < W_KEY * M_PLURAL || prefixOnly.has(i)) continue;
          const c = counts.get(i) ?? { exactN: 0, sum: 0 };
          c.exactN += 1;
          c.sum += s;
          counts.set(i, c);
        }
      });
      for (const [i, c] of counts) {
        if (c.exactN >= content.length - 1) bump(i, TIER.partial + c.sum * 100 + boost(i));
      }
    }
    return result;
  }

  /** The query with two words written apart that the index has as one ("cyber security" -> "cybersecurity", "eco
   * design" -> "ecodesign"), each pair on its own, and with a word and a number written together that the index
   * has apart ("euro7" -> "euro 7", "covid19" -> "covid 19"); none for an identifier. */
  function joinedForms(query: string): string[] {
    if (isIdentifier(query)) return [];
    const ws = words(query);
    const part = (w: string) => w.length >= 3 && !STOP.has(w) && !PARTICLES.has(w) && !/\d/.test(w);
    const out: string[] = [];
    for (let k = 0; k + 1 < ws.length && out.length < 2; k++) {
      const joined = ws[k] + ws[k + 1];
      if (part(ws[k]) && part(ws[k + 1]) && joined.length >= 7 && bySingular.has(singular(joined))) {
        out.push([...ws.slice(0, k), joined, ...ws.slice(k + 2)].join(' '));
      }
    }
    const split = ws.map((w) => (bySingular.has(w) ? w : w.replace(/^(\p{L}{3,})(\d{1,4})$/u, '$1 $2')));
    if (split.some((w, k) => w !== ws[k])) out.push(split.join(' '));
    return out;
  }

  /** `run` on the query and on its joined forms, each document with its best score; a person's name only as typed
   * when the query as typed matches a person ("Anna Maria" is not "Annamária"), otherwise also joined ("Chris Mac
   * Manus": "Chris MacManus"). */
  function runForms(query: string, forms: string[], prefix: Parameters<typeof run>[1], typos?: Set<string>): RunResult {
    const res = run(query, prefix, typos);
    const people = [...res.scores.keys()].some((i) => prepared[i].doc.k === 'mep');
    for (const f of forms) {
      const r = run(f, prefix, typos);
      for (const [i, s] of r.scores) {
        if ((res.scores.get(i) ?? -Infinity) >= s || (people && prepared[i].doc.k === 'mep')) continue;
        res.scores.set(i, s);
        if (r.similar.has(i)) res.similar.set(i, r.similar.get(i)!);
        else res.similar.delete(i);
        if (r.forms.has(i)) res.forms.add(i);
        else res.forms.delete(i);
      }
      for (const i of r.meps) res.meps.add(i);
      for (const w of r.typos) res.typos.add(w);
    }
    return res;
  }

  function search(query: string, opts: SearchOptions = {}): SearchHit[] {
    const limit = opts.limit ?? 50;
    const kinds = opts.kinds?.length ? new Set(opts.kinds) : null;
    const forms = joinedForms(query);
    let res = runForms(query, forms, opts.typing ? 'last' : 'none');
    if (opts.typing && res.scores.size === 0 && !isIdentifier(query)) {
      // a last word too short to be the start of a longer word ("minimum wa", "Fratelli d'It"): the suggestions of
      // the words before it, so that the list does not disappear while the word is typed; not "EU" alone ("EU-US")
      const ws = words(query);
      const before = ws.slice(0, -1);
      if (/^\p{L}{1,2}$/u.test(ws[ws.length - 1]) && before.some((w) => !STOP.has(w) && !QUALIFIERS.has(w))) {
        return search(before.join(' '), opts);
      }
    }
    let fallback = false;
    // an identifier matches only as such (tiers 1-3): no word starts, no word families
    if (!opts.typing && !isIdentifier(query)) {
      // nothing matched whole words: fall back to words starting with those typed ("pharma package")
      if (res.scores.size === 0) {
        res = runForms(query, forms, 'all');
        fallback = true;
      } else {
        // related word forms, below every whole-word match: "fish" -> "fisheries", "farming" -> "farm"; not of
        // a word that is a typo of an index word ("packageing": "packaging", not "package"); a form also ranks
        // above the same file's approximate match ("labeling": "labelling")
        for (const [i, s] of runForms(query, forms, 'family', res.typos).scores) {
          if ((res.scores.get(i) ?? 0) < s && s >= TIER.prefix && s < TIER.syn) res.scores.set(i, s);
        }
      }
    }

    const hits: SearchHit[] = [];
    for (const [i, score] of res.scores) {
      const doc = prepared[i].doc;
      if (kinds && !kinds.has(doc.k)) continue;
      const hit: SearchHit = { doc, score };
      if (score >= TIER.prefix && score < TIER.syn) {
        hit.partial = true;
        if (fallback && !res.forms.has(i)) hit.wordStart = true;
      }
      if (score < TIER.prefix) {
        hit.approximate = true;
        const similar = res.similar.get(i);
        if (similar?.size) hit.similar = [...similar];
      }
      if (res.meps.has(i)) hit.meps = true;
      hits.push(hit);
    }
    hits.sort(
      (a, b) =>
        b.score - a.score ||
        (b.doc.d ?? '').localeCompare(a.doc.d ?? '') ||
        a.doc.t.localeCompare(b.doc.t) ||
        a.doc.id.localeCompare(b.doc.id),
    );
    return hits.slice(0, limit);
  }

  return { search, size: docs.length };
}

/** The similar words of approximate hits (`SearchHit.similar`), in the order of the hits given (best match
 * first), so that a summary names the words of the first results shown. */
export function similarWords(lists: Iterable<string[] | undefined>, max = 3): string[] {
  const out: string[] = [];
  for (const l of lists) {
    for (const w of l ?? []) {
      if (out.length >= max) return out;
      if (!out.includes(w)) out.push(w);
    }
  }
  return out;
}

export interface QueryPart {
  /** The words of the part, as typed. */
  text: string;
  /** Its best whole-word matches on its own. */
  hits: SearchHit[];
}

/** A query of several words that matches nothing as a whole, cut into the longest runs of words that each match
 * something through whole words on their own ("NIS2 Ireland": "NIS2" and "Ireland"; "NIS 2 Ireland": "NIS 2" and
 * "Ireland"). Stop words and name particles are no part on their own ("von der Leyen" is not "von der
 * Schulenburg"). A part that matches nothing that way (a misspelling, or only the start of longer words: "Pen")
 * has no hits. Null for one word, an identifier, or more than five words. */
export function queryParts(engine: SearchEngine, query: string, limit = 3): QueryPart[] | null {
  if (isIdentifier(query)) return null;
  const counts = (text: string) => words(text).some((w) => !STOP.has(w) && !PARTICLES.has(w));
  const stop = (token: string) => words(token).every((w) => STOP.has(w));
  const tokens = query.trim().split(/\s+/);
  if (tokens.filter(counts).length < 2 || tokens.length > 5) return null;
  const parts: QueryPart[] = [];
  let taken = 0; // the tokens before this one are in a part
  for (let i = 0; i < tokens.length; ) {
    let part: QueryPart | null = null;
    let end = i + 1;
    for (let j = i === 0 ? tokens.length - 1 : tokens.length; j > i && !part; j--) {
      const text = tokens.slice(i, j).join(' ');
      if (!counts(text) || stop(tokens[i]) || stop(tokens[j - 1])) continue;
      const hits = engine
        .search(text, { limit: limit + 20 })
        .filter((h) => !h.partial && !h.approximate)
        .slice(0, limit);
      if (hits.length) {
        part = { text, hits };
        end = j;
      }
    }
    if (!part && counts(tokens[i])) {
      // nothing on its own: shown with the name particles typed before it ("Le Pen")
      let k = i;
      while (k > taken && !counts(tokens[k - 1]) && !stop(tokens[k - 1])) k--;
      part = { text: tokens.slice(k, i + 1).join(' '), hits: [] };
    }
    if (part) {
      parts.push(part);
      taken = end;
    }
    i = end;
  }
  return parts;
}

/** Dossier ids matched by the engine, with scores normalised to (0..1], in the engine's order. The legislation
 * explorer and the votes list use this so that their keyword matches agree with the search page. `partial`
 * collects the ids matched only through related word forms or word starts (`wordStart` those of them matched
 * through words starting with those typed), `approximate` those matched only approximately (with their similar
 * words); `wholeWords` leaves both out; `identifiers` keeps only the matches on an identifier or on a name holding
 * the query as a phrase (a number: a title citing "Directive (EU) 2022/2464"). */
export function dossierScores(
  engine: SearchEngine,
  query: string,
  opts: {
    wholeWords?: boolean;
    identifiers?: boolean;
    partial?: Set<string>;
    wordStart?: Set<string>;
    approximate?: Map<string, string[]>;
  } = {},
): Map<string, number> {
  const m = new Map<string, number>();
  if (!query.trim()) return m;
  let hits: SearchHit[];
  try {
    hits = engine.search(query, { kinds: ['dossier'], limit: 5000 });
  } catch {
    return m;
  }
  const max = hits[0]?.score || 1;
  for (const h of hits) {
    if (opts.wholeWords && (h.partial || h.approximate)) continue;
    if (opts.identifiers && h.score < TIER.phrase) continue;
    const fromUrl = /^\/legislation\/([^/?#]+)/.exec(h.doc.u)?.[1];
    const id = fromUrl ? decodeURIComponent(fromUrl) : h.doc.id;
    if (!m.has(id)) {
      m.set(id, h.score / max);
      if (h.partial) opts.partial?.add(id);
      if (h.wordStart) opts.wordStart?.add(id);
      if (h.approximate) opts.approximate?.set(id, h.similar ?? []);
    }
  }
  return m;
}

let engine: Promise<SearchEngine> | null = null;

/** Load search.json once and build the engine (cached; retried after a failure). */
export function loadSearch(): Promise<SearchEngine> {
  engine ??= loadData<SearchDoc[]>('search.json').then(createSearchEngine);
  engine.catch(() => {
    engine = null;
  });
  return engine;
}
