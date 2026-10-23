"""Treaty opt-outs that a directive itself records in its recitals (EUR-Lex text, via Cellar).

Denmark (Protocol No 22) and Ireland (Protocol No 21) take part in measures in the area of freedom,
security and justice only if they opt in. Each such directive says in its recitals, in standard
wording, which of them are not bound, e.g. Directive (EU) 2016/343, recital 51: "In accordance with
Articles 1 and 2 of Protocol No 22 ..., Denmark is not taking part in the adoption of this Directive and
is not bound by it or subject to its application." The Council's voting results record the same fact
only for votes since 2019, and Cellar has no property for it.

Produces data/snapshot/optouts/directives.json: one record per directive of the EUR-Lex snapshot whose
text has been read, with the countries its recitals declare not bound and the sentences quoted. The
text of an adopted act does not change, so each directive is read once; texts that could not be
fetched are retried on the next run. Stops starting new downloads after EU_INTEL_FETCH_BUDGET_S.

Request: GET https://publications.europa.eu/resource/celex/{CELEX} with Accept: application/xhtml+xml
(else text/html) and Accept-Language: eng (Cellar content negotiation; the English expression).
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any

from pipeline.http import HttpError
from pipeline.models.entities import DirectiveOptOut, LegalAct, SourceRef, SourceStatus
from pipeline.snapshot import fetch_deadline, now_iso, read_records, upsert_records

log = logging.getLogger("pipeline.sources.optouts")

SOURCE_ID = "optouts"
CELEX_URL = "https://publications.europa.eu/resource/celex/{celex}"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
COUNTRIES = {"Denmark": "DK", "Ireland": "IE"}
# "... , Denmark is not taking part in the adoption of this Directive and is not bound by it ..."
NOT_BOUND_RE = re.compile(
    r"([^.;]{0,400}?)\b(?:is|are) not taking part in the adoption of this Directive,? and (?:is|are) not bound by it",
    re.IGNORECASE,
)


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
    todo = [c for c in directives if c not in done or done[c].status != "ok"]
    deadline = fetch_deadline()
    out: list[DirectiveOptOut] = []
    unavailable = 0
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
            out.append(DirectiveOptOut(celex=celex, status="unavailable", url=url, source=src))
            continue
        countries, quotes = not_bound(text)
        out.append(DirectiveOptOut(celex=celex, status="ok", not_bound=countries, quotes=quotes, url=url, source=src))
    total = upsert_records(SOURCE_ID, "directives", DirectiveOptOut, out, id_of=lambda r: r.celex)
    merged = read_records(SOURCE_ID, "directives", DirectiveOptOut)
    ok = [r for r in merged if r.status == "ok"]
    pending = len([c for c in directives if c not in {r.celex for r in ok}])
    by_country = {c: sum(1 for r in ok if c in r.not_bound) for c in ("DK", "IE")}
    return SourceStatus(
        source=SOURCE_ID,
        status="ok" if not pending else "partial",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"directives_read": len(ok), "pending": pending, "not_bound_DK": by_country["DK"],
                 "not_bound_IE": by_country["IE"]},  # fmt: skip
        note=(
            f"{len(ok)} of {len(directives)} directives read ({len(out)} this run, {unavailable} unavailable); "
            f"recitals declare Denmark not bound by {by_country['DK']} and Ireland by {by_country['IE']}"
            + (f"; {pending} pending, resumed next run" if pending else "")
            + f"; {total} records"
        ),
    )
