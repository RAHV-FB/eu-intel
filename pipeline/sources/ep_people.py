"""European Parliament people & organizations (EP Open Data API v2).

Produces data/snapshot/ep_people/meps.json (list[Mep]) and orgs.json (list[Organization]) for every
MEP who sat in the 9th or 10th parliamentary term, with their political-group, national-party and
committee memberships in those terms, and the organizations those memberships reference.

Requests (all batched; the API allows comma-separated ids and at most 500 requests / 5 min):
    /meps?parliamentary-term=9|10      ids of every MEP of each term (current and former)
    /meps/show-current                 who is sitting today -> Mep.active
    /meps/{id,id,...}                  full person records incl. all memberships (50 per request)
    /corporate-bodies/{id,id,...}      groups, national parties, committees (50 per request)

Source facts relied on (checked against the live API, see tests/test_ep_people.py):
- Each membership has its own period; group memberships are split at role changes (MEMBER ->
  CHAIR_VICE ...) and never overlap; the end date is the last day of membership.
- Mandates are memberships with role MEMBER_PARLIAMENT in org "ep-<term>", carrying the country
  represented. Two one-day 2019 mandates have no organization; their term comes from the date.
- Group/party/committee memberships never cross a term boundary (orgs are re-created per term).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.http import EP_API, Http
from pipeline.models.countries import normalize_country
from pipeline.models.entities import Membership, Mep, Organization, SourceRef, SourceStatus
from pipeline.snapshot import now_iso, write_records

SOURCE_ID = "ep_people"
FMT = {"format": "application/ld+json"}
BATCH = 50
WORKERS = 2  # the API is shared with other pipeline sources; stay well below its rate limit
PAGE = 1000

# Term periods (first and last sitting day). The 10th term is ongoing.
TERMS: dict[int, tuple[str, str | None]] = {9: ("2019-07-02", "2024-07-15"), 10: ("2024-07-16", None)}

# EP corporate-body classification -> Membership/Organization kind (others, e.g. delegations, skipped)
KINDS = {
    "EU_POLITICAL_GROUP": "group",
    "NATIONAL_POLITICAL_GROUP": "party",
    "COMMITTEE_PARLIAMENTARY_STANDING": "committee",
    "COMMITTEE_PARLIAMENTARY_SUB": "committee",
    "COMMITTEE_PARLIAMENTARY_TEMPORARY": "committee",
    "COMMITTEE_PARLIAMENTARY_SPECIAL": "committee",
}

# Official EP group labels whose familiar English abbreviation (as used on europarl.europa.eu/en) differs.
# All other labels ("S&D", "Renew", "ECR", "PfE", "ESN", "ID", "NI", "The Left") are kept as given. The
# 9th-term "GUE/NGL" group (org 5151, until 2020-12-18) is a distinct body in the source (isVersionOf
# org/GUE-NGL vs org/THE-LEFT) and the API itself reports "GUE/NGL" for dates before the rename: kept.
GROUP_CODES = {"PPE": "EPP", "Verts/ALE": "Greens/EFA"}


# ------------------------------------------------------------------------------------------- fetching
def _list(http: Http, path: str, **params: Any) -> list[dict]:
    out: list[dict] = []
    while True:
        page = http.get_json(f"{EP_API}{path}", params={**FMT, **params, "offset": len(out), "limit": PAGE})
        out += page["data"]
        if len(page["data"]) < PAGE:
            return out


def _details(http: Http, path: str, ids: list[str]) -> dict[str, dict]:
    """Fetch full records for ids in batches of BATCH (sorted, so requests are stable and cacheable)."""
    ids = sorted(set(ids), key=lambda x: (len(x), x))
    chunks = [ids[i : i + BATCH] for i in range(0, len(ids), BATCH)]

    def one(chunk: list[str]) -> list[dict]:
        return http.get_json(f"{EP_API}{path}/{','.join(chunk)}", params=FMT)["data"]

    with ThreadPoolExecutor(WORKERS) as ex:
        return {r["identifier"]: r for batch in ex.map(one, chunks) for r in batch}


# ------------------------------------------------------------------------------------------- parsing
def _suffix(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def _period(rec: dict, key: str) -> tuple[str | None, str | None]:
    p = rec.get(key) or {}
    return p.get("startDate"), p.get("endDate")


def term_of(day: str | None) -> int | None:
    for term, (start, end) in TERMS.items():
        if day and start <= day and (end is None or day <= end):
            return term
    return None


def display_name(p: dict) -> str:
    given, family = p.get("givenName"), p.get("familyName")
    return f"{given} {family}" if given and family else p["label"]


def parse_mep(p: dict, active: bool, list_terms: set[int], retrieved_at: str) -> Mep:
    memberships: list[Membership] = []
    mandates: list[tuple[str, str | None]] = []  # (start, country)
    terms = set(list_terms)
    for m in p.get("hasMembership", []):
        start, end = _period(m, "memberDuring")
        if m.get("role") == "def/ep-roles/MEMBER_PARLIAMENT":
            org = _suffix(m.get("organization")) or ""
            terms.add(int(org[3:]) if org.startswith("ep-") else (term_of(start) or 0))
            mandates.append((start or "", normalize_country((m.get("represents") or [None])[0])))
            continue
        kind = KINDS.get(_suffix(m.get("membershipClassification")) or "")
        term = term_of(start)
        if kind and m.get("organization") and term in TERMS:
            memberships.append(
                Membership(
                    org_id=_suffix(m["organization"]),
                    kind=kind,
                    role=_suffix(m.get("role")),
                    start=start,
                    end=end,
                    term=term,
                )
            )
    memberships.sort(key=lambda x: (x.start or "", x.kind, x.org_id, x.role or ""))
    country = next((c for _, c in sorted(mandates, key=lambda x: x[0], reverse=True) if c), None)
    if not country:
        raise ValueError(f"MEP {p['identifier']}: no country of representation in any mandate")
    url = f"https://www.europarl.europa.eu/meps/en/{p['identifier']}"
    return Mep(
        id=p["identifier"],
        name=display_name(p),
        given_name=p.get("givenName"),
        family_name=p.get("familyName"),
        sort_label=p.get("sortLabel"),
        country=country,
        active=active,
        terms=sorted(t for t in terms if t),
        memberships=memberships,
        official_url=url,
        photo_url=None,  # portraits are not hotlinked (privacy); see report / DATA_SOURCES.md
        source=SourceRef(
            institution="EP",
            url=url,
            label=f"EP Open Data API – MEP {p['identifier']}",
            identifier=p["identifier"],
            retrieved_at=retrieved_at,
        ),
    )


def parse_org(o: dict, retrieved_at: str) -> Organization:
    kind = KINDS[_suffix(o.get("classification")) or ""]
    short = o.get("label")
    full = (o.get("prefLabel") or {}).get("en") or short
    if kind == "group":
        code = GROUP_CODES.get(short, short)
    elif kind == "party":  # national parties: label is the acronym when it differs from the name
        code = short if short and short != full else None
    else:
        code = short
    start, end = _period(o, "temporal")
    return Organization(
        id=o["identifier"],
        kind=kind,
        code=code,
        label=full,
        country=normalize_country((o.get("represents") or [None])[0]) if kind == "party" else None,
        start=start,
        end=end,
        source=SourceRef(
            institution="EP",
            url=f"{EP_API}/corporate-bodies/{o['identifier']}?format=application%2Fld%2Bjson",
            label=f"EP Open Data API – corporate body {short}",
            identifier=o["identifier"],
            retrieved_at=retrieved_at,
        ),
    )


def current_group(mep: Mep, orgs: dict[str, Organization]) -> list[str | None]:
    return [
        orgs[m.org_id].code if m.org_id in orgs else None
        for m in mep.memberships
        if m.kind == "group" and m.end is None
    ]


def cross_check(meps: list[Mep], orgs: list[Organization], current: dict[str, dict]) -> list[str]:
    """Compare each active MEP's open group membership and country with /meps/show-current."""
    by_id = {o.id: o for o in orgs}
    out = []
    for mep in meps:
        row = current.get(mep.id)
        if not row:
            continue
        label = row.get("api:political-group")
        if current_group(mep, by_id) != [GROUP_CODES.get(label, label)]:
            out.append(f"MEP {mep.id}: current group {current_group(mep, by_id)} != show-current {label!r}")
        if mep.country != normalize_country(row.get("api:country-of-representation")):
            out.append(f"MEP {mep.id}: country {mep.country} != show-current")
    return out


