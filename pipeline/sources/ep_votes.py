"""European Parliament plenary votes with individual roll-call ballots (EP Open Data API v2).

Produces data/snapshot/ep_votes/votes.json (list[EpVote]) for every recorded plenary vote of the 9th and
10th terms (sittings from 2019-07-02 to today) and ballots.json (list[EpBallots]) with the individual
positions of roll-call votes on whole texts (kind final / mandate / resolution / motion; see BALLOT_KINDS)
and of votes on a committee's decision to enter into negotiations (see keeps_ballots).

Requests (paced for the API's limit of 500 requests / 5 min per endpoint, shared with the other EP sources;
~800 for the sittings, ~30 for the procedure list, ~600 document and ~10 procedure fallbacks; all cached
by pipeline.http except sittings of the last FRESH_DAYS days):
    /meetings?year=Y                         plenary sittings (PLENARY_SITTING, with parliamentary_term)
    /meetings/{sitting}/decisions            every decision of the sitting (all pages in one response;
                                             `limit`/`offset` are ignored by this endpoint)
    /meetings/{sitting}/vote-results         vote items ("PLENARY_VOTE_RESULTS", one per agenda item)
    /procedures?process-type=T               process id -> official reference "2021/0106(COD)"
    /procedures/{id,id,...}                  references of linked procedures the paginated list never
                                             returned (its offset paging repeats some rows, skips others)
    /plenary-documents/{doc}?language=en     fallback: document -> procedure that created it

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
  referenceText "Provisional agreement": it is the final vote, not an amendment. Old labels carry it in
  the tail: "Digital Services Act - A9-0356/2021 - Christel Schaldemose - Provisional agreement - Am 564".
- Once that agreement is adopted, the vote on the "Commission proposal" is published as LAPSED without
  counts: it was never held, so it is kept as kind "other", not as a final vote.

Procedure links (EpVote.procedure_refs) are made only through official identifiers, in this order:
  1. new format: decision -> vote item (inverse_consists_of) -> procedures of that item (an item voted
     under the urgent procedure names its procedure only in its structuredLabel, "(COM(2025)0652 –
     C10-0263/2025 – 2025/0329(COD))");
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

Outcome (EpVote.outcome / outcome_basis) — see resolve_outcome(): "published" when the decision carries
decision_outcome (from 2024-01-15); else "minutes" from the sitting's official "Results of votes" annex
(PV-…-VOT XML, see parse_minutes); else "derived" from the counts when majority_rule is votes_cast and the
counts are not tied; otherwise "unknown".

Subject (EpVote.subject) — what was voted, in English, as published: the vote item title from 2024-01-15
(earlier items are titled in French only), else the block title of the sitting's English minutes.
Kind detail (EpVote.kind_detail) — see kind_detail(): rejection motions, censure, objections, decisions to
enter into negotiations.

Mandates — a vote classified "final" becomes "mandate" when Parliament referred the file back to committee
for interinstitutional negotiations right after it: an adopted referral-back decision in the same vote item
(new format) or a PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS event of the linked procedure on
the vote's date (e.g. the AI Act vote of 14 June 2023, 499-28-93).

Incremental fetching — see the section "incremental fetching" below (window, chunks, _state.json).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from lxml import etree

from pipeline.http import EP_API, Http, HttpError
from pipeline.models.entities import EpBallots, EpVote, KindDetail, SourceRef, SourceStatus, VoteKind
from pipeline.snapshot import fetch_deadline, now_iso, read_records, read_state, write_records, write_state

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
BALLOT_KINDS: frozenset[str] = frozenset({"final", "mandate", "resolution", "motion"})


# ============================================================================================ fetching
class _Pacer:
    """Starts a worker's network requests at least MIN_GAP_S apart; cache hits are not slowed down."""

    def __init__(self, gap_s: float):
        self.gap_s = gap_s
        self._local = threading.local()

    def get(self, http: Http, url: str, **kw: Any) -> bytes:
        t0 = time.monotonic()
        body = http.get(url, **kw)
        if time.monotonic() - t0 > 0.05:  # went to the network (cache hits return in ~1 ms)
            wait = self.gap_s - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(wait)
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


TERM_STARTS = ((10, "2024-07-16"), (9, "2019-07-02"))  # first day of each parliamentary term


def term_of(day: str) -> int:
    return next(term for term, start in TERM_STARTS if day >= start)


def list_sittings(http: Http, today: str | None = None, from_year: int | None = None) -> list[dict]:
    """Plenary sittings of the 9th and 10th terms up to today: [{id, date, term}] sorted by date."""
    today = today or _today()
    out: dict[str, dict] = {}
    for year in range(max(from_year or 0, int(FIRST_SITTING[:4])), int(today[:4]) + 1):
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


PROC_BATCH = 50
PROCESS_ID_RE = re.compile(r"\d{4}-\d{4}[A-Z]?")  # EP process id, e.g. "2021-0106"


def process_id(uri: str) -> str | None:
    """'eli/dl/proc/2021-0106' -> '2021-0106'; some records write the id as '2022-0371(COD)'."""
    m = re.match(r"(\d{4}-\d{4}[A-Z]?)(?:\([A-Z]{3}\))?$", uri.rstrip("/").rsplit("/", 1)[-1])
    return m.group(1) if m else None


def fetch_procedures_by_id(http: Http, ids: list[str]) -> dict[str, str]:
    """Process id -> reference for ids the /procedures list never returned (see fetch_procedures).

    Needed because offset pagination of the /procedures list is not stable: pages repeat some records and
    never return others (RSP: 6677 rows, 5790 distinct ids), so the list misses ~5% of procedures.
    """
    return fetch_procedures(http, ids)[0]


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
            pid
            for p in _ids(r.get("inverse_created_a_realization_of"))
            if "/proc/" in p and (pid := process_id(p))
        ]
        derived += [_suffix(d) or d for d in _ids(r.get("is_derivative_of"))]
    return sorted(set(procs)), sorted(set(derived))


