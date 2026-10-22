"""European Parliament plenary votes with individual roll-call ballots (EP Open Data API v2).

Produces data/snapshot/ep_votes/votes.json (list[EpVote]) for every recorded plenary vote of the 9th and
10th terms (sittings from 2019-07-02 to today) and ballots.json (list[EpBallots]) with the individual
positions of roll-call votes on whole texts (kind final / resolution / motion; see BALLOT_KINDS).

Requests (about 2 per sitting plus ~30 for procedure references; paced for the API's limit of 500
requests / 5 min per endpoint, which is shared with the other EP sources):
    /meetings?year=Y                         plenary sittings (PLENARY_SITTING, with parliamentary_term)
    /meetings/{sitting}/decisions            every decision of the sitting (all pages in one response;
                                             `limit`/`offset` are ignored by this endpoint)
    /meetings/{sitting}/vote-results         vote items ("PLENARY_VOTE_RESULTS", one per agenda item)
    /procedures?process-type=T               process id -> official reference "2021/0106(COD)"
    /plenary-documents/{doc}                 fallback only: document -> procedure that created it

Source facts relied on (checked against the live API; see tests/test_ep_votes.py and fixtures):
- Two record formats. From 2024-01-15 every decision (show of hands, electronic, roll-call) is published
  with decision_outcome, referenceText, decided_on_a_realization_of (amendment documents "…-AM-102",
  split parts "…-SPLIT-1-2"), decisionAboutId, comment codes ("RCV", "sep", "2/RCV"), headingLabel and
  inverse_consists_of -> the vote item. Before that date the API only has roll-call votes, without an
  outcome, without document ids and without a link to the vote item; their English label reads
  "A9-0188/2023 - Brando Benifei - Am 808 13/03/2024 12:14:17.000" (some labels exist only in French).
- A vote item lists the procedure(s) it belongs to in inverse_consists_of ("eli/dl/proc/2021-0106") and
  the document(s) it is based on (based_on_a_realization_of: report A-9-2023-0188, motions B-9-…).
- The provisional agreement of a trilogue is tabled as one amendment ("Am 808", document …-AM-808) with
  referenceText "Provisional agreement": it is the final vote, not an amendment.

Procedure links (EpVote.procedure_refs) are made only through official identifiers, in this order:
  1. new format: decision -> vote item (inverse_consists_of) -> procedures of that item;
  2. old format: the document reference that opens the label ("A9-0188/2023", "RC-B9-0118/2019") is the
     exact id of a document the sitting's vote item is based on -> that item's procedures; a joint motion
     (RC) is matched through the motions it replaces (document is_derivative_of, via /plenary-documents);
     a procedure reference written in the label itself ("… (2020/0060(COD))") is also used;
  3. otherwise the base document of the vote (amendment/split document, label or heading reference) is
     looked up with /plenary-documents/{doc} -> inverse_created_a_realization_of (the procedure).
Unresolvable votes keep procedure_refs = [] (never matched by title).

Vote kind (EpVote.kind) — see classify(). Signals: referenceText / label tail (whole-text markers such as
"Provisional agreement", "Commission proposal", "Single vote", "Motion for a resolution (as a whole)"),
document ids (-AM- = amendment, -SPLIT- without -AM- = split vote on the original text), decisionAboutId
("§" = part of the original text), comment ("sep" = separate vote; digits = part of a split vote), the
vote item title (objections, motions of censure, "***II" second reading) and the procedure type of the
linked procedure (legislative types make "motion for a resolution" the legislative resolution).

Majority rule (EpVote.majority_rule) — see majority_rule(). Set only where the Treaty text fixes it for
that kind of vote; everything else stays "unknown". Abstentions are not votes cast (Rule 178(3) RoP as
quoted in CJEU C-650/18 Hungary v Parliament, ECLI:EU:C:2021:426, paras 7 and 89 ff.).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pipeline.http import EP_API, Http, HttpError
from pipeline.models.entities import EpBallots, EpVote, SourceRef, SourceStatus, VoteKind
from pipeline.snapshot import now_iso, write_records

log = logging.getLogger("pipeline.sources.ep_votes")

SOURCE_ID = "ep_votes"
FMT = {"format": "application/ld+json"}
FIRST_SITTING = "2019-07-02"  # first sitting of the 9th term
RICH_FORMAT_FROM = "2024-01-15"  # first sitting whose decisions carry outcome, documents and vote items
WORKERS = 2  # the API is shared with other sources and allows 500 requests / 5 min per endpoint
MIN_GAP_S = 2.5  # per worker, between two requests that actually hit the network (<= 0.8 req/s)
FRESH_DAYS = 30  # sittings this recent are always re-fetched (late corrections, newly published votes)
PROCESS_TYPES = (
    "ACI APP AVC BUD CNS COD DEC NLE SYN BUI COS DEA DCE IMM INI INL INS REG RPS RSO RSP GBD".split()
)
# Roll-call votes on a whole text keep their individual ballots (all roll-calls would be ~150 MB).
BALLOT_KINDS: frozenset[str] = frozenset({"final", "resolution", "motion"})


# ============================================================================================ fetching
class _Pacer:
    """Keeps each worker under MIN_GAP_S between network requests; cache hits are not slowed down."""

    def __init__(self, gap_s: float):
        self.gap_s = gap_s
        self._local = threading.local()

    def get(self, http: Http, url: str, **kw: Any) -> bytes:
        last = getattr(self._local, "last", 0.0)
        wait = self.gap_s - (time.monotonic() - last)
        t0 = time.monotonic()
        body = http.get(url, **kw)
        if time.monotonic() - t0 > 0.05:  # went to the network (cache hits return in ~1 ms)
            if wait > 0:
                time.sleep(wait)
            self._local.last = time.monotonic()
        return body


_PACER = _Pacer(MIN_GAP_S)


def _get_data(http: Http, path: str, *, use_cache: bool = True, **params: Any) -> list[dict]:
    """GET an API resource's `data`; 204 (no content) and 404 (unknown id) mean "no records"."""
    body = _PACER.get(
        http, f"{EP_API}{path}", params={**FMT, **params}, use_cache=use_cache, ok_statuses=(200, 204, 404)
    )
    if not body:
        return []
    try:
        d = json.loads(body)
    except ValueError:
        return []  # 404 pages are JSON too, but be defensive
    data = d.get("data", []) if isinstance(d, dict) else []
    return data if isinstance(data, list) else []


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def list_sittings(http: Http, today: str | None = None) -> list[dict]:
    """Plenary sittings of the 9th and 10th terms up to today: [{id, date, term}] sorted by date."""
    today = today or _today()
    out: dict[str, dict] = {}
    for year in range(int(FIRST_SITTING[:4]), int(today[:4]) + 1):
        offset, page = 0, 100
        while True:
            rows = _get_data(
                http, "/meetings", year=year, offset=offset, limit=page, use_cache=year < int(today[:4])
            )
            for r in rows:
                sid = r.get("activity_id") or _suffix(r.get("id")) or ""
                term = (_suffix(r.get("parliamentary_term")) or "").rsplit("-", 1)[-1]
                day = sid[7:17]  # MTG-PL-YYYY-MM-DD
                if r.get("had_activity_type") != "def/ep-activities/PLENARY_SITTING" or not term.isdigit():
                    continue
                if FIRST_SITTING <= day <= today and int(term) >= 9:
                    out[sid] = {"id": sid, "date": day, "term": int(term)}
            if len(rows) < page:
                break
            offset += page
    return sorted(out.values(), key=lambda s: s["id"])


