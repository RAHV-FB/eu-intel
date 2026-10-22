"""How Member States transpose and apply EU law.

Three independent sub-sources; each output file is written only if its sub-source succeeded:

1. National implementing measures ("MNE"/NIM) -> data/snapshot/implementation/measures.json
   Source: Publications Office Cellar SPARQL. Cellar models each notified national measure as a
   `cdm:measure_national_implementing` work linked to the directive by
   `cdm:measure_national_implementing_implements_resource_legal`, with the notifying country in
   `..._implemented_by_country`, the Commission reference in `..._reference_commission`
   ("MNE(2025)04528"), the national official-journal publication date in `..._date_official_journal`
   and the title on the work or its expression. One measure may be notified for several directives;
   it then carries one CELEX-like id per directive ("72022L2555CZE_202504528"), which we use as id.
   Scope: directives (CELEX 3YYYYLNNNN) dated 2014-01-01 or later, plus directives listed under a
   `celex` key in data/curated/featured.yaml. Human list: EUR-Lex NIM page of the directive.
   coverage.json lists every directive whose measures were queried successfully, including those
   with 0 measures; a directive absent from coverage.json was not covered by this dataset.

   A notified measure is what the Member State told the Commission; it is NOT an assessment that
   the directive is correctly or completely transposed. Absence of records for a country is NOT a
   finding of non-transposition: the UI must say NO_MEASURES_LABEL.

2. Infringement cases -> infringements.json
   Source: the Commission's infringement decisions register (Themis), whose public web app is
   backed by a JSON API (POST <base>/api/infringements) and an .xlsx export
   (POST <base>/api/INFRINGEMENTS/export). Scope: all open cases, plus every case with a decision
   dated 2019-01-01 or later. The latest stage is the register's decision type, verbatim.
   `legal_basis` is the register's own "Legal basis" column (export), as given; `celex` is set only
   when it names exactly one EU act.
   An open case at e.g. "Referral to Court" is not a Court judgment.

3. Country indicators (Single Market Scoreboard) -> indicators.json
   single-market-scoreboard.ec.europa.eu rejects scripted access (CloudFront 403), and no other
   official machine-readable distribution of the current figures was found (data.europa.eu only
   links 2019 HTML/PDF; Eurostat tsdgo220 was discontinued in 2018). We probe the host and record
   the result; nothing is written until an official machine-readable source is available.
   We never compute a compliance score ourselves.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from lxml import etree

from pipeline import snapshot
from pipeline.http import Http, HttpError
from pipeline.models.countries import MEMBER_STATES, normalize_country
from pipeline.models.entities import (
    CountryIndicator,
    ImplementationCoverage,
    InfringementCase,
    NationalMeasure,
    SourceRef,
    SourceStatus,
)

log = logging.getLogger("pipeline.sources.implementation")

SOURCE_ID = "implementation"
MAX_WORKERS = 4

# Text the site shows for a directive/country pair without records. Absence of a record means only
# that the dataset holds no notified measure; it is not a finding of non-transposition.
NO_MEASURES_LABEL = "No measures found in the available dataset"

DIRECTIVE_CELEX_RE = re.compile(r"^3\d{4}L\d{4}$")
SECONDARY_LAW_CELEX_RE = re.compile(r"^3\d{4}[A-Z]\d{4}$")

# ---------------------------------------------------------------- national implementing measures
MEASURES_SINCE = "2014-01-01"
EURLEX_NIM_URL = "https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:{celex}"
NIM_LABEL = "EUR-Lex – national transposition measures"
FEATURED_YAML = snapshot.CURATED / "featured.yaml"
# Cellar uses placeholder dates for unknown values (e.g. "1001-01-01" official-journal date).
_SENTINEL_DATES = {"1001-01-01", "9999-12-31"}

_XSD_STRING = "<http://www.w3.org/2001/XMLSchema#string>"
_PREFIXES = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX cmr: <http://publications.europa.eu/ontology/cdm/cmr#>
"""