# ------------------------------------------------------------------ minutes ("Results of votes", PV-…-VOT)
# Before 2024-01-15 the API publishes roll-call votes without their outcome. The sitting's official minutes
# annex "Results of votes" (PV-9-2019-10-24-VOT, XML on data.europarl.europa.eu) lists every vote with its
# result (+ adopted, — rejected, ↓ lapsed) and, for electronic votes, the counts. A decision takes the
# outcome of the minutes row with the same (for, against, abstention) counts in the same sitting, within the
# block or heading of the decision's document when its label names one; ambiguous matches stay unknown.
MINUTES_SYMBOLS = {"+": "adopted", "-": "rejected", "—": "rejected", "–": "rejected", "↓": "lapsed"}


@dataclass(frozen=True)
class MinutesRow:
    item: str  # Vote.Result number in the minutes ("6.")
    counts: tuple[int, int, int]
    outcome: str | None
    docs: frozenset[str]  # document ids of the block title/description and the current heading row
    symbol: str | None = None  # procedure symbol of the block title ("Artificial Intelligence Act ***I")
    title: str | None = None  # block title as printed in the English minutes ("Nature restoration ***I")


def parse_minutes(xml: bytes) -> list[MinutesRow]:
    """Rows with counts from a pre-2024 "Results of votes" XML (PV-VOT.xsd)."""
    root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    out: list[MinutesRow] = []
    for block in root.iter("Vote.Result"):
        texts = [block.findtext("Vote.Result.Text.Title") or ""]
        desc = block.find("Vote.Result.Description.Text")
        if desc is not None:
            texts.append("".join(desc.itertext()))
        block_docs = _doc_ids(" ".join(texts))
        m = SYMBOL_RE.search(texts[0].strip())
        block_symbol = m.group(0).replace(" ", "") if m else None
        block_title = clean_subject(texts[0])
        heading: frozenset[str] = frozenset()
        for tr in block.iter("TR"):
            tds = tr.findall("TD")
            total_for = tr.find(".//Vote.Result.Table.TotalVote.For")
            if total_for is None:
                if len(tds) == 1 or any(td.get("COLSPAN") for td in tds):
                    found = _doc_ids(" ".join("".join(td.itertext()) for td in tds))
                    heading = found or heading
                continue
            against = tr.find(".//Vote.Result.Table.TotalVote.Against")
            abstain = tr.find(".//Vote.Result.Table.TotalVote.Abstention")
            try:
                counts = (
                    int(total_for.text or ""),
                    int(against.text) if against is not None and against.text else 0,
                    int(abstain.text) if abstain is not None and abstain.text else 0,
                )
            except ValueError:
                continue
            symbols = [c for c in ("".join(td.itertext()).strip() for td in tds) if c in MINUTES_SYMBOLS]
            outcome = MINUTES_SYMBOLS[symbols[-1]] if symbols else None
            out.append(
                MinutesRow(
                    block.get("Number") or "",
                    counts,
                    outcome,
                    block_docs | heading,
                    block_symbol,
                    block_title,
                )
            )
    return out


def _doc_ids(text: str) -> frozenset[str]:
    return frozenset(d for m in DOC_REF_RE.finditer(text) if (d := doc_ref_to_id(m.group(0))))


def fetch_minutes(http: Http, sitting: dict) -> list[MinutesRow]:
    """Parsed "Results of votes" minutes of a pre-2024 sitting ([] when not published)."""
    base = f"PV-{sitting['term']}-{sitting['date']}-VOT"
    url = f"https://data.europarl.europa.eu/distribution/doc/{base}-FNL_en.xml"
    try:
        body = _PACER.get(http, url, ok_statuses=(200, 404))
        if not body.lstrip().startswith(b"<?xml") and not body.lstrip().startswith(b"<documents"):
            body = b""
            for r in _get_data(http, f"/documents/{base}"):  # file name differs: ask the metadata
                for e in r.get("is_realized_by", []):
                    for m in e.get("is_embodied_by", []) if str(e.get("id", "")).endswith("/en") else []:
                        if str(m.get("format", "")).endswith("/XML") and m.get("is_exemplified_by"):
                            body = _PACER.get(
                                http, f"https://data.europarl.europa.eu/{m['is_exemplified_by']}"
                            )
        return parse_minutes(body) if body else []
    except (HttpError, etree.XMLSyntaxError) as e:
        log.warning("minutes %s: %s", base, e)
        return []


REFERRAL_EVENT = "def/ep-activities/PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"