def fetch_sitting(http: Http, sitting: dict, today: str | None = None) -> tuple[list[dict], list[dict]]:
    """(decisions, vote items) of one sitting, as returned by the API."""
    today = today or _today()
    fresh = date.fromisoformat(sitting["date"]) >= date.fromisoformat(today) - timedelta(days=FRESH_DAYS)
    decisions = _get_data(http, f"/meetings/{sitting['id']}/decisions", use_cache=not fresh)
    items = _get_data(http, f"/meetings/{sitting['id']}/vote-results", use_cache=not fresh)
    return decisions, items


def fetch_procedure_labels(http: Http) -> dict[str, str]:
    """EP process id ("2021-0106") -> official reference ("2021/0106(COD)") for every EP procedure."""
    out: dict[str, str] = {}
    for ptype in PROCESS_TYPES:
        offset, page = 0, 1000
        while True:
            rows = _get_data(http, "/procedures", **{"process-type": ptype}, offset=offset, limit=page)
            for r in rows:
                if r.get("process_id") and r.get("label"):
                    out[r["process_id"]] = r["label"]
            if len(rows) < page:
                break
            offset += page
    return out


LOOKUP_SERIES = ("A-", "B-", "RC-")  # plenary documents; C-documents are not served (404)


def fetch_document_links(http: Http, doc_id: str) -> tuple[list[str], list[str]]:
    """(process ids that created the document, documents it derives from) via /plenary-documents.

    `language=en` keeps the response small (~15 KB instead of up to ~650 KB with every amendment in all
    languages) without dropping inverse_created_a_realization_of / is_derivative_of.
    """
    try:
        rows = _get_data(http, f"/plenary-documents/{doc_id}", language="en")
    except HttpError as e:  # the endpoint answers 500 for some ids; treat as "no information"
        log.warning("document %s: %s", doc_id, e)
        return [], []
    procs: list[str] = []
    derived: list[str] = []
    for r in rows:
        procs += [
            p.rsplit("/", 1)[-1] for p in _ids(r.get("inverse_created_a_realization_of")) if "/proc/" in p
        ]
        derived += [_suffix(d) or d for d in _ids(r.get("is_derivative_of"))]
    return sorted(set(procs)), sorted(set(derived))