def is_directive_celex(celex: str | None) -> bool:
    """True only for a directive's CELEX (sector 3, type L), e.g. "32022L2555"; not corrigenda."""
    return bool(celex) and bool(DIRECTIVE_CELEX_RE.match(celex))


def nim_url(celex: str) -> str:
    return EURLEX_NIM_URL.format(celex=celex)


def directives_query(since: str = MEASURES_SINCE) -> str:
    return (
        _PREFIXES
        + f"""SELECT DISTINCT ?celex WHERE {{
  ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?d .
  FILTER(REGEX(STR(?celex), "^3[0-9]{{4}}L[0-9]{{4}}$")
         && ?d >= "{since}"^^<http://www.w3.org/2001/XMLSchema#date>)
}}"""
    )


def measures_query(celex: str) -> str:
    if not is_directive_celex(celex):
        raise ValueError(f"transposition measures exist only for directives, got {celex!r}")
    return (
        _PREFIXES
        + f"""SELECT ?m ?mc ?country ?mne ?msref ?journal ?doj ?dnot ?wtitle ?etitle ?link ?eli ?modified WHERE {{
  ?w cdm:resource_legal_id_celex "{celex}"^^{_XSD_STRING} .
  ?m cdm:measure_national_implementing_implements_resource_legal ?w .
  OPTIONAL {{ ?m cdm:measure_national_implementing_implemented_by_country ?country }}
  OPTIONAL {{ ?m cdm:resource_legal_id_celex ?mc . FILTER(STRSTARTS(STR(?mc), "7{celex[1:]}")) }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_reference_commission ?mne }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_reference_member-state ?msref }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_name_official_journal ?journal }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_date_official_journal ?doj }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_date_notification ?dnot }}
  OPTIONAL {{ ?m cdm:work_title ?wtitle }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?m ; cdm:expression_title ?etitle }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_national_website_link ?link }}
  OPTIONAL {{ ?m cdm:eli ?eli }}
  OPTIONAL {{ ?m cmr:lastModificationDate ?modified }}
}}"""
    )


def _clean_date(value: str | None) -> str | None:
    """ISO date from a Cellar date/datetime literal; None for missing or placeholder values."""
    if not value:
        return None
    d = value[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d) or d in _SENTINEL_DATES or d < "1500":
        return None
    return d


def _http_url(value: str | None) -> str | None:
    if value and re.match(r"^https?://", value.strip()):
        return value.strip()
    return None


def parse_measure_rows(
    celex: str, rows: Iterable[dict[str, str]], retrieved_at: str
) -> list[NationalMeasure]:
    """Turn SPARQL rows of `measures_query(celex)` into one NationalMeasure per (measure, directive).

    Only facts present in Cellar are used; there are no placeholder records for countries without
    measures.
    """
    if not is_directive_celex(celex):
        raise ValueError(f"transposition measures exist only for directives, got {celex!r}")
    by_measure: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        if r.get("m"):
            by_measure.setdefault(r["m"], []).append(r)

    def first(rs: list[dict[str, str]], key: str) -> str | None:
        vals = sorted({r[key].strip() for r in rs if r.get(key) and r[key].strip()})
        return vals[0] if vals else None

    out: list[NationalMeasure] = []
    for uri, rs in by_measure.items():
        country = normalize_country(first(rs, "country"))
        if not country:
            log.debug("measure %s: no EU country, skipped", uri)
            continue
        mne = first(rs, "mne")
        measure_id = first(rs, "mc") or f"{celex}:{uri.rsplit('/', 1)[-1]}"
        out.append(
            NationalMeasure(
                id=measure_id,
                directive_celex=celex,
                country=country,
                title=first(rs, "etitle") or first(rs, "wtitle"),
                # Publication date in the national official journal, as recorded by Cellar.
                date=_clean_date(first(rs, "doj")),
                commission_ref=mne,
                national_ref=first(rs, "msref"),
                journal=first(rs, "journal"),
                notified=_clean_date(first(rs, "dnot")),
                url=_http_url(first(rs, "link")) or _http_url(first(rs, "eli")),
                source=SourceRef(
                    institution="EUR-Lex",
                    url=nim_url(celex),
                    label=NIM_LABEL,
                    identifier=mne,
                    retrieved_at=retrieved_at,
                    published=_clean_date(first(rs, "modified")),
                ),
            )
        )
    return out


