"""What happens next, and when: the steps the Council and Parliament have scheduled for each procedure, as they
publish them ahead (data/snapshot/agenda/). Plans, not records: a planned date can change, and a step is recorded as
taken only by the other sources once it has happened.

Two official schedules, each written to its own file; a part that fails keeps its previous file:

1. Planned events in Cellar -> agenda/planned.json. The Publications Office records the steps planned on an
   interinstitutional procedure as `cdm:event_legal_projected` events (status PROJECTED), from the Council's file
   planning (`sender_transmission` "CONSIL:FilePlanning") and Parliament's, about three weeks ahead. Each has a date
   (`event_legal_date`), a type of the authority table "event" (`event_legal_has_type_concept_type_event_legal`, e.g.
   APR_R1_byCONSIL, "Approval of the EP's first reading position by the Council (adoption of the legislative act)"),
   the institution taking it (`event_legal_initiated_by_institution`), a procedure phase, the procedure
   (`event_legal_part_of_dossier` -> `procedure_code_interinstitutional_reference_procedure` "2023/0167/COD") and the
   documents it names (`event_legal_document_reference`: "CM 4825 2026 INIT", the agenda of the Council meeting;
   "ST 14751 2026 INIT", a Council document; "PE 34 2026 INIT", the act's text, PE-CONS 34/26). Cellar keeps some
   planned events after their date (on 5 Nov 2026: 20 of Parliament's, back to January 2024, and 5 of the Council's),
   so only those dated from today on are read.
   The Council documents named are looked up in Cellar (resource type, English title): an agenda
   (AGENDA_DRAFT_CONSIL) names the meeting ("COUNCIL OF THE EUROPEAN UNION (General Affairs)", "PERMANENT
   REPRESENTATIVES COMMITTEE (Part 1)"). Each document's copy on data.consilium.europa.eu is requested once per run
   and linked only if it answers: Council notes are often not public (ST 14751/26 answered 404 on 5 Nov 2026, its
   agenda CM 4825/26 200).
2. Parliament's plenary agenda -> agenda/plenary.json. EP Open Data API v2: the plenary sittings of the next
   HORIZON_DAYS days (`/meetings?year=Y`, PLENARY_SITTING) and, for each, the items of its draft agenda
   (`/meetings/{MTG-PL-YYYY-MM-DD}/foreseen-activities`, HTTP 204 until it is published, about three weeks ahead).
   A vote or debate item names its procedure(s) in its structured content
   (`<label typeof="proc" resource="proc/2023-0167">2023/0167(COD)</label>`); one record per item and procedure, with
   the code and label of the Publications Office event type of its kind (VOTE_byEP, DEBATE_byEP) and the phase the
   item gives (`occured_at_stage`, same authority table). A sitting whose agenda cannot be read keeps its records of
   the previous run (the run is "partial").

Labels are the Publications Office's own (authority tables "event" and "procedure-phase": skos:prefLabel in English,
read from Cellar), never written here; a step whose type has no English label there is left out (counted in the note).
Each run replaces both files with the steps dated from today on, so a step that was moved or dropped is not kept.
No request is started after EU_INTEL_FETCH_BUDGET_S.

Requests, all sequential: Cellar SPARQL (the planned events with their labels; the labels of Parliament's event types
and phases; the Council documents named), cached only within a day or for unchanging facts; one GET per Council
document named (no cache); `/meetings` for this year (and the next, near its end) and one paged GET per sitting
ahead (no cache).
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pipeline.http import EP_API, HttpError
from pipeline.models.entities import DocRef, PlannedStep, SourceRef, SourceStatus
from pipeline.snapshot import fetch_deadline, now_iso, past, read_records, write_records
from pipeline.sources.ep_procedures import ep_docref
from pipeline.sources.eurlex import PREFIXES, format_procedure_ref

log = logging.getLogger("pipeline.sources.agenda")

SOURCE_ID = "agenda"
AUTH = "http://publications.europa.eu/resource/authority/"
CELLAR_ID = "http://publications.europa.eu/resource/procedure-event/"
EVENT_URL = "https://publications.europa.eu/resource/procedure-event/{id}"  # 303 to the event's Cellar record
COUNCIL_DOC_URL = "https://data.consilium.europa.eu/doc/document/{doc}/EN/pdf"
FMT = "application/ld+json"
# corporate bodies of the authority table that take the steps shown -> Institution
INSTITUTIONS = {"CONSIL": "Council", "EP": "EP", "COM": "Commission"}
# an item of Parliament's agenda -> the Publications Office's event type of that kind
EP_ITEM_TYPES = {"PLENARY_VOTE": "VOTE_byEP", "PLENARY_DEBATE": "DEBATE_byEP"}
HORIZON_DAYS = 42  # sittings whose agenda is requested: published about three weeks ahead
PAGE = 50  # the API's default page size for foreseen activities
# A Council document reference as Cellar gives it: "CM 4825 2026 INIT", "CM 4750 2026 COR 1", "ST 9999 2026 REV 1 ADD 1"
COUNCIL_DOC_RE = re.compile(r"^([A-Z]{1,6}) (\d{1,6}) (\d{4}) (INIT|(?:(?:REV|COR|ADD|EXT) \d{1,3} ?)+)$")
# Council resource types -> DocRef.kind
DOC_KINDS = {"AGENDA_DRAFT_CONSIL": "agenda", "ACT_LEGIS": "act"}
PROC_LABEL_RE = re.compile(r'<label\b[^>]*\btypeof="proc"[^>]*>\s*(\d{4}/\d{4}[A-Z]?\([A-Z]{3}\))\s*</label>')


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _code(uri: str | None) -> str | None:
    """Last segment of an authority-table IRI: ".../authority/event/VOTE_byEP" -> "VOTE_byEP"."""
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else None


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip


def _long_date(d: str) -> str:
    """"2026-11-25" -> "25 November 2026" (not strftime, whose month names follow the locale)."""
    x = date.fromisoformat(d)
    return f"{x.day} {MONTHS[x.month - 1]} {x.year}"


# ============================================================================== 1. planned events in Cellar
def planned_query(today: str) -> str:
    """The planned events dated from `today` on, one row per event and document named, with the English labels of
    their type and phase."""
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?ev ?same ?date ?type ?label ?inst ?status ?ref ?ptype ?doc ?phase ?phase_label WHERE {{
  ?ev a cdm:event_legal_projected ;
      cdm:event_legal_date ?date ;
      cdm:event_legal_part_of_dossier ?dos .
  FILTER(?date >= "{today}"^^xsd:date)
  ?dos cdm:procedure_code_interinstitutional_reference_procedure ?ref .
  OPTIONAL {{ ?dos cdm:procedure_code_interinstitutional_has_type_concept_type_procedure_code_interinstitutional ?ptype }}
  OPTIONAL {{ ?ev cdm:event_legal_has_type_concept_type_event_legal ?type .
             OPTIONAL {{ ?type skos:prefLabel ?label . FILTER(LANG(?label) = "en") }} }}
  OPTIONAL {{ ?ev cdm:event_legal_initiated_by_institution ?inst }}
  OPTIONAL {{ ?ev cdm:event_legal_has-status_event-status ?status }}
  OPTIONAL {{ ?ev cdm:event_legal_document_reference ?doc }}
  OPTIONAL {{ ?ev cdm:event_legal_occurs_in_procedure-phase ?phase .
             OPTIONAL {{ ?phase skos:prefLabel ?phase_label . FILTER(LANG(?phase_label) = "en") }} }}
  OPTIONAL {{ ?ev owl:sameAs ?same . FILTER(STRSTARTS(STR(?same), "{CELLAR_ID}")) }}
}} ORDER BY ?date ?ref ?ev ?doc"""
    )