# ============================================================================================= parsing
def _suffix(uri: Any) -> str | None:
    if not isinstance(uri, str) or not uri:
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _ids(v: Any) -> list[str]:
    """Normalise a JSON-LD reference field (str | dict | list of either) to a list of id strings."""
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    out = []
    for x in v:
        if isinstance(x, dict):
            x = x.get("id")
        if isinstance(x, str) and x:
            out.append(x)
    return out


def _text(v: Any, langs: tuple[str, ...] = ("en", "mul", "fr")) -> str | None:
    """English text of a multilingual field (falls back to mul, fr, then any language)."""
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, list):
        return _text(v[0], langs) if v else None
    if not isinstance(v, dict):
        return None
    for lang in langs:
        x = v.get(lang)
        if isinstance(x, list):
            x = x[0] if x else None
        if isinstance(x, str) and x.strip():
            return x.strip()
    for x in v.values():
        if isinstance(x, str) and x.strip():
            return x.strip()
    return None


def _committee(v: Any) -> str | None:
    """Committee code from responsible_organization_label, the "Author" column of the voting list.

    That column also names political groups ("The Left", "PPE"), "Members", "original text" or the generic
    "committee"; only a single EP committee code ("INTA", "ENVI") is kept.
    """
    text = _text(v, ("en",)) if isinstance(v, dict) and v.get("en") else None
    return text if text and re.fullmatch(r"[A-Z]{4}", text) else None


TIMESTAMP_RE = re.compile(r"\s+\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?\s*$")
# Official document references as printed: A9-0188/2023, B10-0424/2026, RC-B9-0163/2024, C9-0146/2021
DOC_REF_RE = re.compile(r"\b(RC-B|A|B|C)(\d{1,2})-(\d{4})/(\d{4})\b")
PROC_REF_RE = re.compile(r"\b(\d{4})/(\d{4})\(([A-Z]{3})\)")
SYMBOL_RE = re.compile(r"(\*{1,3})(I{1,3})?\s*$")


def doc_ref_to_id(ref: str) -> str | None:
    """'A9-0188/2023' -> 'A-9-2023-0188'; 'RC-B9-0163/2024' -> 'RC-9-2024-0163' (EP document ids)."""
    m = DOC_REF_RE.fullmatch(ref.strip())
    if not m:
        return None
    series, term, num, year = m.groups()
    return f"{'RC' if series == 'RC-B' else series}-{term}-{year}-{num}"


def base_doc(doc_id: str) -> str | None:
    """Base document of an amendment/part id: 'A-9-2024-0042-AM-102' -> 'A-9-2024-0042'."""
    m = re.match(r"^((?:RC|A|B|C)-\d{1,2}-\d{4}-\d{4})(?:-|$)", doc_id)
    return m.group(1) if m else None


def clean_label(label: str | None) -> str | None:
    if not label:
        return None
    return TIMESTAMP_RE.sub("", label).strip() or None


@dataclass
class VoteItem:
    """A PLENARY_VOTE_RESULTS item: one agenda item's votes (e.g. 'Artificial Intelligence Act ***I')."""

    id: str
    title: str | None
    procs: list[str] = field(default_factory=list)  # EP process ids, e.g. "2021-0106"
    docs: list[str] = field(default_factory=list)  # document ids the item is based on

    @property
    def symbol(self) -> str | None:
        """Procedure symbol at the end of the title: '*' consultation, '***' consent, '***I/II/III' COD."""
        m = SYMBOL_RE.search(self.title or "")
        return m.group(0).replace(" ", "") if m else None


def index_items(items: list[dict]) -> dict[str, VoteItem]:
    out: dict[str, VoteItem] = {}
    for x in items:
        if x.get("had_activity_type") != "def/ep-activities/PLENARY_VOTE_RESULTS":
            continue
        iid = x.get("activity_id") or _suffix(x.get("id"))
        if not iid:
            continue
        procs = [p.rsplit("/", 1)[-1] for p in _ids(x.get("inverse_consists_of")) if "/proc/" in p]
        docs = [_suffix(d) or d for d in _ids(x.get("based_on_a_realization_of"))]
        out[iid] = VoteItem(id=iid, title=_text(x.get("activity_label")), procs=sorted(set(procs)), docs=docs)
    return out