def featured_directives(path: Path | None = None) -> list[str]:
    """Directive CELEX numbers listed under any `celex` key of the curated featured file."""
    path = path or FEATURED_YAML
    if not path.exists():
        return []
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).lower() == "celex":
                    for c in v if isinstance(v, list) else [v]:
                        if isinstance(c, str):
                            found.append(c.strip())
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return sorted({c for c in found if is_directive_celex(c)})


def coverage_entry(celex: str, measures: int, retrieved_at: str) -> ImplementationCoverage:
    return ImplementationCoverage(
        celex=celex,
        measures=measures,
        source=SourceRef(
            institution="EUR-Lex",
            url=nim_url(celex),
            label=NIM_LABEL,
            identifier=celex,
            retrieved_at=retrieved_at,
        ),
    )


def fetch_measures(
    http: Http,
) -> tuple[list[NationalMeasure], list[ImplementationCoverage], dict[str, Any]]:
    """Returns (records, coverage, info). Raises if the directive list cannot be obtained.

    `coverage` lists every directive whose measures were successfully queried, including those
    with 0 measures ("No measures found in the available dataset"). A directive whose query fails
    keeps its previous records and coverage entry (if any); without a previous entry it is left out
    of coverage ("not covered"), so a transient error never turns into "no measures found".
    """
    retrieved_at = snapshot.now_iso()
    scope = {r["celex"] for r in http.sparql(directives_query()) if is_directive_celex(r.get("celex"))}
    scope |= set(featured_directives())
    celexes = sorted(scope)

    def one(celex: str) -> tuple[str, list[NationalMeasure] | None]:
        try:
            return celex, parse_measure_rows(celex, http.sparql(measures_query(celex)), retrieved_at)
        except (HttpError, KeyError, ValueError) as e:
            log.warning("NIM query failed for %s: %s", celex, e)
            return celex, None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(one, celexes))

    failed = [c for c, recs in results if recs is None]
    records = [m for _, recs in results if recs for m in recs]
    coverage = [coverage_entry(c, len(recs), retrieved_at) for c, recs in results if recs is not None]
    if failed:
        keep = set(failed)
        records += [
            m
            for m in snapshot.read_records(SOURCE_ID, "measures", NationalMeasure)
            if m.directive_celex in keep
        ]
        coverage += [
            c for c in snapshot.read_records(SOURCE_ID, "coverage", ImplementationCoverage) if c.celex in keep
        ]
    info = {
        "directives": len(celexes),
        "covered": len(coverage),
        "with_measures": len({m.directive_celex for m in records}),
        "failed": failed,
    }
    return records, coverage, info


# ---------------------------------------------------------------------------- infringements
THEMIS_BASE = "https://ec.europa.eu/implementing-eu-law/search-infringement-decisions/"
THEMIS_API = THEMIS_BASE + "api"
INFRINGEMENTS_SINCE_YEAR = 2019
PAGE_SIZE = 1000
_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\b")


def themis_case_url(case_id: str) -> str:
    """Deep link understood by the register's web app (its own `version=v1` query format)."""
    return f"{THEMIS_BASE}?version=v1&typeOfSearch=byCase&refId={quote(case_id)}&langCode=EN"


def _search_body(**filters: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "refId": None,
        "relatedPetition": None,
        "petition": None,
        "decisionDateFrom": None,
        "decisionDateTo": None,
        "langCode": "EN",
        "memberState": None,
        "decisionCategory": None,
        "infringementType": None,
        "activeCase": None,
        "pressRelease": None,
        "page": 0,
        "size": PAGE_SIZE,
        "title": None,
        "legalBasis": None,
        "dg": None,
        "policyArea": None,
        "courtFinancialSanctions": None,
        "order": "desc",
        "sortColumns": "refId",
    }
    body.update(filters)
    return body


