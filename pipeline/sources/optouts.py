"""Treaty opt-outs that a directive itself records in its recitals (EUR-Lex text, via Cellar).

Denmark (Protocol No 22) and Ireland (Protocol No 21) take part in measures in the area of freedom,
security and justice only if they opt in. Each such directive says in its recitals, in standard
wording, which of them are not bound, e.g. Directive (EU) 2016/343, recital 51: "In accordance with
Articles 1 and 2 of Protocol No 22 ..., Denmark is not taking part in the adoption of this Directive and
is not bound by it or subject to its application." The Council's voting results record the same fact
only for votes since 2019, and Cellar has no property for it.

A directive that builds upon the Schengen acquis adds, after Denmark's recital, that Denmark decides under Article 4
of Protocol No 22 whether to implement it in its national law (Directive (EU) 2023/977, recital 40: "Given that this
Directive builds upon the Schengen acquis, Denmark shall, in accordance with Article 4 of that Protocol, decide within
a period of six months after the Council has decided on this Directive whether it will implement it in its national
law."). That sentence is quoted too, and the directive records Denmark under `schengen_art4`. Denmark's decision, a
notification to the Council, is not in Cellar's metadata (data/curated/denmark_schengen.yaml records those checked).

Ireland may still take part after adoption (Protocol No 21, Article 4): the Commission then confirms its
participation in a decision, e.g. Commission Decision (EU) 2024/2087, Article 1: "The participation of
Ireland in Directive (EU) 2024/1346 is confirmed." Such decisions are found by their title in Cellar and
recorded on the directive (`opted_in`); the recitals' "not bound" no longer applies to that country.
Decisions confirming a participation in a regulation are recorded too (Commission Decision (EU) 2024/2088,
Article 1: "The participation of Ireland in Regulation (EU) 2024/1351 is confirmed."), although regulations'
recitals are not read. Such a decision is a published act that Cellar keeps, so an opt-in recorded earlier
that is missing from a later answer means that answer was incomplete (a query Cellar cut short can still
answer HTTP 200): the recorded opt-in is kept and the run is "partial".

Produces data/snapshot/optouts/directives.json: one record per directive of the EUR-Lex snapshot whose
text has been read, with the countries its recitals declare not bound, the sentences quoted, and later
opt-ins; and data/snapshot/optouts/regulations.json: one record per Commission decision confirming a
participation in a regulation, with the decision's title (its number and date). The text of an adopted act
does not change, so each directive is read once (again when the
recital matcher changes, PARSER_VERSION); texts that could not be fetched are retried on the next run. A text
read before that cannot be fetched again keeps its earlier reading (the run is "partial" until it is re-read).
Stops starting new downloads after EU_INTEL_FETCH_BUDGET_S.

Requests: GET https://publications.europa.eu/resource/celex/{CELEX} with Accept: application/xhtml+xml
(else text/html) and Accept-Language: eng (Cellar content negotiation; the English expression); one Cellar
SPARQL query for decisions titled "confirming the participation of Ireland/Denmark in Directive/Regulation ...".
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any

from pipeline.http import HttpError
from pipeline.models.entities import DirectiveOptOut, LegalAct, RegulationOptIn, SourceRef, SourceStatus
from pipeline.snapshot import fetch_deadline, now_iso, read_manifest, read_records, upsert_records
from pipeline.sources.eurlex import ENG, PREFIXES

log = logging.getLogger("pipeline.sources.optouts")

SOURCE_ID = "optouts"
CELEX_URL = "https://publications.europa.eu/resource/celex/{celex}"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
COUNTRIES = {"Denmark": "DK", "Ireland": "IE"}
PARSER_VERSION = 3
# "... , Denmark is not taking part in the adoption of this Directive and is not bound by it ...", also
# "... and is therefore not bound by it" (Directive 2014/57/EU, recital 31) and "..., and are not bound by or
# subject to its application" (Directive 2014/66/EU, recital 47)
NOT_BOUND_RE = re.compile(
    r"([^.;]{0,400}?)\b(?:is|are) not taking part in the adoption of this Directive,? and (?:is|are) "
    r"(?:therefore )?not bound by (?:it|or subject to)",
    re.IGNORECASE,
)
# "Given that this Directive builds upon the Schengen acquis, Denmark shall, in accordance with Article 4 of that
# Protocol, decide within a period of six months after the Council has decided on this Directive whether it will
# implement it in its national law."
SCHENGEN_ART4_RE = re.compile(
    r"[^.;]*\bbuilds? (?:up)?on the Schengen acquis\s*,\s*Denmark shall\s*,\s*in accordance with Article 4 of "
    r"(?:that|the said) Protocol\s*,\s*decide\b[^.]*\bwhether it will implement it in its national law\s*\.",
    re.IGNORECASE,
)  # the text can have a space before a comma, where a footnote or an element ends ("Schengen acquis , Denmark")
# "Commission Decision (EU) 2024/2087 of 31 July 2024 confirming the participation of Ireland in Directive (EU)
# 2024/1346 of the European Parliament ..."; older titles number the directive "2013/33/EU"; a regulation: "... in
# Regulation (EU) 2024/1351 ...", before 2015 "Regulation (EU) No 516/2014" (number, then year)
OPT_IN_RE = re.compile(
    r"confirming the participation of (Ireland|Denmark) in (Directive|Regulation) (?:\((?:EU|EC)\) )?"
    r"(?:(\d{4})/(\d{1,4})|No (\d{1,4})/(\d{4}))\b"
)
ACT_SECTOR = {"Directive": "L", "Regulation": "R"}


def plain_text(body: bytes) -> str:
    t = body.decode("utf-8", errors="replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).replace("’", "'")


def not_bound(text: str) -> tuple[list[str], list[str]]:
    """Countries that the text declares not taking part in the directive's adoption, and the quotes."""
    countries: set[str] = set()
    quotes: list[str] = []
    for m in NOT_BOUND_RE.finditer(text):
        subject = m.group(1).rsplit(",", 1)[-1]  # after "In accordance with ... Protocol No 22 ...,"
        if re.search(r"\b(?:those|these|both) Member States\b", subject):
            # "... Protocol No 21 on the position of the United Kingdom and Ireland ..., those Member States are
            # not taking part ...": the countries named earlier in the same sentence
            subject = m.group(1)[m.group(1).rfind(". ") + 1 :]
        found = {code for name, code in COUNTRIES.items() if re.search(rf"\b{name}\b", subject)}
        if found:
            countries |= found
            start = max(m.group(1).rfind(". "), 0)
            quotes.append((m.group(1)[start:] + m.group(0)[len(m.group(1)) :]).strip(" .") + ".")
    return sorted(countries), quotes