# ====================================================================================== classification
# Whole-text markers: referenceText (new format) or the last label segment (old format), English + French.
_FINAL = re.compile(
    r"^(provisional agreement|commi\w*on proposals?|proposal for an? (regulation|directive|decision|council)|"
    r"draft (european council|council|legislative|regulation|decision|implementing|joint)|council (draft|"
    r"position)|joint (text|proposal)|single vote|vote unique|consent( procedure)?|approval procedure|"
    r"procédure d.approbation|proposition de la commi\w+|proposition de (règlement|directive|décision)|"
    r"propositions? de décisions?|proposals? for (a )?decisions?|motion for a decision|decision( to refuse "
    r"discharge)?|election of the commission|proposal from the commission|nomination|appointment|"
    r"(final vote|vote final))(?![a-z])",
    re.I,
)
_RESOLUTION = re.compile(
    r"^((vote: )?(joint |alternative )?(motion|proposal|proposition) for (a )?resolution|motion for resolution|"
    r"(vote: )?(proposition de |projet de )?résolution|(vote: )?resolution|(draft |proposal for a |projet de )?"
    r"(recommendation|recommandation)|text as a whole|as a whole|texte dans son ensemble)(?![a-z])",
    re.I,
)
_PROCEDURAL = re.compile(
    r"(referr?al|refer(red)? back|renvoi|request for urgen|urgent procedure|urgency procedure|agenda\b|ordre du "
    r"jour|adjourn|procedural motion|interinstitutional negotiations|request to vote on the amendments|"
    r"request \(rule|demande du groupe|requests? (from|by) (the )?\S+ groups?|group request|postpone|"
    r"inadmissib|request for (the )?amendments|urgent decision)",
    re.I,
)
# Old labels that are procedural by their opening words ("Wednesday's agenda – …", "Request for urgent …")
_PROCEDURAL_LABEL = re.compile(
    r"^((\S+[’']s )?agenda\b|agenda for|ordre du jour|demande d.application de la procédure d.urgence|"
    r"request for urgen|urgent procedure)",
    re.I,
)
_REJECTION = re.compile(r"(reject|rejet|motion of censure|motion de censure)", re.I)
_PART = re.compile(
    r"^((after|before) )?(§|recital|citation|visa|article|annex|point|paragraph|title|heading|subheading|"
    r"sous-titre|chapter|part|section|considérant|line|table|indent|(directive|regulation) (\(\w+\) )?(no )?\d)"
    r"(?![a-z])",
    re.I,
)
_AMENDMENT_TAIL = re.compile(r"^(am|ams|amendments?|block|bloc|budget line|vote en bloc)(?![a-z])", re.I)
_BUDGET_LINE = re.compile(r"^(?:\d{1,2}(?: \d{1,2}){1,4}|[O0]\d(?: \d{2}){1,3})$")  # "07 20 04 01"
_AMENDMENT_NUMBER = re.compile(r"^\d+[A-Z]*(=|/rev\d*)?$")  # "235/rev", "56": old labels omit "Am"
_WHOLE_DOC = re.compile(
    r"^(RC-B|B)\d{1,2}-\d{4}/\d{4}(/REV\d*)?$", re.I
)  # "B10-0441/2026": another motion as a whole
# Procedure types whose "motion for a resolution" is the legislative resolution (the EP's position)
LEGISLATIVE_TYPES = frozenset({"COD", "CNS", "APP", "SYN", "AVC"})


@dataclass
class Signals:
    ref: str | None  # referenceText (new) or the last label segment (old)
    label: str | None
    heading: str | None = None
    comment: str | None = None
    docs: list[str] = field(default_factory=list)
    about: str | None = None  # decisionAboutId
    item_title: str | None = None
    proc_types: list[str] = field(default_factory=list)


def label_tail(label: str | None) -> str | None:
    """Last ' - ' / ' – ' segment of an old-format label: 'A9-0042/2024 - Name - § 4/2' -> '§ 4/2'."""
    if not label:
        return None
    parts = [p.strip() for p in re.split(r"\s+[-–]\s*|\s*[-–]\s+|–", label) if p.strip()]
    return parts[-1] if parts else None