def parse_procedures(rows: list[dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(process id -> reference, process id -> dates of plenary referrals back for negotiations)."""
    refs: dict[str, str] = {}
    referrals: dict[str, list[str]] = {}
    for r in rows:
        pid = r.get("process_id")
        if not pid:
            continue
        if isinstance(r.get("label"), str):
            refs[pid] = r["label"]
        events = [e for e in r.get("consists_of", []) if isinstance(e, dict)]
        referrals[pid] = sorted(
            {
                e["activity_date"]
                for e in events
                if e.get("had_activity_type") == REFERRAL_EVENT and e.get("activity_date")
            }
        )
    return refs, referrals


def fetch_procedures(http: Http, ids: Iterable[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """parse_procedures() of /procedures/{id,id,...} (PROC_BATCH ids per request).

    The referral is a procedure event (e.g. "2021-0106-DEC-REFBAK-2023-06-14",
    PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS) on the day of the vote.
    """
    ids = sorted({pid for pid in ids if PROCESS_ID_RE.fullmatch(pid)})
    rows: list[dict] = []
    for i in range(0, len(ids), PROC_BATCH):
        batch = ids[i : i + PROC_BATCH]
        try:
            rows += _get_data(http, f"/procedures/{','.join(batch)}")
        except HttpError as e:  # one bad id fails the whole batch: retry the ids one by one
            log.warning("procedures batch failed (%s); fetching %d ids one by one", e.status, len(batch))
            for pid in batch:
                try:
                    rows += _get_data(http, f"/procedures/{pid}")
                except HttpError as e2:
                    log.warning("procedure %s: %s", pid, e2)
    return parse_procedures(rows)


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


def ref_to_process_id(ref: str) -> str:
    """'2021/0106(COD)' -> '2021-0106' (the EP process id)."""
    m = PROC_REF_RE.fullmatch(ref)
    return f"{m.group(1)}-{m.group(2)}" if m else ref


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


def clean_subject(text: str | None) -> str | None:
    """A published title with whitespace normalised (spreadsheet artefacts such as '_x000D_' removed)."""
    if not text:
        return None
    return re.sub(r"\s+", " ", text.replace("_x000D_", " ")).strip() or None


def _english(v: Any) -> str | None:
    """The English text of a multilingual field, or None: no fallback to another language."""
    x = v.get("en") if isinstance(v, dict) else None
    if isinstance(x, list):
        x = x[0] if x else None
    return clean_subject(x) if isinstance(x, str) else None


STRUCTURED_LABEL_RE = re.compile(r"<label>(.*?)</label>", re.S)


def structured_label_refs(item: dict) -> list[str]:
    """Procedure references in a vote item's structuredLabel, e.g. "Proposal for a regulation (COM(2025)0652 –
    C10-0263/2025 – 2025/0329(COD)) (Majority of votes cast required)" -> ["2025/0329(COD)"].

    Items voted under the urgent procedure (Rule 170) name their procedure only there."""
    text = _text(item.get("structuredLabel")) or ""
    return sorted(
        {m.group(0) for lab in STRUCTURED_LABEL_RE.findall(text) for m in PROC_REF_RE.finditer(lab)}
    )


@dataclass
class VoteItem:
    """A PLENARY_VOTE_RESULTS item: one agenda item's votes (e.g. 'Artificial Intelligence Act ***I')."""

    id: str
    title: str | None
    procs: list[str] = field(default_factory=list)  # EP process ids, e.g. "2021-0106"
    docs: list[str] = field(default_factory=list)  # document ids the item is based on
    subject: str | None = None  # the title in English only (before 2024 items are titled in French)

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
        procs = [pid for p in _ids(x.get("inverse_consists_of")) if "/proc/" in p and (pid := process_id(p))]
        if not procs:  # urgent-procedure items: the reference printed in the structured label
            procs = [ref_to_process_id(r) for r in structured_label_refs(x)]
        docs = [_suffix(d) or d for d in _ids(x.get("based_on_a_realization_of"))]
        out[iid] = VoteItem(
            id=iid,
            title=_text(x.get("activity_label")),
            procs=sorted(set(procs)),
            docs=docs,
            subject=_english(x.get("activity_label")),
        )
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
    r"draft proposal for a council|extension of (the )?term of office|"
    r"(final vote|vote final))(?![a-z])",
    re.I,
)
_RESOLUTION = re.compile(
    r"^((vote: )?(joint |alternative )?(motion|proposal|proposition) for (a )?resolution|motion for resolution|"
    r"(vote: )?(proposition de |projet de )?résolution|(vote: )?resolution|(draft |proposal for a |projet de )?"
    r"(recommendation|recommandation)(?! \d)|text as a whole|as a whole|texte dans son ensemble)(?![a-z])",
    re.I,
)
_PROCEDURAL = re.compile(
    r"(referr?al|refer(red)? back|renvoi|request for urgen|urgent procedure|urgency procedure|agenda\b|ordre du "
    r"jour|adjourn|procedural motion|interinstitutional negotiations|request to vote on the amendments|"
    r"request \(rule|demande du groupe|requests? (from|by) (the )?\S+ groups?|group request|postpone|"
    r"inadmissib|(request|proposal) (for|to vote on) (the )?amendments|urgent decision|demande des groupes|"
    r"decision by the \S+ committee)",
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
    r"sous-titre|chapter|part|section|considérant|line|table|indent|(directive|regulation) (\(\w+\) )?(no )?\d|"
    r"recommendation \d)"
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
OBJECTION_TYPES = frozenset({"DEA", "RPS"})


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


def label_parts(label: str | None) -> list[str]:
    """' - ' / ' – ' segments of an old-format label: 'A9-0042/2024 - Name - § 4/2' -> [..., '§ 4/2']."""
    if not label:
        return []
    return [p.strip() for p in re.split(r"\s+[-–]\s*|\s*[-–]\s+|–", label) if p.strip()]


def label_tail(label: str | None) -> str | None:
    """Last ' - ' / ' – ' segment of an old-format label: 'A9-0042/2024 - Name - § 4/2' -> '§ 4/2'."""
    parts = label_parts(label)
    return parts[-1] if parts else None


_PROVISIONAL = re.compile(r"^(provisional agreement|accord provisoire)(?![a-z])", re.I)
_STATEMENT = re.compile(r"\b(statements?|declarations?|déclarations?)\b", re.I)


def is_provisional_agreement(ref: str, heading: str, label: str) -> bool:
    """The vote on a provisional agreement (tabled as one amendment, voted as the whole text).

    New format: referenceText "Provisional agreement", or the heading when the referenceText does not name
    another text (a Commission statement voted under the same heading, e.g. Nature Restoration Am 138 on
    27 Feb 2024, is not the agreement). Old format (before 2024): the label ends "… – Provisional agreement –
    Am 564" (Digital Services Act, 5 July 2022)."""
    if _PROVISIONAL.match(ref):
        return True
    if _PROVISIONAL.match(heading) and not _STATEMENT.search(ref):
        return True
    parts = label_parts(label)
    return (
        len(parts) >= 2
        and bool(_PROVISIONAL.fullmatch(parts[-2]))
        and bool(re.fullmatch(r"am\s*\d+", parts[-1], re.I))
    )


def _is_objection(s: Signals) -> bool:
    """Objections to delegated / implementing acts: the item or heading says so, or every linked procedure
    is an objection procedure (DEA, RPS), whose whole-text vote is always the objection."""
    return bool(re.search(r"\bobjection\b", f"{s.item_title or ''} {s.heading or ''}", re.I)) or (
        bool(s.proc_types) and set(s.proc_types) <= OBJECTION_TYPES
    )


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
    is_objection = _is_objection(s)

    # 1. procedural decisions (referral back, urgency, agenda, adjournment, negotiation mandates)
    if _PROCEDURAL.search(ref) or _PROCEDURAL.search(heading) or _PROCEDURAL_LABEL.match(label):
        return "procedural"
    # 2. a provisional agreement is tabled as one amendment but is the vote on the whole text
    if is_provisional_agreement(ref, heading, label):
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
    # an amendment number (decisionAboutId "1") on "Text as a whole" is an amendment replacing the whole text
    # (urgent procedure, tabled by a committee or groups), not the vote on the text
    whole_text_amendment = bool(re.fullmatch(r"(text )?as a whole", ref, re.I))
    if about and about != "§" and re.search(r"\d", about) and (not whole_marker or whole_text_amendment):
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


_CENSURE = re.compile(r"motion of censure|motion de censure", re.I)
_NEGOTIATION_DECISION = re.compile(
    r"decision to enter (into )?interinstitutional negotiations|décision d.engager des négociations "
    r"interinstitutionnelles",
    re.I,
)
_COUNCIL_POSITION = re.compile(r"council[’']?s? position|position of the council|position du conseil", re.I)


def kind_detail(kind: str, s: Signals, symbol: str | None) -> KindDetail | None:
    """What a motion or procedural vote decides, where the published texts say so (else None).

    - "reject_proposal" / "reject_council_position": a motion to reject the Commission proposal (first
      reading, heading "Proposal to reject the Commission proposal") or the Council's position (second
      reading, "***II"). Adopted means Parliament rejected that text; rejected means it did not.
    - "censure": a motion of censure on the Commission (Art. 234 TFEU).
    - "objection": an objection to a delegated or implementing act (adopted = Parliament objects).
    - "negotiation_decision": the plenary vote on a committee's decision to enter into interinstitutional
      negotiations (Rule 71 of the 9th-term, Rule 72 of the 10th-term Rules of Procedure).
    """
    ref = (s.ref or "").strip()
    heading = s.heading or ""
    if kind == "procedural":
        return "negotiation_decision" if _NEGOTIATION_DECISION.search(f"{ref} {s.label or ''}") else None
    if kind != "motion":
        return None
    if _CENSURE.search(f"{ref} {heading} {s.item_title or ''}"):
        return "censure"
    if _REJECTION.search(ref) or re.search(r"\breject", heading, re.I):
        if symbol == "***II" or _COUNCIL_POSITION.search(heading):
            return "reject_council_position"
        return "reject_proposal"
    if _is_objection(s):
        return "objection"
    return None


def keeps_ballots(kind: str, detail: str | None) -> bool:
    """Roll-call votes whose individual positions are kept: votes on whole texts, and the vote confirming
    (or not) a committee's decision to negotiate with the Council."""
    return kind in BALLOT_KINDS or detail == "negotiation_decision"


# ========================================================================================= majority rule
def majority_rule(kind: str, title: str | None, symbol: str | None, proc_types: list[str]) -> str:
    """Majority required by the Treaties for this vote, or "unknown" when it is not established.

    `title` is the vote item title, `symbol` its procedure symbol ("***II"), `proc_types` the types of the
    linked procedures. TFEU Art. 231: "Save as otherwise provided in the Treaties, the European Parliament
    shall act by a majority of the votes cast" (abstentions are not votes cast: CJEU C-650/18). Exceptions:
      - Art. 294(7)(b),(c) TFEU: second reading ("***II", used only for the ordinary legislative procedure) —
        rejection of / amendments to the Council position: majority of component Members.
        Art. 294(13): third reading ("***III") — majority of the votes cast.
      - Art. 290(2) TFEU: objection to a delegated act (DEA): majority of component Members; likewise
        Decision 1999/468/EC Art. 5a(3)(b), (4)(e) for the regulatory procedure with scrutiny (RPS).
      - Art. 234 TFEU (censure) and Art. 354 TFEU (Art. 7 TEU): two-thirds of the votes cast representing a
        majority of the component Members ("two_thirds_cast" = both conditions).
      - Art. 225 (INL requests), 223(1), 312(2) (MFF consent), 314 (budget), Art. 49 TEU (accession consent),
        Art. 232 (Rules of Procedure, REG): component Members or mixed rules. Procedure types that may carry
        one of these (INL, APP, NLE, BUD, REG, ...) stay "unknown". (REG is mixed in the data: amendments to
        the Rules need a majority of component Members, amendments to other parts of the decision do not.)
    """
    types = set(proc_types)
    if kind == "motion" and re.search(r"motion of censure|motion de censure", title or "", re.I):
        return "two_thirds_cast"
    if kind == "procedural":
        return "votes_cast"  # no Treaty exception covers referral, urgency, agenda or adjournment decisions
    if symbol == "***II" and types <= {"COD"}:
        return "component_members" if kind in ("amendment", "motion") else "unknown"
    if len(types) != 1:
        return "unknown"
    (ptype,) = types
    if ptype == "COD":
        return "votes_cast" if symbol in ("***I", "***III") else "unknown"  # Art. 294(3), 294(13)
    if ptype in OBJECTION_TYPES:
        return "component_members" if kind == "motion" else "unknown"
    if ptype in ("CNS", "INI", "RSP", "DEC", "IMM"):
        # consultation, own-initiative and topical resolutions, discharge, immunity: no Treaty exception
        # (censure is handled above; objections to implementing acts under Art. 291 TFEU / Regulation (EU)
        # No 182/2011 Art. 11 carry no special majority)
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
    minutes: list[MinutesRow] = field(default_factory=list)  # pre-2024 "Results of votes" rows

    @classmethod
    def build(
        cls, s: dict, decisions: list[dict], items: list[dict], minutes: list[MinutesRow] | None = None
    ) -> Sitting:
        idx = index_items(items)
        doc_items: dict[str, list[VoteItem]] = {}
        for it in idx.values():
            for d in it.docs:
                doc_items.setdefault(d, []).append(it)
        return cls(s["id"], s["date"], s["term"], decisions, idx, doc_items, list(minutes or []))

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
    title: str  # the label, or a fallback built from published texts (see draft())
    label: str | None  # English (else French) activity label without the old-format timestamp
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
    # Without an activity label (e.g. immunity decisions), join the vote item title and the referenceText,
    # both as published: "Request for waiver of the immunity of … – Proposal for a decision".
    item_title = items[0].title if len(items) == 1 else None
    title = (
        label
        or (f"{item_title} – {ref}" if item_title and ref else None)
        or ref
        or heading
        or item_title
        or f"Vote {dec.get('notation_votingId')}"
    )
    return Draft(
        dec, sitting, title, label, ref, heading, docs, items, list(dict.fromkeys(label_docs)), label_procs
    )


DocIndex = dict[str, dict[str, list[str]]]  # document id -> {"procs": [...], "symbols": [...]}


def item_doc_index(sittings: list[Sitting], known: DocIndex | None = None) -> DocIndex:
    """Document id -> process ids and procedure symbols of the vote items (in any sitting) based on it.

    `known` is the index persisted in _state.json from earlier runs, so an incremental run still sees vote
    items of sittings it does not re-fetch. Symbols matter because some items omit "***II" on one day but
    carry it on another (e.g. the 2020 Mobility Package second readings, A9-0114..0116/2020)."""
    out: dict[str, dict[str, set[str]]] = {}
    for doc, v in (known or {}).items():
        out[doc] = {"procs": set(v.get("procs", ())), "symbols": set(v.get("symbols", ()))}
    for s in sittings:
        for it in s.items.values():
            for doc in it.docs:
                e = out.setdefault(doc, {"procs": set(), "symbols": set()})
                e["procs"].update(it.procs)
                if it.symbol:
                    e["symbols"].add(it.symbol)
    return {d: {k: sorted(v) for k, v in e.items()} for d, e in out.items() if e["procs"] or e["symbols"]}


def _docs_procs(idx: DocIndex) -> dict[str, set[str]]:
    return {d: set(e["procs"]) for d, e in idx.items() if e.get("procs")}


def _doc_symbols(idx: DocIndex) -> dict[str, set[str]]:
    return {d: set(e["symbols"]) for d, e in idx.items() if e.get("symbols")}


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
    # a reference written in the label, "2020/0060(COD)", is the process id "2020-0060" (validated later:
    # build_records drops ids that the EP does not know)
    found = sorted({ref_to_id.get(r) or ref_to_process_id(r) for r in d.label_procs})
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


def symbol_of(d: Draft, doc_symbols: dict[str, set[str]] | None) -> str | None:
    """Procedure symbol of the vote's item, else the single symbol of the items based on its documents."""
    symbols = {it.symbol for it in d.items if it.symbol}
    if not symbols and doc_symbols:
        docs = [doc for it in d.items for doc in it.docs] + d.candidate_docs
        symbols = {sym for doc in docs for sym in doc_symbols.get(doc, ())}
    return symbols.pop() if len(symbols) == 1 else None


def needs_doc_lookup(d: Draft, docs_procs: dict[str, set[str]], ref_to_id: dict[str, str]) -> list[str]:
    """Plenary documents to look up when neither a vote item nor the label gives a procedure."""
    if any(it.procs for it in d.items) or d.label_procs:
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


_REFERRAL_BACK = re.compile(r"referr?al|refer(red)? back|renvoi|rule 59\(4\)|rule 60\(4\)", re.I)


@dataclass
class Context:
    """Cross-decision facts used while building one vote."""

    doc_symbols: dict[str, set[str]] = field(default_factory=dict)
    referrals: dict[str, list[str]] = field(default_factory=dict)  # process id -> referral-back dates
    referral_items: set[str] = field(default_factory=set)  # vote items with an adopted referral back


def referral_items(sitting: Sitting) -> set[str]:
    """Vote items in which Parliament adopted a referral back to committee (published outcome)."""
    out: set[str] = set()
    for dec in sitting.decisions:
        ref = _text(dec.get("referenceText")) or _text(dec.get("activity_label")) or ""
        if _suffix(dec.get("decision_outcome")) == "ADOPTED" and _REFERRAL_BACK.search(ref):
            out |= {i for i in (_suffix(x) for x in _ids(dec.get("inverse_consists_of"))) if i}
    return out


def minutes_rows(d: Draft, counts: tuple[int | None, int | None, int | None]) -> list[MinutesRow]:
    """Minutes rows with the decision's counts (narrowed to its document's block when several match)."""
    if not d.sitting.minutes or counts[0] is None or counts[1] is None:
        return []
    key = (counts[0], counts[1], counts[2] or 0)
    rows = [r for r in d.sitting.minutes if r.counts == key]
    if d.label_docs and len(rows) > 1:
        rows = [r for r in rows if r.docs & set(d.label_docs)]
    return rows


def minutes_outcome(d: Draft, counts: tuple[int | None, int | None, int | None]) -> str | None:
    """Outcome of the decision in the sitting's minutes (see MINUTES_SYMBOLS), or None if not unique."""
    outcomes = {r.outcome for r in minutes_rows(d, counts)}
    return outcomes.pop() if len(outcomes) == 1 and None not in outcomes else None


def minutes_symbol(d: Draft, counts: tuple[int | None, int | None, int | None]) -> str | None:
    symbols = {r.symbol for r in minutes_rows(d, counts)}
    return symbols.pop() if len(symbols) == 1 else None


def minutes_title(d: Draft, counts: tuple[int | None, int | None, int | None]) -> str | None:
    """English block title of the minutes rows matching the decision (by counts, else by its documents)."""
    titles = {r.title for r in minutes_rows(d, counts)}
    if not titles and d.label_docs:
        titles = {r.title for r in d.sitting.minutes if r.docs & set(d.label_docs)}
    return titles.pop() if len(titles) == 1 else None


def subject_of(d: Draft, counts: tuple[int | None, int | None, int | None]) -> str | None:
    """What was voted, as published in English: the vote item title (from 2024-01-15; earlier items are
    titled in French only) or the block title of the sitting's English minutes (before that date)."""
    if d.sitting.rich:
        subjects = {it.subject for it in d.items}
        return subjects.pop() if len(subjects) == 1 else None
    return minutes_title(d, counts)


def resolve_outcome(
    dec: dict, d: Draft, rule: str, counts: tuple[int | None, int | None, int | None]
) -> tuple[str, str | None]:
    """(outcome, outcome_basis): published > minutes > derived from counts (votes_cast, no tie) > unknown."""
    published = OUTCOMES.get(_suffix(dec.get("decision_outcome")) or "")
    if published:
        return published, "published"
    n_for, n_against, _ = counts
    if minutes := minutes_outcome(d, counts):
        arithmetic = None
        if rule == "votes_cast" and n_for is not None and n_against is not None and n_for != n_against:
            arithmetic = "adopted" if n_for > n_against else "rejected"
        if arithmetic and minutes in ("adopted", "rejected") and minutes != arithmetic:
            # the minutes contradict their own counts (e.g. 15 Jan 2020, RC-B9-0040/2020 am 64: "+" with
            # 263 for, 421 against): publish neither
            return "unknown", None
        return minutes, "minutes"
    if rule == "votes_cast" and n_for is not None and n_against is not None and n_for != n_against:
        return ("adopted" if n_for > n_against else "rejected"), "derived"
    return "unknown", None


def build_records(
    d: Draft,
    procs: list[str],
    proc_labels: dict[str, str],
    retrieved: str,
    ctx: Context | None = None,
) -> tuple[EpVote, EpBallots | None]:
    ctx = ctx or Context()
    dec, s = d.dec, d.sitting
    refs = [proc_labels[p] if p in proc_labels else p for p in procs]
    refs = sorted({r for r in refs if PROC_REF_RE.fullmatch(r)})
    proc_types = sorted({m.group(3) for r in refs if (m := PROC_REF_RE.fullmatch(r))})
    item = d.items[0] if len({it.id for it in d.items}) == 1 else None
    sig = Signals(
        ref=d.ref,
        label=d.label,
        heading=d.heading,
        comment=_text(dec.get("comment")),
        docs=d.docs,
        about=dec.get("decisionAboutId") if isinstance(dec.get("decisionAboutId"), str) else None,
        item_title=" | ".join(sorted({it.title or "" for it in d.items})) or None,
        proc_types=proc_types,
    )
    kind = classify(sig)
    day = dec.get("activity_date") or s.date
    if kind == "final" and (
        any(it.id in ctx.referral_items for it in d.items)
        or any(day in ctx.referrals.get(p, ()) for p in procs)
    ):
        kind = "mandate"  # followed by a referral back to committee for interinstitutional negotiations
    counts = tuple(
        _int(dec.get(k))
        for k in ("number_of_votes_favor", "number_of_votes_against", "number_of_votes_abstention")
    )
    symbol = symbol_of(d, ctx.doc_symbols) or minutes_symbol(d, counts)
    rule = majority_rule(kind, item.title if item else None, symbol, proc_types)

    outcome, basis = resolve_outcome(dec, d, rule, counts)
    if kind in ("final", "mandate") and outcome == "lapsed":
        # a whole-text vote that fell without being held (the "Commission proposal" decision once the
        # provisional agreement replacing that text was adopted): not a vote of Parliament on the law
        kind = "other"
        rule = majority_rule(kind, item.title if item else None, symbol, proc_types)
    detail = kind_detail(kind, sig, symbol)
    method = _suffix(dec.get("decision_method"))
    favor, against, abstain = (
        _person_ids(dec.get(k)) for k in ("had_voter_favor", "had_voter_against", "had_voter_abstention")
    )
    rollcall = method == ROLLCALL
    keep_ballots = rollcall and keeps_ballots(kind, detail) and bool(favor or against or abstain)
    vid = str(dec.get("notation_votingId"))
    event_id = dec.get("activity_id") or _suffix(dec.get("id")) or vid
    vote = EpVote(
        id=vid,
        event_id=event_id,
        date=day,
        term=s.term,
        title=d.title,
        reference_text=d.ref if s.rich else None,
        doc_ids=d.docs,
        procedure_refs=refs,
        subject=subject_of(d, counts),
        kind=kind,
        kind_detail=detail,
        outcome=outcome,
        outcome_basis=basis,
        method=method,
        n_for=counts[0],
        n_against=counts[1],
        n_abstain=counts[2],
        attendees=_int(dec.get("number_of_attendees")),
        majority_rule=rule,
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
RETRY_WAIT_S = 60.0  # pause before fetching failed sittings again


def _fetch_sittings(
    http: Http, sittings: list[dict], today: str, deadline: float | None = None
) -> tuple[list[Sitting], list[dict]]:
    """(fetched sittings, sittings that still failed after 3 attempts — e.g. one whose results are not
    published yet). The shared rate limit can exhaust Http's own retries, hence the extra attempts; no
    extra attempt is started if its wait would end after `deadline` (monotonic)."""

    def one(s: dict) -> Sitting:
        decisions, items = fetch_sitting(http, s, today)
        minutes = fetch_minutes(http, s) if decisions and s["date"] < RICH_FORMAT_FROM else []
        return Sitting.build(s, decisions, items, minutes)

    out: dict[str, Sitting] = {}
    pending = list(sittings)
    for attempt in range(3):
        failed = []
        with ThreadPoolExecutor(WORKERS) as ex:
            futures = {s["id"]: ex.submit(one, s) for s in pending}
            for s in pending:
                try:
                    out[s["id"]] = futures[s["id"]].result()
                except HttpError as e:
                    log.warning("sitting %s failed (attempt %d): %s", s["id"], attempt + 1, e)
                    failed.append(s)
        pending = failed
        if not pending:
            break
        if attempt < 2:
            if deadline is not None and time.monotonic() + RETRY_WAIT_S > deadline:
                break
            time.sleep(RETRY_WAIT_S)
    return [out[s["id"]] for s in sittings if s["id"] in out], pending


@dataclass
class Result:
    votes: list[EpVote]
    ballots: list[EpBallots]
    linked_via: Counter[str]
    issues: dict[str, list[str]]  # vote id -> differences between counts and voter lists
    duplicates: int


def plan_lookups(
    data: list[Sitting],
    proc_labels: dict[str, str],
    known_docs: DocIndex | None = None,
    done: Iterable[str] = (),
) -> list[str]:
    """Plenary documents to look up to link votes that no vote item links to a procedure (minus `done`)."""
    ref_to_id = {ref: pid for pid, ref in proc_labels.items()}
    docs_procs = _docs_procs(item_doc_index(data, known_docs))
    wanted = {
        doc
        for s in data
        for dec in s.decisions
        for doc in needs_doc_lookup(draft(dec, s), docs_procs, ref_to_id)
    }
    return sorted(wanted - set(done))


def linked_process_ids(
    data: list[Sitting],
    proc_labels: dict[str, str],
    doc_links: dict[str, tuple[list[str], list[str]]],
    known_docs: DocIndex | None = None,
) -> set[str]:
    ref_to_id = {ref: pid for pid, ref in proc_labels.items()}
    docs_procs = _docs_procs(item_doc_index(data, known_docs))
    return {
        p
        for s in data
        for dec in s.decisions
        for p in resolve_procs(draft(dec, s), docs_procs, doc_links, ref_to_id)[0]
    }


def assemble(
    data: list[Sitting],
    proc_labels: dict[str, str],
    doc_links: dict[str, tuple[list[str], list[str]]],
    retrieved: str,
    known_docs: DocIndex | None = None,
    referrals: dict[str, list[str]] | None = None,
) -> Result:
    """Offline: raw sittings + procedure references + document links -> EpVote / EpBallots records.

    `referrals`: process id -> dates on which Parliament referred it back for negotiations (fetch_procedures).
    """
    ref_to_id = {ref: pid for pid, ref in proc_labels.items()}
    idx = item_doc_index(data, known_docs)
    docs_procs = _docs_procs(idx)
    ctx = Context(doc_symbols=_doc_symbols(idx), referrals=referrals or {})
    votes: dict[str, EpVote] = {}
    ballots: list[EpBallots] = []
    how: Counter[str] = Counter()
    issues: dict[str, list[str]] = {}
    duplicates = 0
    for s in data:
        ctx.referral_items = referral_items(s)
        for dec in s.decisions:
            if not dec.get("notation_votingId"):
                continue
            d = draft(dec, s)
            procs, via = resolve_procs(d, docs_procs, doc_links, ref_to_id)
            vote, b = build_records(d, procs, proc_labels, retrieved, ctx)
            if vote.id in votes:
                duplicates += 1
                continue
            votes[vote.id] = vote
            how[via or "none"] += 1
            if b is not None:
                ballots.append(b)
                if problems := ballot_issues(vote, b):
                    issues[vote.id] = problems
    vote_list = sorted(votes.values(), key=vote_key)
    ballots.sort(key=ballot_key)
    return Result(vote_list, ballots, how, issues, duplicates)


def vote_key(v: EpVote) -> tuple:
    return (v.date, len(v.id), v.id)


def ballot_key(b: EpBallots) -> tuple:
    return (len(b.vote_id), b.vote_id)


# ================================================================================ incremental fetching
# The committed snapshot is the checkpoint (no HTTP cache needed). A run re-fetches the sittings on or after
# (latest sitting in the snapshot - WINDOW_DAYS), the window in which intended-vote corrections and late
# results are published, plus the sittings still pending from an interrupted run; older votes are kept.
# Sittings are processed oldest first in chunks of CHUNK; after each chunk votes.json / ballots.json and
# _state.json are written, so an interruption loses at most one chunk. After fetch_deadline() (from
# EU_INTEL_FETCH_BUDGET_S) no new chunk is started and the run ends "partial". EU_INTEL_FULL_REFRESH=1 (or
# an empty snapshot) makes every sitting of the 9th and 10th terms pending.
#
# _state.json:
#   pending      sitting ids still to fetch in the current pass
#   doc_links    {document id: [process ids]} from /plenary-documents (never re-requested; [] = no link)
#   item_docs    {document id: {"procs": [...], "symbols": [...]}} from the vote items of all fetched sittings
#   proc_refs    {process id: reference} for every procedure linked so far
#   last_full    time of the last completed full pass
CHUNK = 20
WINDOW_DAYS = 60


MIN_KEEP_SHARE = 0.5  # a re-fetched sitting with fewer votes than this share of its stored ones is not replaced


def _out_of_time(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() > deadline


def _sitting_of(v: EpVote) -> str:
    return v.event_id[:17]  # "MTG-PL-2024-03-13-DEC-166051" -> "MTG-PL-2024-03-13"


def _shrunk_sittings(done: set[str], res: Result, stored: Counter[str]) -> set[str]:
    """Sittings of a chunk whose new result has far fewer votes than the snapshot holds: an empty or partial
    /decisions answer (204 and 404 read as "no records"), not a real removal. Their stored votes and
    ballots are kept and they stay pending."""
    new = Counter(_sitting_of(v) for v in res.votes)
    return {s for s in done if stored.get(s, 0) and new.get(s, 0) < MIN_KEEP_SHARE * stored[s]}


def _without_sittings(res: Result, sittings: set[str]) -> Result:
    keep = {v.id for v in res.votes if _sitting_of(v) not in sittings}
    return replace(
        res,
        votes=[v for v in res.votes if v.id in keep],
        ballots=[b for b in res.ballots if b.vote_id in keep],
        issues={k: x for k, x in res.issues.items() if k in keep},
    )


def _merge_chunk(chunk_ids: set[str], res: Result) -> tuple[int, int]:
    """Replace the chunk's sittings in votes.json / ballots.json by `res` (other sittings are kept)."""
    new_ids = {v.id for v in res.votes}
    votes = [
        v
        for v in read_records(SOURCE_ID, "votes", EpVote)
        if _sitting_of(v) not in chunk_ids and v.id not in new_ids
    ]
    votes += res.votes
    keep = {v.id for v in votes if v.has_ballots} - new_ids
    ballots = [b for b in read_records(SOURCE_ID, "ballots", EpBallots) if b.vote_id in keep] + res.ballots
    write_records(SOURCE_ID, "votes", votes, key=vote_key)
    write_records(SOURCE_ID, "ballots", ballots, key=ballot_key)
    return len(votes), len(ballots)


def _procedure_refs(state: dict, votes: list[EpVote]) -> dict[str, str]:
    """Process id -> reference already known from the snapshot and the state."""
    refs = dict(state.get("proc_refs", {}))
    for v in votes:
        for r in v.procedure_refs:
            refs.setdefault(ref_to_process_id(r), r)
    return refs


def _fetch_chunk(
    http: Http,
    chunk: list[dict],
    today: str,
    proc_refs: dict[str, str],
    doc_links: dict[str, list[str]],
    known_docs: DocIndex,
    deadline: float | None = None,
) -> tuple[Result, Counter[str], set[str]]:
    """Fetch and assemble one chunk of sittings; updates proc_refs and doc_links in place.

    Returns the result, request statistics and the ids of the sittings fetched; sittings that could not be
    fetched are left out (and stay pending)."""
    data, failed = _fetch_sittings(http, chunk, today, deadline)
    if not data:
        raise RuntimeError(f"{len(failed)} sittings could not be fetched, e.g. {failed[0]['id']}")
    lookups = plan_lookups(data, proc_refs, known_docs, done=doc_links)
    with ThreadPoolExecutor(WORKERS) as ex:
        found = list(ex.map(lambda doc: fetch_document_links(http, doc), lookups))
    doc_links.update({doc: procs for doc, (procs, _derived) in zip(lookups, found, strict=True)})
    links = {doc: (procs, []) for doc, procs in doc_links.items()}
    missing = sorted(linked_process_ids(data, proc_refs, links, known_docs) - set(proc_refs))
    proc_refs.update(fetch_procedures_by_id(http, missing))
    res = assemble(data, proc_refs, links, now_iso(), known_docs)
    # final votes followed by a referral back to committee are negotiating mandates (procedure events)
    finals = sorted({ref_to_process_id(r) for v in res.votes if v.kind == "final" for r in v.procedure_refs})
    refs, referrals = fetch_procedures(http, finals)
    proc_refs.update(refs)
    if any(referrals.values()):
        res = assemble(data, proc_refs, links, now_iso(), known_docs, referrals)
    known_docs.update(item_doc_index(data, known_docs))
    stats: Counter[str] = Counter(
        sittings=len(data),
        votes=len(res.votes),
        lookups=len(lookups),
        proc_by_id=len(missing),
        procedures=len(finals),
        issues=len(res.issues),
    )
    return res, stats, {x.id for x in data}


def fetch(http: Http) -> SourceStatus:
    t0 = time.monotonic()
    attempted = now_iso()
    today = _today()
    deadline = fetch_deadline()
    state = read_state(SOURCE_ID)
    existing = read_records(SOURCE_ID, "votes", EpVote)
    full = os.environ.get("EU_INTEL_FULL_REFRESH") == "1" or not existing
    pending_before = set(state.get("pending", []))
    if full:
        start = FIRST_SITTING
    else:
        latest = max(v.date for v in existing)
        start = max(FIRST_SITTING, (date.fromisoformat(latest) - timedelta(days=WINDOW_DAYS)).isoformat())
    years = {int(start[:4])} | {int(sid[7:11]) for sid in pending_before}
    try:
        sittings = list_sittings(http, today, from_year=min(years))
    except HttpError as e:
        if not pending_before:
            raise
        # the listing is unavailable: still work through the sittings pending from the previous run
        log.warning("ep_votes: sitting list unavailable (%s); continuing with the pending sittings", e)
        sittings = [
            {"id": sid, "date": sid[7:17], "term": term_of(sid[7:17])} for sid in sorted(pending_before)
        ]
    if not sittings:
        raise RuntimeError("no plenary sittings listed")
    targets = [s for s in sittings if full or s["date"] >= start or s["id"] in pending_before]
    pass_kind = "full" if full or (pending_before and state.get("pass") == "full") else "window"

    proc_refs = _procedure_refs(state, existing)
    if full:
        proc_refs = {**fetch_procedure_labels(http), **proc_refs}  # one listing per full pass
    doc_links: dict[str, list[str]] = dict(state.get("doc_links", {}))
    known_docs: DocIndex = dict(state.get("item_docs", {}))
    linked_ids = {ref_to_process_id(r) for v in existing for r in v.procedure_refs}
    pending = [s["id"] for s in targets]
    last_full = state.get("last_full")

    def save() -> None:
        used = linked_ids | {p for ps in doc_links.values() for p in ps}
        used |= {p for e in known_docs.values() for p in e.get("procs", [])}
        write_state(
            SOURCE_ID,
            {
                "pass": pass_kind,
                "pending": pending,
                "doc_links": dict(sorted(doc_links.items())),
                "item_docs": dict(sorted(known_docs.items())),
                "proc_refs": {p: proc_refs[p] for p in sorted(used) if p in proc_refs},
                "last_full": last_full,
            },
        )

    save()
    counts: Counter[str] = Counter()
    n_ballots = len(read_records(SOURCE_ID, "ballots", EpBallots))
    stored_per_sitting = Counter(_sitting_of(v) for v in existing)
    held: set[str] = set()  # sittings whose stored votes were kept (new answer far smaller)
    error = None
    for i in range(0, len(targets), CHUNK):
        if _out_of_time(deadline):
            break
        chunk = targets[i : i + CHUNK]
        try:
            res, stats, done = _fetch_chunk(http, chunk, today, proc_refs, doc_links, known_docs, deadline)
        except (HttpError, RuntimeError) as e:  # keep the completed chunks; resume next run
            log.warning("ep_votes: stopping after an error in chunk %s..: %s", chunk[0]["id"], e)
            error = repr(e)[:200]
            break
        shrunk = _shrunk_sittings(done, res, stored_per_sitting)
        if shrunk:
            log.warning("ep_votes: kept the stored votes of %s (new answer far smaller)", ", ".join(sorted(shrunk)))
            res, done = _without_sittings(res, shrunk), done - shrunk
            held |= shrunk
        _, n_ballots = _merge_chunk(done, res)
        linked_ids |= {ref_to_process_id(r) for v in res.votes for r in v.procedure_refs}
        pending = [sid for sid in pending if sid not in done]
        if not pending and pass_kind == "full":
            last_full = now_iso()
        save()
        counts.update(stats)
        log.info("ep_votes: %d/%d sittings done", counts["sittings"], len(targets))

    votes = read_records(SOURCE_ID, "votes", EpVote)
    if not votes:
        raise RuntimeError(error or "no votes fetched")
    kinds = Counter(v.kind for v in votes)
    rollcalls = sum(1 for v in votes if v.method == ROLLCALL)
    linked = sum(1 for v in votes if v.procedure_refs)
    mode = "full pass" if pass_kind == "full" else f"window from {start}"
    note = (
        f"{mode}: {counts['sittings']}/{len(targets)} sittings fetched ({counts['votes']} votes, "
        f"{counts['lookups']} document lookups, {counts['proc_by_id']} procedures by id)"
        + (f"; {len(pending)} sittings pending; resumes next run" if pending else "")
        + (f" (stopped by {error})" if error else "")
        + (
            f"; stored votes kept for {len(held)} sittings whose new answer had far fewer votes "
            f"({', '.join(sorted(held)[:5])})"
            if held
            else ""
        )
        + f". Snapshot: {len(votes)} votes ({rollcalls} roll-call, {n_ballots} with ballots), {linked} linked "
        f"to procedures; kinds {dict(sorted(kinds.items()))}; {counts['issues']} fetched votes whose voter "
        f"lists differ from the counts; {time.monotonic() - t0:.0f}s"
    )
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if pending else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"votes": len(votes), "ballots": n_ballots, "sittings": len({_sitting_of(v) for v in votes})},
        note=note,
    )