def schengen_art4(text: str) -> str | None:
    """The recital sentence saying that Denmark decides under Article 4 of Protocol No 22 whether to implement the
    directive, which builds upon the Schengen acquis; None if the text has none."""
    m = SCHENGEN_ART4_RE.search(text)
    return re.sub(r"\s+([,.])", r"\1", m.group(0)).strip() if m else None


def opt_ins_query() -> str:
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?celex ?title WHERE {{
  ?w cdm:resource_legal_id_celex ?celex ;
     cdm:work_date_document ?date .
  FILTER(?date >= "2010-01-01"^^xsd:date)
  ?e cdm:expression_belongs_to_work ?w ;
     cdm:expression_uses_language <{ENG}> ;
     cdm:expression_title ?title .
  FILTER(CONTAINS(LCASE(STR(?title)), "confirming the participation of"))
}}"""
    )


def opt_ins(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Directive or regulation CELEX -> {country: CELEX of the Commission decision confirming its participation}."""
    out: dict[str, dict[str, str]] = {}
    for r in sorted(rows, key=lambda r: r.get("celex", "")):
        m = OPT_IN_RE.search(re.sub(r"\s+", " ", r.get("title") or ""))  # titles use no-break spaces
        if m and re.fullmatch(r"3\d{4}D\d{4}", r.get("celex") or ""):
            year, number = (m[3], m[4]) if m[3] else (m[6], m[5])
            out.setdefault(f"3{year}{ACT_SECTOR[m[2]]}{int(number):04d}", {})[COUNTRIES[m[1]]] = r["celex"]
    return out


def regulation_opt_ins(rows: list[dict[str, str]]) -> list[RegulationOptIn]:
    """The decisions of the answer that confirm a participation in a regulation, each with its title."""
    titles = {r.get("celex"): " ".join((r.get("title") or "").split()) for r in rows}
    return [RegulationOptIn(decision=d, celex=celex, country=c, title=titles[d])
            for celex, by in opt_ins(rows).items() if celex[5] == "R" for c, d in sorted(by.items())]  # fmt: skip


def fetch_text(http: Any, celex: str) -> bytes:
    url = CELEX_URL.format(celex=celex)
    last: Exception | None = None
    for accept in ("application/xhtml+xml", "text/html"):
        try:
            return http.get(url, headers={"Accept": accept, "Accept-Language": "eng"}, use_cache=False)
        except HttpError as e:
            last = e
    raise last or RuntimeError(celex)