def classify(s: Signals) -> VoteKind:
    """Kind of vote from structured signals; "other" when no rule applies (see module docstring)."""
    ref = (s.ref or "").strip().lstrip("-–: ").strip()
    label = (s.label or "").strip()
    item = s.item_title or ""
    heading = s.heading or ""
    is_am_doc = any("-AM-" in d for d in s.docs)
    is_split_doc = any("-SPLIT-" in d for d in s.docs)
    whole_marker = bool(_FINAL.match(ref) or _RESOLUTION.match(ref))
    legislative = bool(set(s.proc_types) & LEGISLATIVE_TYPES) and not set(s.proc_types) - LEGISLATIVE_TYPES
    is_objection = bool(re.search(r"\bobjection\b", f"{item} {heading}", re.I))

    # 1. procedural decisions (referral back, urgency, agenda, adjournment, negotiation mandates)
    if _PROCEDURAL.search(ref) or _PROCEDURAL.search(heading) or _PROCEDURAL_LABEL.match(label):
        return "procedural"
    # 2. a provisional agreement is tabled as one amendment but is the vote on the whole text
    if re.match(r"^provisional agreement", ref, re.I) or re.match(r"^provisional agreement", heading, re.I):
        return "final"
    # 3. rejection motions and motions of censure (decisions on the whole text)
    if not is_am_doc and (
        _REJECTION.search(ref) or re.search(r"motion of censure", f"{item} {heading}", re.I)
    ):
        if not _PART.match(ref) and not _AMENDMENT_TAIL.match(ref):
            return "motion"
    # 4. amendments (incl. parts of an amendment, budget lines and blocks of amendments)
    if is_am_doc or _AMENDMENT_TAIL.match(ref) or _BUDGET_LINE.match(ref):
        return "amendment"
    if re.search(r"(^|[\s,;(])(am|ams|amendments?)\s*\d", ref, re.I) or _AMENDMENT_NUMBER.match(ref):
        return "amendment"
    if re.search(r"amendments by the committee", label, re.I) and not whole_marker:
        return "amendment"
    about = (s.about or "").strip()
    if about and about != "§" and re.search(r"\d", about) and not whole_marker:
        return "amendment"
    # 5. split / separate votes on parts of the original text
    if not whole_marker and (
        is_split_doc or about == "§" or _PART.match(ref) or re.match(r"^(sep|\d)", (s.comment or "").strip())
    ):
        return "split_or_separate"
    # 6. whole texts (old labels may carry the marker at the start: "Final vote: <title> - C9-…")
    for text in (ref, label):
        if re.match(r"^(final vote|vote final)", text, re.I):
            return "resolution" if re.search(r"\b(RC-)?B\d{1,2}-\d{4}/\d{4}", label) else "final"
        if _FINAL.match(text):
            return "motion" if is_objection else "final"
        if _RESOLUTION.match(text) or _WHOLE_DOC.match(text):
            if is_objection:
                return "motion"  # an objection to a delegated / implementing act, as a whole
            return "final" if legislative else "resolution"
    return "other"


# ========================================================================================= majority rule
def majority_rule(kind: str, item: VoteItem | None, proc_types: list[str]) -> str:
    """Majority required by the Treaties for this vote, or "unknown" when it is not established.

    TFEU Art. 231: "Save as otherwise provided in the Treaties, the European Parliament shall act by a majority
    of the votes cast" (abstentions are not votes cast: CJEU C-650/18). Exceptions in the Treaties:
      - Art. 294(7)(b),(c) TFEU: second reading — rejection of / amendments to the Council position:
        majority of component Members. Art. 294(13): third reading — majority of the votes cast.
      - Art. 290(2) TFEU: objection to (or revocation of) a delegated act: majority of component Members;
        Decision 1999/468/EC Art. 5a(3)(b),(4)(e): opposition under the regulatory procedure with scrutiny: idem.
      - Art. 234 TFEU (censure) and Art. 354 TFEU (Art. 7 TEU): two-thirds of the votes cast representing a
        majority of the component Members ("two_thirds_cast" = both conditions).
      - Art. 225 TFEU (request to the Commission), Art. 223(1), Art. 312(2) (MFF consent), Art. 314 (budget),
        Art. 49 TEU (accession consent), Art. 232 (Rules of Procedure): majority of component Members or
        mixed rules. Procedure types that may carry one of these (INL, APP, NLE, BUD, REG, ...) stay "unknown".
    """
    title = (item.title if item else "") or ""
    types = set(proc_types)
    if re.search(r"motion of censure|motion de censure", title, re.I) and kind == "motion":
        return "two_thirds_cast"
    if kind == "procedural":
        return "votes_cast"  # no Treaty exception covers referral, urgency, agenda or adjournment decisions
    if not types or len(types) > 1:
        return "unknown"
    (ptype,) = types
    symbol = item.symbol if item else None
    if ptype == "COD":
        if symbol == "***II":
            return "component_members" if kind in ("amendment", "motion") else "unknown"
        if symbol in ("***I", "***III"):
            return "votes_cast"  # Art. 294(3) (no special majority) and Art. 294(13)
        return "unknown"
    if ptype in ("DEA", "RPS"):
        return "component_members" if kind == "motion" else "unknown"
    if ptype in ("CNS", "INI", "RSP", "DEC", "IMM"):
        # consultation, own-initiative and topical resolutions, discharge, immunity: no Treaty exception
        # (a motion of censure is handled above; objections to implementing acts under Art. 291 TFEU /
        # Regulation (EU) No 182/2011 Art. 11 carry no special majority)
        return "votes_cast"
    return "unknown"