def labels_query(iris: Iterable[str]) -> str:
    """English labels of authority-table concepts (event types, procedure phases)."""
    values = " ".join(f"<{i}>" for i in sorted(set(iris)))
    return (
        PREFIXES
        + f"""SELECT ?c ?label WHERE {{
  VALUES ?c {{ {values} }}
  ?c skos:prefLabel ?label . FILTER(LANG(?label) = "en")
}}"""
    )


def council_doc(ref: str) -> tuple[str, str] | None:
    """A Council document reference as Cellar gives it -> (its citation, its register id):
    "CM 4825 2026 INIT" -> ("CM 4825/26", "CM-4825-2026-INIT"); "PE 34 2026 INIT" -> ("PE-CONS 34/26", ...);
    "CM 4750 2026 COR 1" -> ("CM 4750/26 COR 1", "CM-4750-2026-COR-1"). None for another kind of reference."""
    m = COUNCIL_DOC_RE.match(" ".join(ref.split()))
    if not m:
        return None
    prefix, number, year, suffix = m.groups()
    suffix = suffix.strip()
    cite = f"{'PE-CONS' if prefix == 'PE' else prefix} {int(number)}/{year[2:]}"
    if suffix != "INIT":
        cite += f" {suffix}"
    return cite, f"{prefix}-{int(number)}-{year}-{suffix.replace(' ', '-')}"