def fetch(http: Any) -> SourceStatus:
    attempted = now_iso()
    directives = sorted(a.celex for a in read_records("eurlex", "acts", LegalAct) if a.act_type == "directive")
    done = {r.celex: r for r in read_records(SOURCE_ID, "directives", DirectiveOptOut)}
    todo = [c for c in directives if c not in done or done[c].status != "ok" or done[c].parser < PARSER_VERSION]
    deadline = fetch_deadline()
    out: list[DirectiveOptOut] = []
    unavailable = 0
    try:
        rows = http.sparql(opt_ins_query(), use_cache=False)
        later, regulations = opt_ins(rows), regulation_opt_ins(rows)
    except Exception as e:  # noqa: BLE001 - keep the opt-ins already recorded
        log.warning("optouts: opt-in decisions not fetched: %r", e)
        later, regulations = None, []
    for celex in todo:
        if deadline is not None and time.monotonic() > deadline:
            break
        url = EURLEX_URL.format(celex=celex)
        src = SourceRef(institution="EUR-Lex", url=url, label=f"EUR-Lex – text of CELEX {celex}", identifier=celex,
                        retrieved_at=attempted)  # fmt: skip
        try:
            text = plain_text(fetch_text(http, celex))
        except Exception as e:  # noqa: BLE001 - one missing text must not stop the others
            log.warning("optouts: %s text not fetched: %r", celex, e)
            unavailable += 1
            if celex not in done or done[celex].status != "ok":  # else the earlier reading stays until a re-read
                out.append(DirectiveOptOut(celex=celex, status="unavailable", url=url, source=src))
            continue
        countries, quotes = not_bound(text)
        schengen = schengen_art4(text) if "DK" in countries else None
        if schengen:
            quotes = [*quotes, schengen]
        out.append(DirectiveOptOut(celex=celex, status="ok", not_bound=countries, quotes=quotes, url=url, source=src,
                                   schengen_art4=["DK"] if schengen else [], parser=PARSER_VERSION))  # fmt: skip
    read_now = sum(1 for r in out if r.status == "ok")

    def stored(celex: str) -> dict[str, str]:
        return done[celex].opted_in if celex in done else {}

    kept: list[str] = []  # opt-ins recorded earlier that this run's answer lacks: kept (see the module docstring)
    if later is not None:  # every record carries the opt-ins as last queried, and those recorded earlier
        fresh = {r.celex for r in out}
        out += [r for c, r in done.items() if c not in fresh]
        kept = [f"{r.celex} {c} ({d})" for r in out for c, d in sorted(stored(r.celex).items())
                if c not in later.get(r.celex, {})]  # fmt: skip
        # regulations: the decisions recorded earlier stay (upsert), those this answer lacks are reported
        answered = {r.decision for r in regulations}
        kept += [f"{r.celex} {r.country} ({r.decision})" for r in read_records(SOURCE_ID, "regulations",
                 RegulationOptIn) if r.decision not in answered]  # fmt: skip
        upsert_records(SOURCE_ID, "regulations", RegulationOptIn, regulations, id_of=lambda r: r.decision)
    out = [r.model_copy(update={"opted_in": {**stored(r.celex), **(later or {}).get(r.celex, {})}}) for r in out]
    total = upsert_records(SOURCE_ID, "directives", DirectiveOptOut, out, id_of=lambda r: r.celex)
    merged = read_records(SOURCE_ID, "directives", DirectiveOptOut)
    n_regulations = len(read_records(SOURCE_ID, "regulations", RegulationOptIn))
    ok = [r for r in merged if r.status == "ok" and r.parser >= PARSER_VERSION]
    pending = len([c for c in directives if c not in {r.celex for r in ok}])
    by_country = {c: sum(1 for r in ok if c in r.not_bound and c not in r.opted_in) for c in ("DK", "IE")}
    n_opt_in = sum(len(r.opted_in) for r in merged)
    prev = read_manifest().get(SOURCE_ID)
    return SourceStatus(
        source=SOURCE_ID,
        status="ok" if not (pending or later is None or kept) else "partial",
        # a run that retrieved nothing (no text read, opt-in query failed) keeps the last retrieval time
        fetched_at=now_iso() if read_now or later is not None or prev is None else prev.fetched_at,
        attempted_at=attempted,
        records={"directives_read": len(ok), "pending": pending, "not_bound_DK": by_country["DK"],
                 "not_bound_IE": by_country["IE"], "regulations": n_regulations},  # fmt: skip
        note=(
            f"{len(ok)} of {len(directives)} directives read ({len(todo)} this run, {unavailable} unavailable); "
            f"recitals declare Denmark not bound by {by_country['DK']} and Ireland by {by_country['IE']}"
            f" (net of {n_opt_in} later opt-ins confirmed by the Commission"
            + ("" if later is not None else ", as last recorded: the query failed this run")
            + f"); {n_regulations} later opt-ins to regulations confirmed by the Commission"
            + (f"; this run's answer lacked {len(kept)} opt-ins recorded earlier, kept: {', '.join(kept)}"
               if kept else "")  # fmt: skip
            + (f"; {pending} pending, resumed next run" if pending else "")
            + f"; {total} records"
        ),
    )