# ============================================================================================ assembly
OUTCOMES = {"ADOPTED": "adopted", "REJECTED": "rejected", "LAPSED": "lapsed"}
ROLLCALL = "VOTE_ELECTRONIC_ROLLCALL"


@dataclass
class Sitting:
    """One sitting's raw records plus its vote-item indexes."""

    id: str
    date: str
    term: int
    decisions: list[dict]
    items: dict[str, VoteItem]
    doc_items: dict[str, list[VoteItem]] = field(default_factory=dict)  # document id -> vote items

    @classmethod
    def build(cls, s: dict, decisions: list[dict], items: list[dict]) -> Sitting:
        idx = index_items(items)
        doc_items: dict[str, list[VoteItem]] = {}
        for it in idx.values():
            for d in it.docs:
                doc_items.setdefault(d, []).append(it)
        return cls(s["id"], s["date"], s["term"], decisions, idx, doc_items)

    @property
    def rich(self) -> bool:
        return self.date >= RICH_FORMAT_FROM


def _person_ids(v: Any) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p in _ids(v)]


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Draft:
    """Everything parsed from one decision before procedure links are resolved."""

    dec: dict
    sitting: Sitting
    title: str
    ref: str | None
    heading: str | None
    docs: list[str]
    items: list[VoteItem]
    label_docs: list[str]  # document ids written in the label / heading (official references)
    label_procs: list[str]  # procedure references written in the label ("2020/0060(COD)")

    @property
    def candidate_docs(self) -> list[str]:
        out = [b for d in self.docs if (b := base_doc(d))] + self.label_docs
        return list(dict.fromkeys(out))


def draft(dec: dict, sitting: Sitting) -> Draft:
    raw_label = _text(dec.get("activity_label"))
    label = clean_label(raw_label)
    ref = _text(dec.get("referenceText"))
    heading = _text(dec.get("headingLabel"))
    heading = re.sub(r"\s+", " ", heading).strip() if heading else None
    docs = [_suffix(d) or d for d in _ids(dec.get("decided_on_a_realization_of"))]
    docs += [_suffix(d) or d for d in _ids(dec.get("decided_on_a_part_of_a_realization_of"))]
    items = [
        sitting.items[i]
        for i in (_suffix(x) for x in _ids(dec.get("inverse_consists_of")))
        if i in sitting.items
    ]
    text = " ".join(t for t in (label, heading) if t)
    label_docs = [d for m in DOC_REF_RE.finditer(text) if (d := doc_ref_to_id(m.group(0)))]
    label_procs = sorted({m.group(0) for m in PROC_REF_RE.finditer(label or "")})
    if not sitting.rich:
        ref = label_tail(label)
        if not items:  # old format: the voted document is the vote item's document
            for d in label_docs:
                items += [it for it in sitting.doc_items.get(d, []) if it not in items]
    title = (
        label
        or ref
        or heading
        or (items[0].title if items else None)
        or f"Vote {dec.get('notation_votingId')}"
    )
    return Draft(dec, sitting, title, ref, heading, docs, items, list(dict.fromkeys(label_docs)), label_procs)


def doc_index(sittings: list[Sitting]) -> dict[str, set[str]]:
    """Document id -> process ids of the vote items (in any sitting) that are based on that document."""
    out: dict[str, set[str]] = {}
    for s in sittings:
        for it in s.items.values():
            for d in it.docs:
                if it.procs:
                    out.setdefault(d, set()).update(it.procs)
    return out


def resolve_procs(
    d: Draft,
    docs_procs: dict[str, set[str]],
    doc_links: dict[str, tuple[list[str], list[str]]],
    ref_to_id: dict[str, str],
) -> tuple[list[str], str]:
    """Process ids of the vote and how they were found ("item" | "label" | "document" | "")."""
    procs = sorted({p for it in d.items for p in it.procs})
    if procs:
        return procs, "item"
    found = sorted({ref_to_id[r] for r in d.label_procs if r in ref_to_id})
    if found:
        return found, "label"
    for doc in d.candidate_docs:
        if doc in docs_procs:
            return sorted(docs_procs[doc]), "item"
        created, derived = doc_links.get(doc, ([], []))
        if created:
            return created, "document"
        procs = sorted({p for src in derived for p in docs_procs.get(src, ())})
        if procs:  # joint motion -> the motions it replaces -> their vote item
            return procs, "item"
    return [], ""


def needs_doc_lookup(d: Draft, docs_procs: dict[str, set[str]], ref_to_id: dict[str, str]) -> list[str]:
    """Plenary documents to look up when neither a vote item nor the label gives a procedure."""
    if any(it.procs for it in d.items) or any(r in ref_to_id for r in d.label_procs):
        return []
    if any(doc in docs_procs for doc in d.candidate_docs):
        return []
    return [doc for doc in d.candidate_docs if doc.startswith(LOOKUP_SERIES)]