def _post_json(
    http: Http, path: str, body: dict[str, Any], accept: str = "application/json", use_cache: bool = True
) -> bytes:
    # The register's API only accepts a JSON request body (form posts get 415, GET 405).
    return http.request(
        "POST", THEMIS_API + path, json_body=body, headers={"Accept": accept}, use_cache=use_cache
    )


def search_cases(http: Http, **filters: Any) -> list[dict[str, Any]]:
    """All case records matching the filters (register search 'by case'), paging through results."""
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        d = json.loads(_post_json(http, "/infringements", _search_body(page=page, **filters)))
        recs = d.get("records") or []
        out.extend(recs)
        total = d.get("totalRows") or 0
        if not recs or len(out) >= total or page > 200:
            break
        page += 1
    return out


def read_xlsx_rows(content: bytes) -> list[dict[str, str | None]]:
    """Rows of the first worksheet of an .xlsx file as {header: value} (no external dependency)."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(io.BytesIO(content))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = etree.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(si.itertext()) for si in root.findall(f"{ns}si")]
    rows: list[dict[str, str | None]] = []
    for row in etree.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{ns}row"):
        cells: dict[str, str | None] = {}
        for c in row.findall(f"{ns}c"):
            col = re.match(r"[A-Z]+", c.get("r") or "")
            if not col:
                continue
            v = c.find(f"{ns}v")
            if v is None:
                inline = c.find(f"{ns}is")
                val = "".join(inline.itertext()) if inline is not None else None
            elif c.get("t") == "s":
                val = shared[int(v.text or 0)]
            else:
                val = v.text
            cells[col.group()] = val
        rows.append(cells)
    if not rows:
        return []
    header = {col: (name or "").strip() for col, name in rows[0].items()}
    return [{header[col]: val for col, val in r.items() if col in header} for r in rows[1:]]


def parse_export_legal_basis(content: bytes) -> dict[str, list[str]]:
    """Case id -> CELEX numbers in the export's "Legal basis" column (one per line, as given)."""
    out: dict[str, list[str]] = {}
    for r in read_xlsx_rows(content):
        case_id = (r.get("Infringement case number") or "").strip()
        if not case_id:
            continue
        values = [x.strip() for x in (r.get("Legal basis") or "").splitlines() if x.strip()]
        out[case_id] = list(dict.fromkeys(values))  # as given, de-duplicated, order kept
    return out


def single_act_celex(legal_basis: list[str] | None) -> str | None:
    """The CELEX of the act a case concerns, only when the register names exactly one EU act.

    Treaty articles (sector 1, e.g. "12008E258") are ignored; several secondary-law acts -> None
    (we do not choose between them).
    """
    acts = sorted({c for c in legal_basis or [] if SECONDARY_LAW_CELEX_RE.match(c)})
    return acts[0] if len(acts) == 1 else None


def _ddmmyyyy(value: str | None) -> str | None:
    m = _DATE_RE.match(value or "")
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def country_names(refdata: dict[str, Any] | None) -> dict[str, str]:
    """English country name used by the register -> ISO alpha-2 (from its reference data)."""
    names = {v: k for k, v in MEMBER_STATES.items()} | {"United Kingdom": "GB"}
    for x in (refdata or {}).get("memberState", []):
        if x.get("language") == "EN" and x.get("title"):
            iso = normalize_country(x.get("key"))
            if iso:
                names[x["title"]] = iso
    return names


def _latest_value(decisions: list[dict[str, Any]], field: str) -> str | None:
    """`field` of the most recent decision that has it (register order breaks date ties)."""
    dated = [
        (_ddmmyyyy(d.get("decisionDate")) or "", i, str(d[field]).strip())
        for i, d in enumerate(decisions)
        if d.get(field) and str(d[field]).strip()
    ]
    return max(dated)[2] if dated else None