# ------------------------------------------------------------------------------------------- entry
def fetch(http: Http) -> SourceStatus:
    attempted = now_iso()
    term_ids: dict[str, set[int]] = {}
    for term in TERMS:
        for r in _list(http, "/meps", **{"parliamentary-term": term}):
            term_ids.setdefault(r["identifier"], set()).add(term)
    current = {r["identifier"]: r for r in _list(http, "/meps/show-current")}
    people = _details(http, "/meps", list(term_ids))
    retrieved = now_iso()
    problems = [f"MEP {i} not returned" for i in term_ids if i not in people]
    problems += [f"current MEP {i} not in term lists" for i in current.keys() - term_ids.keys()]

    meps = [parse_mep(people[i], i in current, term_ids[i], retrieved) for i in term_ids if i in people]
    org_ids = {m.org_id for mep in meps for m in mep.memberships}
    raw_orgs = _details(http, "/corporate-bodies", list(org_ids))
    orgs = [parse_org(o, retrieved) for o in raw_orgs.values() if o["identifier"] in org_ids]
    problems += [f"org {i} not returned" for i in sorted(org_ids - raw_orgs.keys())]
    problems += cross_check(meps, orgs, current)

    write_records(SOURCE_ID, "meps", meps, key=lambda m: int(m.id))
    write_records(SOURCE_ID, "orgs", orgs, key=lambda o: (o.kind, int(o.id)))
    kinds = {k: sum(o.kind == k for o in orgs) for k in ("group", "party", "committee")}
    per_term = {t: sum(t in m.terms for m in meps) for t in TERMS}
    note = f"MEPs per term {per_term}, active {sum(m.active for m in meps)}; orgs {kinds}" + (
        f"; problems: {'; '.join(problems[:20])}" if problems else ""
    )
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if problems else "ok",
        fetched_at=retrieved,
        attempted_at=attempted,
        records={"meps": len(meps), "orgs": len(orgs)},
        note=note,
    )