def documents_query(refs: Iterable[str]) -> str:
    """Resource type and English title of the Council documents named (Cellar ids "consil:CM_4825_2026_INIT")."""
    values = " ".join(f'"consil:{"_".join(r.split())}"^^xsd:string' for r in sorted(set(refs)))
    return (
        PREFIXES
        + f"""SELECT ?id ?date ?rtype ?title WHERE {{
  VALUES ?id {{ {values} }}
  ?w cdm:work_id_document ?id .
  OPTIONAL {{ ?w cdm:work_date_document ?date }}
  OPTIONAL {{ ?w cdm:work_has_resource-type ?rtype }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ;
                cdm:expression_uses_language <{AUTH}language/ENG> ;
                cdm:expression_title ?title }}
}}"""
    )


def document_facts(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Cellar answer of documents_query -> {reference as named ("CM 4825 2026 INIT"): {date, type, title}}."""
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        ref = (r.get("id") or "").removeprefix("consil:").replace("_", " ")
        facts = out.setdefault(ref, {})
        for key, field in (("date", "date"), ("rtype", "type"), ("title", "title")):
            if r.get(key) and field not in facts:
                facts[field] = _code(r[key]) if key == "rtype" else " ".join(r[key].split())
    return out


def public_copies(http: Any, refs: Iterable[str], deadline: float | None) -> tuple[dict[str, str], list[str]]:
    """{reference: URL of its public copy} for the Council documents that answer on data.consilium.europa.eu, and
    the references not checked (an error other than 404, or no time left). One request each, in turn."""
    found: dict[str, str] = {}
    unchecked: list[str] = []
    for ref in sorted(set(refs)):
        doc = council_doc(ref)
        if not doc:
            continue
        if past(deadline):
            unchecked.append(ref)
            continue
        url = COUNCIL_DOC_URL.format(doc=doc[1])
        try:
            http.get(url, use_cache=False, retries=1)
            found[ref] = url
        except HttpError as e:
            if e.status != 404:  # 404: no public copy in the register
                log.warning("agenda: %s not checked: %s", ref, e)
                unchecked.append(ref)
    return found, unchecked


def meeting_of(docs: list[str], facts: dict[str, dict[str, str]]) -> str | None:
    """The meeting a planned event is on: the English title of the first Council agenda it names, as given."""
    for ref in docs:
        f = facts.get(ref, {})
        if f.get("type") == "AGENDA_DRAFT_CONSIL" and f.get("title"):
            return f["title"]
    return None


def _doc_order(ref: str) -> tuple[int, str]:
    """Council agendas first (CM before ST), the initial version before corrigenda and revisions."""
    m = COUNCIL_DOC_RE.match(ref)
    return (0 if m and m[1] == "CM" else 1, f"{m[3]}{int(m[2]):06d} {m[4] != 'INIT'} {m[4]}" if m else ref)


def build_planned(
    rows: list[dict[str, str]],
    retrieved_at: str,
    facts: dict[str, dict[str, str]] | None = None,
    public: dict[str, str] | None = None,
) -> tuple[list[PlannedStep], dict[str, int]]:
    """One PlannedStep per planned event of the Cellar answer (rows: one per event and document named); events without
    a procedure in the EP's format, an institution shown here, or an English label of their type are left out (counted)."""
    facts, public = facts or {}, public or {}
    events: dict[str, dict[str, Any]] = {}
    for r in rows:
        ev = events.setdefault(r.get("ev") or "", {"docs": [], **r})
        if r.get("doc") and r["doc"] not in ev["docs"]:
            ev["docs"].append(" ".join(r["doc"].split()))
    skipped = {"no_reference": 0, "no_label": 0, "other_institution": 0, "not_planned": 0}
    out: dict[str, PlannedStep] = {}
    for key, ev in events.items():
        ref = format_procedure_ref(ev.get("ref") or "", ev.get("ptype") or None)
        code = _code(ev.get("type"))
        inst = INSTITUTIONS.get(_code(ev.get("inst")) or "") or (
            INSTITUTIONS.get(code.rsplit("_by", 1)[-1]) if code and "_by" in code else None
        )
        day = (ev.get("date") or "")[:10]
        if ev.get("status") and _code(ev["status"]) != "PROJECTED":
            skipped["not_planned"] += 1
            continue
        if not ref or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not key:
            skipped["no_reference"] += 1
            continue
        if not inst:
            skipped["other_institution"] += 1
            continue
        if not code or not ev.get("label"):
            skipped["no_label"] += 1
            continue
        local = (ev.get("same") or "").removeprefix(CELLAR_ID) or key.rsplit("/", 1)[-1]
        docs = sorted(ev["docs"], key=_doc_order)
        documents = []
        for d in docs:
            cited = council_doc(d)
            f = facts.get(d, {})
            documents.append(DocRef(
                id=cited[0] if cited else d, kind=DOC_KINDS.get(f.get("type", ""), "other"),
                date=f.get("date"), url=public.get(d),
            ))  # fmt: skip
        phase = _code(ev.get("phase"))
        out[local] = PlannedStep(
            id=f"cellar:{local}",
            reference=ref,
            date=day,
            institution=inst,  # type: ignore[arg-type]
            event_type=code,
            label=" ".join(ev["label"].split()),
            phase_code=phase,
            phase=" ".join(ev["phase_label"].split()) if ev.get("phase_label") else None,
            meeting=meeting_of(docs, facts),
            documents=documents,
            source=SourceRef(
                institution="EUR-Lex",
                url=EVENT_URL.format(id=local) if ev.get("same") else key.replace("http://", "https://", 1),
                label="Planned event recorded in Cellar (machine-readable)",
                identifier=local,
                retrieved_at=retrieved_at,
            ),
        )
    return sorted(out.values(), key=lambda s: (s.date, s.reference, s.id)), skipped


def fetch_planned(
    http: Any, today: str, retrieved_at: str, deadline: float | None
) -> tuple[list[PlannedStep], str, bool]:
    """The planned events from `today` on, with the meetings and public copies of the Council documents they name; a
    note; and whether the documents were all looked up and checked. Raises if the planned events cannot be read."""
    rows = http.sparql(planned_query(today))  # cached for the day only: the query names it
    refs = sorted({" ".join(r["doc"].split()) for r in rows if r.get("doc")})
    council = [r for r in refs if council_doc(r)]
    facts: dict[str, dict[str, str]] = {}
    notes: list[str] = []
    if council and not past(deadline):
        try:
            facts = document_facts(http.sparql(documents_query(council)))
        except Exception as e:  # noqa: BLE001 - the steps are kept, without their meetings
            log.warning("agenda: Council documents not looked up: %r", e)
            notes.append("the Council documents named could not be looked up (meetings not given)")
    public, unchecked = public_copies(http, council, deadline)
    if unchecked:
        notes.append(
            f"{len(unchecked)} Council documents not checked for a public copy ({', '.join(unchecked[:3])})"
        )
    steps, skipped = build_planned(rows, retrieved_at, facts, public)
    left_out = ", ".join(f"{n} {why.replace('_', ' ')}" for why, n in skipped.items() if n)
    note = (f"{len(steps)} planned events from {today} on ({sum(s.institution == 'Council' for s in steps)} of the "
            f"Council, {sum(s.institution == 'EP' for s in steps)} of Parliament); {len(public)} of {len(council)} Council "
            f"documents named have a public copy" + (f"; left out: {left_out}" if left_out else ""))  # fmt: skip
    return steps, "; ".join([note, *notes]), not notes


# ============================================================================== 2. Parliament's plenary agenda
def _get_data(http: Any, path: str, **params: Any) -> list[dict]:
    """GET an EP API resource's `data` (never cached: the agenda changes until the sitting); 204 and 404 mean none."""
    body = http.get(
        f"{EP_API}{path}", params={"format": FMT, **params}, use_cache=False, ok_statuses=(200, 204, 404)
    )
    if not body:
        return []
    try:
        d = json.loads(body)
    except ValueError:
        return []
    data = d.get("data", []) if isinstance(d, dict) else []
    return data if isinstance(data, list) else []


def upcoming_sittings(
    rows: list[dict], today: str, horizon_days: int = HORIZON_DAYS
) -> list[tuple[str, str]]:
    """(sitting id, date) of the plenary sittings from `today` to `horizon_days` ahead, in date order."""
    end = (date.fromisoformat(today) + timedelta(days=horizon_days)).isoformat()
    out = set()
    for r in rows:
        sid = r.get("activity_id") or _code(r.get("id")) or ""
        day = (r.get("activity_date") or "")[:10]
        if (
            r.get("had_activity_type") == "def/ep-activities/PLENARY_SITTING"
            and sid.startswith("MTG-PL-")
            and today <= day <= end
        ):
            out.add((sid, day))
    return sorted(out, key=lambda x: (x[1], x[0]))


def _english(v: Any) -> str | None:
    """The English text of a multilingual field, whitespace normalised; None without one."""
    x = v.get("en") if isinstance(v, dict) else v
    if isinstance(x, list):
        x = x[0] if x else None
    if not isinstance(x, str):
        return None
    return " ".join(html.unescape(x).split()) or None


def item_references(item: dict) -> list[str]:
    """The procedures an agenda item names in its structured content ("2023/0167(COD)"), in order. The labels are
    the same in every language; English first."""
    content = item.get("structuredContent")
    texts = [content] if isinstance(content, str) else []
    if isinstance(content, dict):
        texts = [content.get("en"), *(v for k, v in sorted(content.items()) if k != "en")]
    for t in texts:
        if isinstance(t, str) and (found := PROC_LABEL_RE.findall(t)):
            return list(dict.fromkeys(found))
    return []


def agenda_url(sitting: str) -> str:
    return f"{EP_API}/meetings/{sitting}/foreseen-activities?format=application%2Fld%2Bjson"


def build_plenary(
    items: list[dict], sitting: str, retrieved_at: str, labels: dict[str, str]
) -> tuple[list[PlannedStep], int]:
    """One PlannedStep per vote or debate item of a sitting's agenda and procedure it names; and the number of such
    items left out for want of an English label of their event type (`labels`: authority IRI -> label)."""
    out: list[PlannedStep] = []
    unlabelled = 0
    for it in items:
        code = EP_ITEM_TYPES.get(_code(it.get("had_activity_type")) or "")
        refs = item_references(it)
        day = (it.get("activity_date") or "")[:10]
        aid = it.get("activity_id") or _code(it.get("id"))
        if not code or not refs or not aid or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        label = labels.get(f"{AUTH}event/{code}")
        if not label:
            unlabelled += 1
            continue
        stage = it.get("occured_at_stage")
        stage = stage[0] if isinstance(stage, list) and stage else stage
        phase = _code(stage) if isinstance(stage, str) and "/procedure-phase/" in stage else None
        based = it.get("based_on_a_realization_of") or []
        docs = [ep_docref(d) for d in (based if isinstance(based, list) else [based]) if isinstance(d, str)]
        docs = sorted((d for d in docs if d.kind == "report"), key=lambda d: d.id)
        for ref in refs:
            pid = ref.split("(")[0].replace("/", "-")
            out.append(PlannedStep(
                id=f"ep:{aid}:{pid}", reference=ref, date=day, institution="EP", event_type=code, label=label,
                phase_code=phase, phase=labels.get(f"{AUTH}procedure-phase/{phase}") if phase else None,
                item=_english(it.get("activity_label")), documents=docs,
                source=SourceRef(
                    institution="EP", url=agenda_url(sitting),
                    label=f"Parliament's draft agenda for {_long_date(day)} (EP Open Data API)",
                    identifier=aid, retrieved_at=retrieved_at,
                ),
            ))  # fmt: skip
    return out, unlabelled


def fetch_plenary(
    http: Any, today: str, retrieved_at: str, deadline: float | None, previous: list[PlannedStep]
) -> tuple[list[PlannedStep], str, bool]:
    """The vote and debate items of the agendas of the sittings ahead; a note; and whether every sitting was read
    (a sitting not read keeps its previous records). Raises if the sittings cannot be listed."""
    years = sorted({today[:4], (date.fromisoformat(today) + timedelta(days=HORIZON_DAYS)).isoformat()[:4]})
    rows: list[dict] = []
    for year in years:
        offset = 0
        while True:
            page = _get_data(http, "/meetings", year=year, offset=offset, limit=100)
            rows += page
            if len(page) < 100:
                break
            offset += 100
    if not rows:  # the year's list holds its past sittings too: an empty answer is not a recess
        raise RuntimeError(f"no plenary sittings listed for {', '.join(years)}")
    sittings = upcoming_sittings(rows, today)
    items_by_sitting: dict[str, list[dict]] = {}
    failed: list[str] = []
    for sid, _day in sittings:
        if past(deadline):
            failed.append(sid)
            continue
        try:
            items, offset = [], 0
            while True:
                page = _get_data(http, f"/meetings/{sid}/foreseen-activities", offset=offset, limit=PAGE)
                items += page
                if len(page) < PAGE:
                    break
                offset += PAGE
            items_by_sitting[sid] = items
        except HttpError as e:
            log.warning("agenda: %s not read: %s", sid, e)
            failed.append(sid)
    phases = {
        stage
        for items in items_by_sitting.values()
        for it in items
        for stage in ([it.get("occured_at_stage")] if isinstance(it.get("occured_at_stage"), str) else [])
        if "/procedure-phase/" in stage
    }
    labels = {
        r["c"]: " ".join(r["label"].split())
        for r in http.sparql(labels_query([*(f"{AUTH}event/{c}" for c in EP_ITEM_TYPES.values()), *phases]))
    }  # cached: the authority tables' labels do not change from one run to the next
    steps: list[PlannedStep] = []
    unlabelled = 0
    for sid, items in items_by_sitting.items():
        built, n = build_plenary(items, sid, retrieved_at, labels)
        steps += built
        unlabelled += n
    # a sitting whose agenda was not read keeps its records of the previous run
    kept = [s for s in previous if s.date >= today and s.source.identifier and any(
        s.source.identifier.startswith(f"{sid}-") for sid in failed)]  # fmt: skip
    steps += kept
    published = sum(1 for items in items_by_sitting.values() if items)
    note = (f"{len(steps)} vote and debate items naming a procedure on the agendas of {published} of the "
            f"{len(sittings)} plenary sittings of the next {HORIZON_DAYS} days (the others not yet published)"
            + (f"; {unlabelled} left out without an English label of their type" if unlabelled else "")
            + (f"; {len(failed)} sittings not read ({', '.join(failed[:3])}), {len(kept)} of their earlier records kept"
               if failed else ""))  # fmt: skip
    return sorted(steps, key=lambda s: (s.date, s.reference, s.id)), note, not failed


# ============================================================================== fetch
def fetch(http: Any, today: str | None = None) -> SourceStatus:
    attempted = now_iso()
    today = today or _today()
    deadline = fetch_deadline()
    notes: list[str] = []
    records: dict[str, int] = {}
    parts_ok = 0
    complete = True
    try:
        planned, note, whole = fetch_planned(http, today, attempted, deadline)
        write_records(SOURCE_ID, "planned", planned, key=lambda s: (s.date, s.reference, s.id))
        records["planned"] = len(planned)
        notes.append(f"Cellar: {note}")
        parts_ok += 1
        complete = complete and whole
    except Exception as e:  # noqa: BLE001 - the other part goes on; this file keeps its previous records
        log.warning("agenda: planned events not read: %r", e)
        notes.append(f"Cellar planned events not read ({e!r:.200}); the previous file is kept")
        complete = False
    try:
        previous = read_records(SOURCE_ID, "plenary", PlannedStep)
        plenary, note, whole = fetch_plenary(http, today, attempted, deadline, previous)
        write_records(SOURCE_ID, "plenary", plenary, key=lambda s: (s.date, s.reference, s.id))
        records["plenary"] = len(plenary)
        notes.append(f"Parliament: {note}")
        parts_ok += 1
        complete = complete and whole
    except Exception as e:  # noqa: BLE001
        log.warning("agenda: plenary agenda not read: %r", e)
        notes.append(f"Parliament's plenary agenda not read ({e!r:.200}); the previous file is kept")
        complete = False
    if not parts_ok:
        raise RuntimeError("; ".join(notes))
    return SourceStatus(
        source=SOURCE_ID,
        status="ok" if complete else "partial",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records=records,
        note="; ".join(notes)[:1500],
    )