def parse_case(
    rec: dict[str, Any],
    names: dict[str, str],
    retrieved_at: str,
    legal_basis: dict[str, list[str]] | None = None,
) -> InfringementCase | None:
    case_id = (rec.get("infringementNumber") or "").strip()
    country = names.get((rec.get("memberState") or "").strip())
    if not case_id or not country:
        return None
    decisions = [d for d in rec.get("decisions") or [] if _ddmmyyyy(d.get("decisionDate"))]
    latest = None
    if decisions:
        # Stable max: on equal dates the decision listed last by the register wins.
        latest = max(enumerate(decisions), key=lambda x: (_ddmmyyyy(x[1].get("decisionDate")), x[0]))[1]
    active = rec.get("activeInfringementCase")
    noncom = rec.get("nonCommunicationCase")
    basis = (legal_basis or {}).get(case_id, [])
    return InfringementCase(
        id=case_id,
        country=country,
        celex=single_act_celex(basis),
        legal_basis=basis,
        court_ref=_latest_value(decisions, "normalCuriaReference"),
        press_release_url=_http_url(_latest_value(decisions, "pressReleaseURL")),
        title=(rec.get("title") or "").strip() or case_id,
        non_communication={"Yes": True, "No": False}.get(noncom),
        latest_stage=latest.get("decisionType") if latest else None,  # verbatim
        latest_decision_date=_ddmmyyyy(latest.get("decisionDate")) if latest else None,
        status={"Yes": "open", "No": "closed"}.get(active, "unknown"),
        source=SourceRef(
            institution="Commission",
            url=themis_case_url(case_id),
            label="European Commission – infringement decisions register",
            identifier=case_id,
            retrieved_at=retrieved_at,
        ),
    )


def _export_legal_basis_checked(http: Http, filters: dict[str, Any]) -> dict[str, list[str]] | None:
    """Legal basis per case from one export slice, or None if it fails or is inconsistent."""
    try:
        expected = json.loads(_post_json(http, "/infringements", _search_body(size=1, **filters)))[
            "totalRows"
        ]
        for use_cache in (True, False):
            content = _post_json(
                http,
                "/INFRINGEMENTS/export",
                _search_body(**filters),
                accept="application/octet-stream",
                use_cache=use_cache,
            )
            part = parse_export_legal_basis(content)
            if len(part) == expected:
                return part
            log.warning("register export %s: %d rows, search says %d; retrying", filters, len(part), expected)
    except (HttpError, zipfile.BadZipFile, etree.XMLSyntaxError, KeyError, ValueError) as e:
        log.warning("register export failed (%s): %s", filters, e)
    return None


def _export_filters(this_year: int) -> list[dict[str, Any]]:
    """Export slices covering the case scope; each slice stays small enough for one request."""
    slices: list[dict[str, Any]] = [{"activeCase": "true"}]
    for y in range(INFRINGEMENTS_SINCE_YEAR, this_year + 1):
        slices.append({"decisionDateFrom": f"01/01/{y}", "decisionDateTo": f"31/12/{y}"})
    return slices


def fetch_infringements(http: Http) -> tuple[list[InfringementCase], dict[str, Any]]:
    """Returns (records, info). Raises if the case search fails (nothing is written then)."""
    retrieved_at = snapshot.now_iso()
    try:
        refdata = http.get_json(THEMIS_API + "/referencedata/loadAll", headers={"Accept": "application/json"})
    except (HttpError, ValueError) as e:
        log.warning("register reference data unavailable: %s", e)
        refdata = None
    names = country_names(refdata)

    raw: dict[str, dict[str, Any]] = {}
    for filters in ({"activeCase": "true"}, {"decisionDateFrom": f"01/01/{INFRINGEMENTS_SINCE_YEAR}"}):
        for rec in search_cases(http, **filters):
            if rec.get("infringementNumber"):
                raw[rec["infringementNumber"]] = rec

    legal_basis: dict[str, list[str]] = {}
    failed_exports: list[str] = []

    # Exports run one at a time: concurrent export requests were observed to return row sets that
    # did not match their filters. Each export is checked against the search's row count.
    for filters in _export_filters(datetime.now(UTC).year):
        label = ",".join(f"{k}={v}" for k, v in filters.items())
        part = _export_legal_basis_checked(http, filters)
        if part is None:
            failed_exports.append(label)
        else:
            legal_basis.update(part)

    records: list[InfringementCase] = []
    skipped = 0
    for rec in raw.values():
        case = parse_case(rec, names, retrieved_at, legal_basis)
        if case is None:
            skipped += 1
        else:
            records.append(case)
    info = {
        "cases": len(records),
        "skipped": skipped,
        "without_legal_basis_data": sum(1 for c in records if c.id not in legal_basis),
        "failed_exports": failed_exports,
    }
    return records, info