def source_ref(sitting: Sitting, event_id: str, rollcall: bool, retrieved: str) -> SourceRef:
    kind = "RCV" if rollcall else "VOT"
    what = "results of roll-call votes" if rollcall else "results of votes"
    return SourceRef(
        institution="EP",
        url=f"https://www.europarl.europa.eu/doceo/document/PV-{sitting.term}-{sitting.date}-{kind}_EN.html",
        label=f"European Parliament plenary minutes, {sitting.date} – {what} (EP Open Data API decision {event_id})",
        identifier=event_id,
        retrieved_at=retrieved,
    )


def build_records(
    d: Draft,
    procs: list[str],
    proc_labels: dict[str, str],
    retrieved: str,
) -> tuple[EpVote, EpBallots | None]:
    dec, s = d.dec, d.sitting
    refs = [proc_labels[p] if p in proc_labels else p for p in procs]
    refs = sorted({r for r in refs if PROC_REF_RE.fullmatch(r)})
    proc_types = sorted({m.group(3) for r in refs if (m := PROC_REF_RE.fullmatch(r))})
    item = d.items[0] if len({it.id for it in d.items}) == 1 else None
    sig = Signals(
        ref=d.ref,
        label=d.title,
        heading=d.heading,
        comment=_text(dec.get("comment")),
        docs=d.docs,
        about=dec.get("decisionAboutId") if isinstance(dec.get("decisionAboutId"), str) else None,
        item_title=" | ".join(sorted({it.title or "" for it in d.items})) or None,
        proc_types=proc_types,
    )
    kind = classify(sig)
    method = _suffix(dec.get("decision_method"))
    favor, against, abstain = (
        _person_ids(dec.get(k)) for k in ("had_voter_favor", "had_voter_against", "had_voter_abstention")
    )
    rollcall = method == ROLLCALL
    keep_ballots = rollcall and kind in BALLOT_KINDS and bool(favor or against or abstain)
    vid = str(dec.get("notation_votingId"))
    event_id = dec.get("activity_id") or _suffix(dec.get("id")) or vid
    vote = EpVote(
        id=vid,
        event_id=event_id,
        date=dec.get("activity_date") or s.date,
        term=s.term,
        title=d.title,
        reference_text=d.ref if s.rich else None,
        doc_ids=d.docs,
        procedure_refs=refs,
        kind=kind,
        outcome=OUTCOMES.get(_suffix(dec.get("decision_outcome")) or "", "unknown"),
        method=method,
        n_for=_int(dec.get("number_of_votes_favor")),
        n_against=_int(dec.get("number_of_votes_against")),
        n_abstain=_int(dec.get("number_of_votes_abstention")),
        attendees=_int(dec.get("number_of_attendees")),
        majority_rule=majority_rule(kind, item, proc_types),
        committee=_committee(dec.get("responsible_organization_label")),
        has_ballots=keep_ballots,
        source=source_ref(s, event_id, rollcall, retrieved),
    )
    ballots = None
    if keep_ballots:
        ballots = EpBallots(
            vote_id=vid,
            favor=favor,
            against=against,
            abstain=abstain,
            intended_favor=_person_ids(dec.get("had_voter_intended_favor")),
            intended_against=_person_ids(dec.get("had_voter_intended_against")),
            intended_abstain=_person_ids(dec.get("had_voter_intended_abstention")),
        )
    return vote, ballots


def ballot_issues(vote: EpVote, b: EpBallots) -> list[str]:
    """Differences between published counts and published voter lists (reported, never corrected)."""
    out = []
    for name, n, ids in (
        ("for", vote.n_for, b.favor),
        ("against", vote.n_against, b.against),
        ("abstain", vote.n_abstain, b.abstain),
    ):
        if n is not None and n != len(ids):
            out.append(f"{name}: count {n} != {len(ids)} voters")
    allv = b.favor + b.against + b.abstain
    if len(allv) != len(set(allv)):
        out.append(f"{len(allv) - len(set(allv))} MEP id(s) listed in more than one position")
    return out


# =============================================================================================== fetch
def _fetch_sittings(http: Http, sittings: list[dict], today: str) -> list[Sitting]:
    def one(s: dict) -> Sitting:
        decisions, items = fetch_sitting(http, s, today)
        return Sitting.build(s, decisions, items)

    out: dict[str, Sitting] = {}
    pending = list(sittings)
    for attempt in range(3):  # the shared rate limit can exhaust Http's retries; try failed ones again
        failed = []
        with ThreadPoolExecutor(WORKERS) as ex:
            futures = {s["id"]: ex.submit(one, s) for s in pending}
            for s in pending:
                try:
                    out[s["id"]] = futures[s["id"]].result()
                except HttpError as e:
                    log.warning("sitting %s failed (attempt %d): %s", s["id"], attempt + 1, e)
                    failed.append(s)
        if not failed:
            break
        pending = failed
        time.sleep(120)
    else:
        raise RuntimeError(f"{len(pending)} sittings could not be fetched, e.g. {pending[0]['id']}")
    return [out[s["id"]] for s in sittings]