# ---------------------------------------------------------------------------- indicators
SCOREBOARD_URL = "https://single-market-scoreboard.ec.europa.eu/"


def fetch_indicators(http: Http) -> tuple[list[CountryIndicator] | None, str]:
    """No official machine-readable distribution is reachable yet; probe and report."""
    try:
        http.get(SCOREBOARD_URL, headers={"Accept": "text/html"}, use_cache=False)
    except HttpError as e:
        return None, f"Single Market Scoreboard unreachable (HTTP {e.status or 'error'})"
    return None, "Single Market Scoreboard reachable, but no machine-readable data parser is implemented"


# ---------------------------------------------------------------------------- entry point
def fetch(http: Http) -> SourceStatus:
    attempted = snapshot.now_iso()
    notes: list[str] = []
    counts: dict[str, int] = {}
    ok_parts = 0

    try:
        measures, coverage, mi = fetch_measures(http)
        snapshot.write_records(
            SOURCE_ID, "measures", measures, key=lambda m: (m.directive_celex, m.country, m.date or "", m.id)
        )
        snapshot.write_records(SOURCE_ID, "coverage", coverage, key=lambda c: c.celex)
        counts["measures"] = len(measures)
        counts["coverage"] = len(coverage)
        note = (
            f"measures: {mi['covered']}/{mi['directives']} directives covered, "
            f"{mi['with_measures']} with records"
        )
        if mi["failed"]:
            note += f"; {len(mi['failed'])} directive queries failed (previous records kept)"
        else:
            ok_parts += 1
        notes.append(note)
    except Exception as e:  # noqa: BLE001 - sub-source failure must not stop the others
        log.exception("measures sub-source failed")
        notes.append(f"measures failed: {e!r}"[:200])

    try:
        cases, ci = fetch_infringements(http)
        snapshot.write_records(SOURCE_ID, "infringements", cases, key=lambda c: c.id)
        counts["infringements"] = len(cases)
        note = f"infringements: {ci['cases']} cases"
        if ci["failed_exports"]:
            note += f"; legal-basis export failed for {len(ci['failed_exports'])} slices"
        else:
            ok_parts += 1
        notes.append(note)
    except Exception as e:  # noqa: BLE001
        log.exception("infringements sub-source failed")
        notes.append(f"infringements failed: {e!r}"[:200])

    try:
        indicators, inote = fetch_indicators(http)
        if indicators is not None:
            snapshot.write_records(
                SOURCE_ID, "indicators", indicators, key=lambda i: (i.indicator, i.country, i.period)
            )
            counts["indicators"] = len(indicators)
            ok_parts += 1
        notes.append(f"indicators: {inote}")
    except Exception as e:  # noqa: BLE001
        log.exception("indicators sub-source failed")
        notes.append(f"indicators failed: {e!r}"[:200])

    status = "ok" if ok_parts == 3 else ("partial" if counts else "failed")
    return SourceStatus(
        source=SOURCE_ID,
        status=status,
        fetched_at=snapshot.now_iso() if counts else None,
        attempted_at=attempted,
        records=counts,
        note="; ".join(notes),
    )