@dataclass
class Result:
    votes: list[EpVote]
    ballots: list[EpBallots]
    linked_via: Counter[str]
    issues: dict[str, list[str]]  # vote id -> differences between counts and voter lists
    duplicates: int


def plan_lookups(data: list[Sitting], proc_labels: dict[str, str]) -> list[str]:
    """Plenary documents that must be looked up to link votes no vote item links to a procedure."""
    ref_to_id = {ref: pid for pid, ref in proc_labels.items()}
    docs_procs = doc_index(data)
    return sorted(
        {
            doc
            for s in data
            for dec in s.decisions
            for doc in needs_doc_lookup(draft(dec, s), docs_procs, ref_to_id)
        }
    )


def assemble(
    data: list[Sitting],
    proc_labels: dict[str, str],
    doc_links: dict[str, tuple[list[str], list[str]]],
    retrieved: str,
) -> Result:
    """Offline: raw sittings + procedure references + document links -> EpVote / EpBallots records."""
    ref_to_id = {ref: pid for pid, ref in proc_labels.items()}
    docs_procs = doc_index(data)
    votes: dict[str, EpVote] = {}
    ballots: list[EpBallots] = []
    how: Counter[str] = Counter()
    issues: dict[str, list[str]] = {}
    duplicates = 0
    for s in data:
        for dec in s.decisions:
            if not dec.get("notation_votingId"):
                continue
            d = draft(dec, s)
            procs, via = resolve_procs(d, docs_procs, doc_links, ref_to_id)
            vote, b = build_records(d, procs, proc_labels, retrieved)
            if vote.id in votes:
                duplicates += 1
                continue
            votes[vote.id] = vote
            how[via or "none"] += 1
            if b is not None:
                ballots.append(b)
                if problems := ballot_issues(vote, b):
                    issues[vote.id] = problems
    vote_list = sorted(votes.values(), key=lambda v: (v.date, len(v.id), v.id))
    ballots.sort(key=lambda b: (len(b.vote_id), b.vote_id))
    return Result(vote_list, ballots, how, issues, duplicates)


def fetch(http: Http) -> SourceStatus:
    t0 = time.monotonic()
    attempted = now_iso()
    today = _today()
    sittings = list_sittings(http, today)
    if not sittings:
        raise RuntimeError("no plenary sittings listed")
    data = _fetch_sittings(http, sittings, today)
    proc_labels = fetch_procedure_labels(http)
    if len(proc_labels) < 1000:
        raise RuntimeError(f"procedure list looks incomplete ({len(proc_labels)} procedures)")
    lookups = plan_lookups(data, proc_labels)
    log.info("%d sittings; %d document lookups", len(data), len(lookups))
    with ThreadPoolExecutor(WORKERS) as ex:
        doc_links = dict(
            zip(lookups, ex.map(lambda doc: fetch_document_links(http, doc), lookups), strict=True)
        )
    res = assemble(data, proc_labels, doc_links, now_iso())
    if not res.votes:
        raise RuntimeError("no votes parsed")
    write_records(SOURCE_ID, "votes", res.votes)
    write_records(SOURCE_ID, "ballots", res.ballots)

    kinds = Counter(v.kind for v in res.votes)
    rollcalls = sum(1 for v in res.votes if v.method == ROLLCALL)
    linked = sum(1 for v in res.votes if v.procedure_refs)
    note = (
        f"{len(sittings)} sittings ({sum(1 for s in data if s.decisions)} with votes), {len(res.votes)} votes "
        f"({rollcalls} roll-call, {len(res.ballots)} with ballots), {linked} linked to procedures "
        f"(via {dict(sorted(res.linked_via.items()))}); kinds {dict(sorted(kinds.items()))}; "
        f"{len(lookups)} document lookups; {len(res.issues)} votes whose voter lists differ from the counts"
        + (f"; {res.duplicates} duplicate voting ids skipped" if res.duplicates else "")
        + f"; {time.monotonic() - t0:.0f}s"
    )
    if res.issues:
        log.warning("ballot/count differences: %s", dict(list(res.issues.items())[:20]))
    return SourceStatus(
        source=SOURCE_ID,
        status="ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"votes": len(res.votes), "ballots": len(res.ballots), "sittings": len(sittings)},
        note=note,
    )
