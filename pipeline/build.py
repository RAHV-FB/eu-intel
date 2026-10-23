"""Offline build: data/snapshot + data/curated -> public/data (the contract in src/types/data.ts).

    python -m pipeline build

Principles
- Only identifiers link records (procedure reference, CELEX, EP vote id). Never titles.
  An ambiguous link (e.g. a vote naming two procedures) is shown on each dossier but no single
  `dossier_id` is asserted.
- Missing sources produce empty sections; meta.json says what is missing and why.
- Output is compact JSON with stable ordering, so identical inputs give identical files
  (except meta.built_at). Set EU_INTEL_TODAY=YYYY-MM-DD to pin "today" (tests).
- EU_INTEL_RECORD_ACTIVITY=1 compares the snapshot with data/state/digest.json and appends
  verified changes to data/state/activity.json (see pipeline/analysis/activity.py).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from pipeline.analysis.transposition import article_label, articles_text, general_deadline
from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.models import entities
from pipeline.models.countries import MEMBER_STATES
from pipeline.models.entities import (
    CouncilVote,
    CountryIndicator,
    EpBallots,
    EpVote,
    InfringementCase,
    LegalAct,
    Mep,
    NationalMeasure,
    Organization,
    Procedure,
    SourceStatus,
    TrainFile,
)
from pipeline.snapshot import CURATED, ROOT, SNAPSHOT, now_iso, read_manifest

log = logging.getLogger("pipeline.build")

OUT = ROOT / "public" / "data"
STATE = ROOT / "data" / "state"
DEFAULT_SITE_URL = "https://rahv-fb.github.io/eu-intel/"

# ------------------------------------------------------------------------------------------ sources
# Reuse / licence statements shown on the About page. Keep them factual and short.
# Verified 2026-10-22: the EP legal notice (https://www.europarl.europa.eu/legal-notice/en/) authorises
# reuse provided the source is acknowledged; data.europa.eu lists the EP open datasets under the
# "European Commission reuse notice". (No CC BY claim is made because none was confirmed.)
EP_LICENCE = (
    "© European Union – Source: European Parliament. Reuse is authorised provided the source is "
    "acknowledged (European Parliament legal notice)."
)
SOURCES: dict[str, dict[str, str]] = {
    "ep_people": {
        "name": "European Parliament – MEPs, political groups and national parties",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": EP_LICENCE,
    },
    "ep_procedures": {
        "name": "European Parliament – legislative procedures (Legislative Observatory data)",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": EP_LICENCE,
    },
    "ep_votes": {
        "name": "European Parliament – plenary votes and roll-call results",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": EP_LICENCE,
    },
    "eurlex": {
        "name": "EUR-Lex / Publications Office (Cellar) – adopted legal acts and their dates",
        "institution": "EUR-Lex",
        "url": "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html",
        "licence": "© European Union, https://eur-lex.europa.eu. Reuse authorised under Commission "
        "Decision 2011/833/EU, with acknowledgement of the source.",
    },
    "council": {
        "name": "Council of the European Union – voting results (official voting-result documents)",
        "institution": "Council",
        "url": "https://www.consilium.europa.eu/en/general-secretariat/corporate-policies/transparency/open-data/voting-results/",
        "licence": "© European Union, Council of the European Union. Reuse of Council documents is authorised "
        "under Council Decision (EU) 2017/1842, with acknowledgement of the source.",
    },
    "implementation": {
        "name": "European Commission / EUR-Lex – national transposition measures, infringements and indicators",
        "institution": "Commission",
        "url": "https://commission.europa.eu/law/application-eu-law_en",
        "licence": "© European Union. Reuse authorised under Commission Decision 2011/833/EU, with "
        "acknowledgement of the source.",
    },
    "train": {
        "name": "European Parliament – Legislative Train Schedule",
        "institution": "LegislativeTrain",
        "url": "https://www.europarl.europa.eu/legislative-train/",
        "licence": "© European Union, source: European Parliament. Reuse authorised with acknowledgement "
        "of the source.",
    },
}

TYPE_LABELS: dict[str, str] = {
    "COD": "Ordinary legislative procedure",
    "CNS": "Consultation procedure",
    "APP": "Consent procedure",
    "NLE": "Non-legislative act",
    "BUD": "Budgetary procedure",
    "BUI": "Budget (other)",
    "DEC": "Budget discharge",
    "DEA": "Delegated act",
    "RPS": "Implementing measure (regulatory procedure with scrutiny)",
    "INI": "Own-initiative report",
    "INL": "Request for a legislative proposal",
    "RSP": "Resolution on a topical subject",
    "RSO": "Parliament's internal organisation",
    "REG": "Parliament's Rules of Procedure",
    "IMM": "Parliamentary immunity",
    "ACI": "Interinstitutional agreement",
    "INS": "Institutional procedure",
    "COS": "Strategy paper",
    "DCE": "Written declaration",
    "AVC": "Assent procedure (before 2009)",
    "SYN": "Cooperation procedure (before 1999)",
    "GBD": "Budget guidelines",
}
LEGISLATIVE_TYPES = {"COD", "CNS", "APP", "NLE", "SYN", "AVC"}

VOTE_KIND_LABELS: dict[str, str] = {
    "final": "Final vote on the text",
    "amendment": "Amendment",
    "split_or_separate": "Split or separate vote on part of the text",
    "resolution": "Vote on a resolution",
    "motion": "Vote on a motion",
    "procedural": "Procedural vote",
    "mandate": "Vote on Parliament's negotiating mandate",
    "other": "Other vote",
}
VOTE_KIND_PHRASE: dict[str, str] = {
    "final": "final vote on the text",
    "amendment": "vote on an amendment",
    "split_or_separate": "vote on part of the text",
    "resolution": "vote on the resolution",
    "motion": "vote on a motion",
    "procedural": "procedural vote",
    "mandate": "vote on Parliament's negotiating mandate (text referred back to committee for negotiations)",
    "other": "vote",
}

KEY_KINDS = {
    "proposal",
    "committee_report",
    "ep_position",
    "provisional_agreement",
    "council_position",
    "council_adoption",
    "signature",
    "publication",
    "entry_into_force",
    "application",
    "transposition_deadline",
    "transposition_application",
    "withdrawal",
    "rejection",
    "lapsed",
}
VOTE_EVENT_KINDS = {"ep_position", "plenary_vote", "rejection"}
ACTIVE_STAGES = {"proposed", "parliament_position", "negotiations", "provisional_agreement"}
ADOPTED_STAGES = {"adopted", "published", "in_force", "no_longer_in_force"}

RULE_LABELS = {
    "votes_cast": "Majority of votes cast (abstentions are not counted)",
    "component_members": "Majority of Parliament's component Members (abstentions and absences count like votes against)",
    "two_thirds_cast": "Two-thirds of the votes cast, representing a majority of component Members",
}
PAST_TITLES = {
    "entry_into_force": "Entered into force",
    "application": "Further provisions started to apply (date recorded by EUR-Lex)",
    "transposition_deadline": "Deadline for Member States to transpose the directive (passed)",
}
INDEX_OFFICIAL_TITLE_MAX = 140  # dossiers/index.json only; full titles are in dossiers/<id>.json
INDEX_TITLE_MAX = 180

STAGE_LABELS: dict[str, str] = {
    "proposed": "Proposed",
    "parliament_position": "Approved by Parliament",
    "negotiations": "In negotiations",
    "provisional_agreement": "Provisional agreement reached",
    "adopted": "Adopted",
    "published": "Published",
    "in_force": "In force",
    "no_longer_in_force": "No longer in force",
    "withdrawn": "Withdrawn",
    "rejected": "Rejected",
    "lapsed": "Lapsed",
    "unknown": "Status unknown",
}

DEMONYMS: dict[str, list[str]] = {
    "AT": ["Austrian"], "BE": ["Belgian"], "BG": ["Bulgarian"], "HR": ["Croatian", "Croat"],
    "CY": ["Cypriot"], "CZ": ["Czech", "Czech Republic"], "DK": ["Danish", "Dane"], "EE": ["Estonian"],
    "FI": ["Finnish", "Finn"], "FR": ["French"], "DE": ["German", "Deutschland"], "GR": ["Greek", "Hellenic"],
    "HU": ["Hungarian"], "IE": ["Irish"], "IT": ["Italian"], "LV": ["Latvian"], "LT": ["Lithuanian"],
    "LU": ["Luxembourgish", "Luxembourger"], "MT": ["Maltese"], "NL": ["Dutch", "Holland"],
    "PL": ["Polish", "Pole"], "PT": ["Portuguese"], "RO": ["Romanian"], "SK": ["Slovak", "Slovakian"],
    "SI": ["Slovenian", "Slovene"], "ES": ["Spanish", "Spaniard", "España"], "SE": ["Swedish", "Swede"],
}  # fmt: skip

GROUP_ALIASES: dict[str, list[str]] = {
    "epp": ["EPP", "European People's Party", "PPE", "Christian Democrats"],
    "s-d": ["S&D", "S and D", "Socialists and Democrats", "Socialists", "S&Ds"],
    "renew": ["Renew", "Renew Europe", "liberals"],
    "greens-efa": ["Greens/EFA", "Greens", "Verts/ALE", "European Free Alliance"],
    "ecr": ["ECR", "European Conservatives and Reformists", "Conservatives"],
    "the-left": ["The Left", "Left", "GUE/NGL"],
    "id": ["ID", "Identity and Democracy"],
    "pfe": ["PfE", "Patriots", "Patriots for Europe"],
    "esn": ["ESN", "Europe of Sovereign Nations"],
    "ni": ["NI", "Non-attached", "Non-inscrits", "Independents"],
}

# Guide pages (How the EU Works) for search. Anchors must exist on /how-the-eu-works.
GUIDE_PAGES: list[dict[str, str]] = [
    {"id": "olp", "t": "How an EU law is made (ordinary legislative procedure)",
     "a": "ordinary legislative procedure | codecision | co-decision | legislative procedure | how laws are made "
          "| trilogue | trilogues | interinstitutional negotiations | provisional agreement | first reading",
     "u": "/how-the-eu-works#olp"},
    {"id": "council-voting", "t": "How the Council votes: qualified majority and unanimity",
     "a": "qualified majority | QMV | unanimity | veto | blocking minority | council vote | council voting",
     "u": "/how-the-eu-works#council-voting"},
    {"id": "parliament-voting", "t": "How Parliament votes: roll-call votes and majorities",
     "a": "roll-call vote | roll call | plenary vote | majority of votes cast | absolute majority | abstention",
     "u": "/how-the-eu-works#parliament-voting"},
    {"id": "implementation", "t": "Transposition: how directives become national law",
     "a": "transposition | transpose | national measures | implementation | NIM | transposition deadline",
     "u": "/how-the-eu-works#implementation"},
    {"id": "infringements", "t": "Infringement procedures",
     "a": "infringement | infringements | letter of formal notice | reasoned opinion | court of justice | CJEU",
     "u": "/how-the-eu-works#infringements"},
    {"id": "instruments", "t": "Regulations, directives and decisions",
     "a": "regulation | directive | decision | entry into force | application date | legal act | instrument",
     "u": "/how-the-eu-works#instruments"},
    {"id": "commission", "t": "The European Commission",
     "a": "European Commission | commission | commissioner | right of initiative | proposal",
     "u": "/how-the-eu-works#commission"},
    {"id": "parliament", "t": "The European Parliament",
     "a": "European Parliament | parliament | MEP | MEPs | political group | political groups | plenary",
     "u": "/how-the-eu-works#parliament"},
    {"id": "council", "t": "The Council of the European Union",
     "a": "Council of the EU | Council of the European Union | council of ministers | ministers | presidency",
     "u": "/how-the-eu-works#council"},
    {"id": "european-council", "t": "The European Council (heads of state or government)",
     "a": "European Council | summit | heads of state | heads of government | EUCO",
     "u": "/how-the-eu-works#european-council"},
]  # fmt: skip

# ------------------------------------------------------------------------------------------- helpers


def _today() -> str:
    return os.environ.get("EU_INTEL_TODAY") or date.today().isoformat()


def _add_days(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _as_dict(obj: Any) -> Any:
    """Normalize analysis-module results (pydantic model, dataclass, dict) to JSON-ready dicts."""
    if obj is None:
        return None
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _as_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_dict(v) for v in obj]
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float, bool)):  # Enum
        return obj.value
    return obj


def _src(ref: Any) -> dict | None:
    return ref.model_dump(mode="json") if ref is not None else None


# Same political group under an earlier official short label (EP corporate bodies are re-created at
# renamings): GUE/NGL was renamed "The Left in the European Parliament – GUE/NGL" in December 2020.
GROUP_SLUG_MERGE = {"gue-ngl": "the-left"}


def group_slug(code: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-") or "unknown"
    return GROUP_SLUG_MERGE.get(slug, slug)


REF_RE = re.compile(r"^(\d{4})/(\d{4})\(([A-Z]{3})\)$")
_SHORT_NAME = re.compile(
    r"\(([A-Z][^()]{2,70}?(?:Act|Regulation|Directive|Package|Code|Mechanism|Instrument|Fund|Programme))\)"
)


def short_names(title: str) -> list[str]:
    """Official short names given in parentheses in a title, e.g. '(Artificial Intelligence Act)'.

    A parenthetical right after another act's number ("Regulation (EU) 2016/679 (General Data
    Protection Regulation)") names that other act, so it is skipped.
    """
    out = []
    for m in _SHORT_NAME.finditer(title or ""):
        before = title[: m.start()].rstrip()
        if re.search(r"\d{1,4}/\d{1,4}(?:/[A-Z]+)*$", before):
            continue
        out.append(m.group(1).strip())
    return out


def provision_label(code: str) -> str:
    """Cellar location code to a readable provision: "A05P1" -> "Article 5(1)", "A01PT3" -> "Article 1, point 3"."""
    m = re.fullmatch(r"A0*(\d+)([A-Z]?)(?:P0*(\d+))?(?:PT0*(\d+))?", code)
    if not m:
        return code
    art, letter, par, point = m.groups()
    out = f"Article {art}{letter.lower()}" + (f"({par})" if par else "")
    return out + (f", point {point}" if point else "")


def ruling_summary(r) -> dict:
    """A court ruling on an act, described without overstating its scope (the judgment is linked)."""
    kind = "Action for annulment" if r.effect == "annulment" else "Preliminary ruling on validity"
    provs = [provision_label(c) for c in r.provisions]
    # EUR-Lex records which provisions are affected but not whether in whole or in part, so say both.
    if r.effect == "annulment":
        outcome = f"annulled all or part of {', '.join(provs)}" if provs else "annulled the act or part of it"
    else:
        outcome = (
            f"declared all or part of {', '.join(provs)} invalid" if provs else "declared the act invalid"
        )
    return {
        "case_number": r.case_number, "celex": r.celex, "date": r.date, "ecli": r.ecli,
        "effect": r.effect, "kind_label": kind, "provisions": provs, "url": r.url,
        "summary": f"The Court of Justice {outcome}. The judgment sets out the exact scope and any temporal effects.",
    }  # fmt: skip


def norm_ref(ref: str) -> str:
    return re.sub(r"\s+", "", ref or "").upper()


def ref_number(ref: str) -> str | None:
    m = re.match(r"^(\d{4})/(\d{4})", norm_ref(ref))
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _lazy(module: str, attr: str) -> Any:
    try:
        mod = importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 - optional analysis module (may be absent or broken)
        log.warning("optional module %s unavailable: %r", module, e)
        return None
    return getattr(mod, attr, None)


def _load[M: BaseModel](
    source: str, name: str, model: type[M], issues: list[str], root: Path = SNAPSHOT
) -> list[M]:
    path = root / source / f"{name}.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        issues.append(f"{source}/{name}.json unreadable: {e}")
        return []
    out: list[M] = []
    bad = 0
    for x in raw:
        try:
            out.append(model.model_validate(x))
        except ValidationError:
            bad += 1
    if bad:
        issues.append(f"{source}/{name}.json: {bad} invalid records skipped")
        log.warning("%s/%s: %d invalid records skipped", source, name, bad)
    return out


def _load_yaml(name: str, curated: Path = CURATED) -> Any:
    path = curated / name
    if not path.exists():
        return None
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - curated data must never break the build
        log.warning("curated %s unreadable: %r", name, e)
        return None


def _write(rel: str, data: Any, root: Path) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    cut = text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:(")
    return cut + "…"


_OPTIONAL_SUMMARY = ("short", "started", "last_event", "adopted", "next_date", "instrument")


def _index_entry(d: dict) -> dict:
    """Compact DossierSummary for dossiers/index.json: long official titles shortened (full text in
    dossiers/<id>.json), optional fields omitted when empty."""
    out = {k: v for k, v in d.items() if not (k in _OPTIONAL_SUMMARY and v is None)}
    out["official_title"] = _truncate(d["official_title"], INDEX_OFFICIAL_TITLE_MAX)
    out["title"] = _truncate(d["title"], INDEX_TITLE_MAX)
    if out.get("short"):
        out["short"] = _truncate(out["short"], 240)
    return out


STALL_KEYS = (
    "days_since_last_event", "text", "last_event_date", "official_label", "official_source_url",
    "official_label_date", "official_text",
)  # fmt: skip
UNKNOWN_STEPS = {"Not available.", "Not determined from the recorded events."}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]  # fmt: skip


def _long_date(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{dd} {_MONTHS[m - 1]} {y}"


def _dedupe_sources(sources: list[dict | None]) -> list[dict]:
    """Keep the first SourceRef per (institution, url, identifier)."""
    out, seen = [], set()
    for x in sources:
        if not x:
            continue
        k = (x.get("institution"), x.get("url"), x.get("identifier"))
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _vote_index_entry(v: dict) -> dict:
    """Compact EpVoteSummary for votes/index.json (full record in votes/<id>.json)."""
    out = {k: x for k, x in v.items() if not (k in ("dossier_id", "dossier_ref", "margin") and x is None)}
    src = v.get("source") or {}
    out["source"] = {k: src[k] for k in ("institution", "url") if src.get(k)}
    return out


def _valid_on(start: str | None, end: str | None, d: str) -> bool:
    return (start is None or start <= d) and (end is None or d <= end)


def council_assessment(a: dict | None) -> dict | None:
    """pipeline.analysis.council_qmv.CouncilAssessment -> CouncilAssessment in src/types/data.ts."""
    if not a:
        return None
    notes = a.get("notes") or ([a["note"]] if a.get("note") else [])
    return {
        "rule": a.get("rule"),
        "states_for": a.get("states_for"),
        "states_required": a.get("states_required"),
        "population_for_pct": a.get("population_for_pct"),
        "population_required_pct": a.get("population_required_pct"),
        "adopted_by_rule": a.get("adopted_by_rule"),
        "blocking_minority_existed": a.get("blocking_minority_formed", a.get("blocking_minority_existed")),
        "single_state_veto_possible": bool(a.get("single_state_veto_possible"))
        and a.get("rule") == "unanimity",
        "note": " ".join(str(n) for n in notes),
        "legal_basis": a.get("legal_basis"),
        "states_against": a.get("states_against"),
        "states_abstain": a.get("states_abstain"),
        "states_not_participating": a.get("states_not_participating"),
    }


# ------------------------------------------------------------------------------------------- titles
_BOILER = re.compile(
    r"^(?:(?:amended\s+)?proposal\s+for\s+an?\s+|draft\s+)?"
    r"(?:(?:council|commission)\s+)?(?:implementing\s+|delegated\s+)?"
    r"(regulation|directive|decision|recommendation)"
    r"(?:\s+\((?:EU|EC|EEC|Euratom)(?:,\s*Euratom)?\))?"
    r"(?:\s+No)?(?:\s+\d{1,4}/\d{1,4}(?:/(?:EU|EC|EEC|Euratom|CFSP|JHA))*)?"
    r"(?:\s+of\s+the\s+european\s+parliament\s+and\s+of\s+the\s+council|\s+of\s+the\s+council)?"
    r"(?:\s+of\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4})?"
    r"\s*[,:]?\s*",
    re.IGNORECASE,
)
_TAIL = re.compile(
    r"\s*(?:\((?:Text with EEA relevance|codification|recast)\.?\)|Text with EEA relevance\.?)\s*$",
    re.IGNORECASE,
)
_LEAD = re.compile(r"^(?:on|concerning|establishing|laying\s+down|setting\s+out|as\s+regards)\s+(?:the\s+)?",
                   re.IGNORECASE)  # fmt: skip


def instrument_from_title(title: str) -> str | None:
    m = _BOILER.match(title.strip())
    return m.group(1).lower() if m and m.group(1) else None


def clean_title(title: str) -> str:
    """Strip legal boilerplate when the remainder is still a meaningful noun phrase."""
    t = re.sub(r"\s+", " ", (title or "").strip()).rstrip(".")
    for _ in range(2):
        t = _TAIL.sub("", t)
    m = _BOILER.match(t)
    if m and m.end() > 0:
        rest = t[m.end() :]
        rest2 = _LEAD.sub("", rest)
        # keep verbs such as "amending ..." (the instrument amended is the meaningful part)
        if len(rest2.split()) >= 2 and not re.match(r"^(?:\(|\d)", rest2):
            t = rest2
    t = t.strip().rstrip(",;:").strip()
    return t[:1].upper() + t[1:] if t else t


# ------------------------------------------------------------------------------------------- curated
def load_curated(curated: Path = CURATED) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    """Returns (featured by normalized reference/id, topics by slug, alias rules)."""
    featured_raw = _load_yaml("featured.yaml", curated) or []
    if isinstance(featured_raw, dict):
        featured_raw = (
            featured_raw.get("dossiers") or featured_raw.get("featured") or list(featured_raw.values())
        )
    featured: dict[str, dict] = {}
    for e in featured_raw if isinstance(featured_raw, list) else []:
        if not isinstance(e, dict):
            continue
        key = norm_ref(str(e.get("reference") or "")) or str(e.get("id") or "")
        if key:
            featured[key] = e
    topics_raw = _load_yaml("topics.yaml", curated) or {}
    topics: dict[str, dict] = {}
    if isinstance(topics_raw, dict):
        topics_raw = topics_raw.get("topics", topics_raw)
    if isinstance(topics_raw, dict):
        for slug, t in topics_raw.items():
            if isinstance(t, dict):
                topics[str(slug)] = t
    elif isinstance(topics_raw, list):
        for t in topics_raw:
            if isinstance(t, dict) and t.get("slug"):
                topics[str(t["slug"])] = t
    aliases_raw = _load_yaml("aliases.yaml", curated) or []
    if isinstance(aliases_raw, dict):
        aliases_raw = aliases_raw.get("aliases", [])
    aliases = [a for a in aliases_raw if isinstance(a, dict)] if isinstance(aliases_raw, list) else []
    return featured, topics, aliases


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        return [str(v)]
    return [str(x) for x in v if x is not None]


# ------------------------------------------------------------------------------------------- context
class Snapshot:
    def __init__(self, root: Path = SNAPSHOT) -> None:
        self.root = root
        self.issues: list[str] = []
        i = self.issues
        self.manifest: dict[str, SourceStatus] = self._manifest()
        self.meps = _load("ep_people", "meps", Mep, i, root)
        self.orgs = _load("ep_people", "orgs", Organization, i, root)
        self.procedures = _load("ep_procedures", "procedures", Procedure, i, root)
        self.votes = _load("ep_votes", "votes", EpVote, i, root)
        self.ballots = _load("ep_votes", "ballots", EpBallots, i, root)
        self.acts = _load("eurlex", "acts", LegalAct, i, root)
        self.council = _load("council", "votes", CouncilVote, i, root)
        self.measures = _load("implementation", "measures", NationalMeasure, i, root)
        self.infringements = _load("implementation", "infringements", InfringementCase, i, root)
        self.indicators = _load("implementation", "indicators", CountryIndicator, i, root)
        cov_model = getattr(entities, "ImplementationCoverage", None)
        self.coverage = _load("implementation", "coverage", cov_model, i, root) if cov_model else []
        self.has_coverage_file = self.file_exists("implementation", "coverage")
        self.train = _load("train", "files", TrainFile, i, root)

    def _manifest(self) -> dict[str, SourceStatus]:
        if self.root == SNAPSHOT:
            return read_manifest()
        path = self.root / "_manifest.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: SourceStatus.model_validate(v) for k, v in raw.items()}

    def file_exists(self, source: str, name: str) -> bool:
        return (self.root / source / f"{name}.json").exists()


class Builder:
    def __init__(
        self, snap: Snapshot, today: str | None = None, curated: Path = CURATED, state: Path = STATE
    ) -> None:
        self.s = snap
        self.today = today or _today()
        self.state_dir = state
        self.featured_cur, self.topics_cur, self.alias_rules = load_curated(curated)
        self.files: dict[str, Any] = {}
        self._index()

    # ---------------------------------------------------------------- indexes
    def _index(self) -> None:
        s = self.s
        self.org = {o.id: o for o in s.orgs}
        self.mep = {m.id: m for m in s.meps}
        self.proc_by_ref: dict[str, Procedure] = {}
        self.proc_by_num: dict[str, list[Procedure]] = defaultdict(list)
        self.act = {a.celex: a for a in s.acts}
        self.stub_ids: set[str] = set()
        self.procedures: list[Procedure] = list(s.procedures)
        self._register(self.procedures)
        stubs = self._stub_procedures()
        self.stub_ids = {p.id for p in stubs}
        self.procedures += stubs
        self._register(stubs)
        # group code -> slug, merged across terms
        self.group_orgs: dict[str, list[Organization]] = defaultdict(list)
        for o in s.orgs:
            if o.kind == "group":
                self.group_orgs[group_slug(o.code or o.label)].append(o)
        self.org_slug = {o.id: slug for slug, os_ in self.group_orgs.items() for o in os_}
        # per-MEP membership intervals
        self.mep_groups: dict[str, list[tuple[str | None, str | None, str]]] = {}
        self.mep_parties: dict[str, list[tuple[str | None, str | None, str]]] = {}
        for m in s.meps:
            g = [(x.start, x.end, x.org_id) for x in m.memberships if x.kind == "group"]
            p = [(x.start, x.end, x.org_id) for x in m.memberships if x.kind == "party"]
            self.mep_groups[m.id] = sorted(g, key=lambda t: (t[0] or "", t[1] or "9999"))
            self.mep_parties[m.id] = sorted(p, key=lambda t: (t[0] or "", t[1] or "9999"))
        self.ballots = {b.vote_id: b for b in s.ballots}
        self.train_by_ref: dict[str, list[TrainFile]] = defaultdict(list)
        for t in s.train:
            for r in t.procedure_refs:
                self.train_by_ref[norm_ref(r)].append(t)
        # measures coverage: directives for which the implementation source returned any data
        self.measures_by: dict[tuple[str, str], list[NationalMeasure]] = defaultdict(list)
        for nm in s.measures:
            self.measures_by[(nm.directive_celex, nm.country)].append(nm)
        # directives whose national measures were queried: coverage.json when published by the source;
        # otherwise only directives with at least one measure are known to have been queried
        if s.has_coverage_file:
            self.measure_celexes = {c.celex for c in s.coverage}
        else:
            self.measure_celexes = {nm.directive_celex for nm in s.measures}
        self.infr_by_celex: dict[str, list[InfringementCase]] = defaultdict(list)
        self.infr_by_country: dict[str, list[InfringementCase]] = defaultdict(list)
        for ic in sorted(s.infringements, key=lambda c: (c.latest_decision_date or "", c.id), reverse=True):
            for c in sorted({*(getattr(ic, "legal_basis", None) or []), *([ic.celex] if ic.celex else [])}):
                self.infr_by_celex[c].append(ic)
            self.infr_by_country[ic.country].append(ic)
        # Member States recorded as not participating in the Council's latest recorded vote on a procedure
        # (Treaty opt-outs, e.g. Denmark and Ireland in justice and home affairs) are not bound by the act,
        # so "no measures found" would be misleading for them.
        latest_cv: dict[str, CouncilVote] = {}
        for cv in sorted(s.council, key=lambda v: (v.date, v.id)):
            if cv.positions:
                for r in cv.procedure_refs:
                    latest_cv[norm_ref(r)] = cv
        self.not_participating_by_ref: dict[str, tuple[set[str], CouncilVote]] = {
            ref: ({c for c, pos in cv.positions.items() if pos == "not_participating"}, cv)
            for ref, cv in latest_cv.items()
        }
        self.act_refs: dict[str, list[str]] = {
            a.celex: [norm_ref(r) for r in a.procedure_refs] for a in s.acts
        }

    def not_participating(self, celex: str, country: str) -> CouncilVote | None:
        """The Council vote recording that `country` did not take part in adopting this act, if any."""
        for ref in self.act_refs.get(celex, []):
            countries, cv = self.not_participating_by_ref.get(ref, (set(), None))
            if country in countries:
                return cv
        return None

    def _register(self, procs: list[Procedure]) -> None:
        for p in sorted(procs, key=lambda p: p.id):
            self.proc_by_ref[norm_ref(p.reference)] = p
            n = ref_number(p.reference)
            if n:
                self.proc_by_num[n].append(p)

    def _stub_procedures(self) -> list[Procedure]:
        """Procedures named by EUR-Lex acts but absent from the EP procedure snapshot.

        Built only from the act record (official reference, title, dates); no EP events are invented.
        """
        refs: dict[str, list[LegalAct]] = defaultdict(list)
        for a in self.s.acts:
            for r in a.procedure_refs:
                if REF_RE.match(norm_ref(r)) and self.resolve_ref(r) is None:
                    refs[norm_ref(r)].append(a)
        out = []
        for ref, acts in sorted(refs.items()):
            m = REF_RE.match(ref)
            assert m
            pid = f"{m.group(1)}-{m.group(2)}"
            if pid in {p.id for p in out}:
                continue
            main = sorted(acts, key=lambda a: (a.date_document or "", a.celex))[0]
            out.append(Procedure(
                id=pid, reference=ref, type=m.group(3), title=main.title,
                celex_refs=sorted({a.celex for a in acts}),
                oeil_url=f"https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={ref}",
                source=main.source,
            ))  # fmt: skip
        return out

    def resolve_ref(self, ref: str) -> Procedure | None:
        p = self.proc_by_ref.get(norm_ref(ref))
        if p:
            return p
        n = ref_number(ref)
        cands = self.proc_by_num.get(n or "", [])
        return cands[0] if len(cands) == 1 else None

    def group_at(self, mep_id: str, d: str) -> str | None:
        for start, end, org_id in self.mep_groups.get(mep_id, []):
            if _valid_on(start, end, d):
                return org_id
        return None

    def party_at(self, mep_id: str, d: str) -> str | None:
        for start, end, org_id in self.mep_parties.get(mep_id, []):
            if _valid_on(start, end, d):
                return org_id
        return None

    def current_or_last(self, spans: list[tuple[str | None, str | None, str]]) -> str | None:
        if not spans:
            return None
        ongoing = [s for s in spans if s[1] is None]
        if ongoing:
            return max(ongoing, key=lambda t: t[0] or "")[2]
        return max(spans, key=lambda t: t[1] or "")[2]

    def group_code(self, slug: str | None) -> str | None:
        if not slug or slug not in self.group_orgs:
            return None
        o = max(self.group_orgs[slug], key=lambda o: o.start or "")
        return o.code or o.label

    # ---------------------------------------------------------------- run
    def run(self) -> dict[str, Any]:
        self.build_dossier_links()
        self.build_votes()
        self.build_council()
        self.build_dossiers()
        self.build_people()
        self.build_countries()
        self.build_topics()
        self.build_activity()
        self.build_home()
        self.build_search()
        self.build_meta()
        return self.files

    # ---------------------------------------------------------------- linking
    def build_dossier_links(self) -> None:
        """Procedures, curated entries, acts, votes, council votes, train files -> dossier ids."""
        self.dossier_ids: list[str] = sorted(p.id for p in self.procedures)
        self.proc = {p.id: p for p in self.procedures}
        self.acts_of: dict[str, list[LegalAct]] = defaultdict(list)
        act_dossiers: dict[str, set[str]] = defaultdict(set)
        for a in self.s.acts:
            for r in a.procedure_refs:
                p = self.resolve_ref(r)
                if p:
                    act_dossiers[a.celex].add(p.id)
        claimed_by: dict[str, set[str]] = defaultdict(set)
        for p in self.procedures:
            for c in p.celex_refs:
                if c in self.act:
                    act_dossiers[c].add(p.id)
                    claimed_by[c].add(p.id)
        # Split procedures (e.g. 2016/0224A and 2016/0224B): EUR-Lex links their acts to the parent reference,
        # while the EP records each adoption under the split procedure. Keep an act on the split procedure that
        # claims it and drop the parent link, so that one law has one page.
        pids = {p.id for p in self.procedures}
        self.split_children: dict[str, list[str]] = defaultdict(list)
        for pid in sorted(pids):
            m = re.fullmatch(r"(\d{4}-\d{4})([A-Z])", pid)
            if m and m.group(1) in pids:
                self.split_children[m.group(1)].append(pid)
        for celex, ds in act_dossiers.items():
            for parent, children in self.split_children.items():
                if parent in ds and any(c in claimed_by[celex] for c in children):
                    ds.discard(parent)
        for celex, ds in sorted(act_dossiers.items()):
            for d in sorted(ds):
                self.acts_of[d].append(self.act[celex])
        self.act_dossiers = act_dossiers
        for d in self.acts_of:
            self.acts_of[d].sort(key=lambda a: (a.date_document or a.date_publication or "", a.celex))
        # curated entries (by procedure reference, then id)
        self.curated_of: dict[str, dict] = {}
        for key, e in self.featured_cur.items():
            p = self.proc_by_ref.get(key) or self.proc.get(str(e.get("id") or ""))
            if p is None and ref_number(key):
                p = self.resolve_ref(key)
            if p is not None:
                self.curated_of[p.id] = e
            else:
                log.info("curated entry %s: procedure not in snapshot", key)
        self.train_of: dict[str, list[TrainFile]] = {}
        for pid, p in self.proc.items():
            t = self.train_by_ref.get(norm_ref(p.reference))
            if t:
                self.train_of[pid] = sorted(t, key=lambda x: x.url)

    def vote_dossiers(self, v: EpVote) -> list[str]:
        out = {p.id for r in v.procedure_refs if (p := self.resolve_ref(r))}
        return sorted(out)

    # ---------------------------------------------------------------- titles/topics
    def dossier_title(self, p: Procedure) -> str:
        cur = self.curated_of.get(p.id)
        if cur and cur.get("short_title"):
            return str(cur["short_title"])
        names = short_names(p.title)
        return names[0] if names else clean_title(p.title)

    def topics_for(self, p: Procedure) -> list[str]:
        out: set[str] = set()
        codes = [s.code for s in p.subjects if s.scheme == "ep"]
        for slug, t in self.topics_cur.items():
            for pref in _as_list(t.get("ep_subjects")):
                pref = pref.strip().rstrip(".")
                if any(c == pref or c.startswith(pref + ".") for c in codes):
                    out.add(slug)
                    break
        cur = self.curated_of.get(p.id)
        if cur:
            out.update(t for t in _as_list(cur.get("topics")) if t in self.topics_cur or not self.topics_cur)
        return sorted(out)

    # ---------------------------------------------------------------- EP votes
    def build_votes(self) -> None:
        s = self.s
        self.vote_dossier_map: dict[str, list[str]] = {}
        self.votes_of: dict[str, list[EpVote]] = defaultdict(list)
        for v in s.votes:
            ds = self.vote_dossiers(v)
            self.vote_dossier_map[v.id] = ds
            for d in ds:
                self.votes_of[d].append(v)
        idx = [
            v
            for v in s.votes
            if (v.has_ballots and v.kind in ("final", "mandate", "resolution", "motion"))
            or (v.kind in ("final", "mandate") and self.vote_dossier_map.get(v.id))
        ]
        idx.sort(key=lambda v: (v.date, v.id), reverse=True)
        self.indexed_votes = idx
        self.indexed_vote_ids = {v.id for v in idx}
        self.component_cache: dict[str, int | None] = {}
        margin_fn = _lazy("pipeline.analysis.ep_margin", "margin")
        self.vote_summary: dict[str, dict] = {}
        self.group_votes: dict[str, list[dict]] = defaultdict(list)
        self.mep_votes: dict[str, list[dict]] = defaultdict(list)
        for v in idx:
            summ = self.ep_vote_summary(v, margin_fn)
            self.vote_summary[v.id] = summ
        for v in idx:
            det = self.ep_vote_detail(v)
            self.files[f"votes/{v.id}.json"] = det
        self.files["votes/index.json"] = [_vote_index_entry(self.vote_summary[v.id]) for v in idx]

    def component_members(self, d: str) -> int | None:
        """Number of component Members for majority rules: the statutory number of seats documented in
        pipeline.analysis.ep_margin (None when not covered; margins needing it are then not computed)."""
        if d not in self.component_cache:
            seats = _lazy("pipeline.analysis.ep_margin", "statutory_seats")
            self.component_cache[d] = seats(d) if seats else None
        return self.component_cache[d]

    def ep_vote_summary(self, v: EpVote, margin_fn: Any) -> dict:
        ds = self.vote_dossier_map.get(v.id, [])
        did = ds[0] if len(ds) == 1 else None
        p = self.proc.get(did) if did else None
        b = self.ballots.get(v.id) if v.has_ballots else None
        n_for, n_against, n_abs = v.n_for, v.n_against, v.n_abstain
        if n_for is None and b is not None:
            n_for, n_against, n_abs = len(b.favor), len(b.against), len(b.abstain)
        margin = None
        # a margin is shown only when the official outcome is known and the majority rule is established,
        # so its label can never contradict the outcome
        if margin_fn is not None and v.outcome in ("adopted", "rejected") and v.majority_rule != "unknown":
            try:
                m = _as_dict(margin_fn(v, self.component_members(v.date)))
                passed = isinstance(m, dict) and isinstance(m.get("distance"), int) and m["distance"] >= 0
                if (
                    m
                    and m.get("rule") in RULE_LABELS
                    and isinstance(m.get("relative"), (int, float))
                    and passed == (v.outcome == "adopted")
                ):
                    margin = {
                        "rule": m["rule"],
                        "rule_label": m.get("rule_label") or RULE_LABELS[m["rule"]],
                        "threshold": m["threshold"],
                        "distance": m["distance"],
                        "relative": m["relative"],
                        "label": m["label"],
                    }
            except Exception as e:  # noqa: BLE001
                log.debug("margin failed for %s: %r", v.id, e)
        if p is not None:
            display = f"{_truncate(self.dossier_title(p), 120)} — {VOTE_KIND_PHRASE.get(v.kind, 'vote')}"
            if v.kind in ("amendment", "split_or_separate") and v.reference_text:
                display += f" ({v.reference_text})"
        else:
            display = v.title
        return {
            "id": v.id,
            "date": v.date,
            "title": v.title,
            "display_title": display,
            "kind": v.kind,
            "kind_label": VOTE_KIND_LABELS.get(v.kind, "Vote"),
            "outcome": v.outcome,
            "outcome_basis": getattr(v, "outcome_basis", None),
            "for": n_for,
            "against": n_against,
            "abstain": n_abs,
            "dossier_id": did,
            "dossier_ref": p.reference if p else None,
            "topics": self.topics_for(p) if p else [],
            "margin": margin,
            "has_ballots": bool(b is not None),
            "source": _src(v.source),
        }

    def ep_vote_detail(self, v: EpVote) -> dict:
        summ = self.vote_summary[v.id]
        b = self.ballots.get(v.id) if v.has_ballots else None
        ballots: list[dict] = []
        names: dict[str, str] = {}
        groups: dict[str, Counter] = defaultdict(Counter)
        countries: dict[str, Counter] = defaultdict(Counter)
        recon = {"matches": False, "note": "No individual (roll-call) votes are recorded for this vote."}
        if b is not None:
            intended: dict[str, str] = {}
            for pos, ids in (("for", b.intended_favor), ("against", b.intended_against),
                             ("abstain", b.intended_abstain)):  # fmt: skip
                for i in ids:
                    intended[i] = pos
            seen: set[str] = set()
            for pos, ids in (("for", b.favor), ("against", b.against), ("abstain", b.abstain)):
                for mid in ids:
                    if mid in seen:
                        continue
                    seen.add(mid)
                    m = self.mep.get(mid)
                    gid = self.group_at(mid, v.date)
                    slug = self.org_slug.get(gid) if gid else None
                    party = self.party_at(mid, v.date)
                    country = m.country if m else None
                    it = intended.get(mid)
                    ballot = {"mep": mid, "pos": pos, "group": slug, "country": country}
                    if party:
                        ballot["party"] = party
                    if it and it != pos:
                        ballot["intended"] = it  # correction recorded after the vote
                    ballots.append(ballot)
                    names[mid] = m.name if m else mid
                    groups[slug or "unknown"][pos] += 1
                    if country:
                        countries[country][pos] += 1
                    self.mep_votes[mid].append({"vote_id": v.id, "pos": pos, "_d": v.date})
            ballots.sort(key=lambda x: (x["pos"], names.get(x["mep"], ""), x["mep"]))
            rf, ra, rb = len(b.favor), len(b.against), len(b.abstain)
            if v.n_for is None:
                recon = {
                    "matches": False,
                    "note": "Official totals not published; counts are recorded individual votes.",
                }
            elif (rf, ra, rb) == (v.n_for, v.n_against, v.n_abstain):
                recon = {"matches": True, "note": None}
            else:
                recon = {
                    "matches": False,
                    "note": f"Recorded individual votes ({rf} for, {ra} against, {rb} abstentions) differ from "
                    f"the official totals ({v.n_for} for, {v.n_against} against, {v.n_abstain} abstentions). "
                    "The official result is authoritative.",
                }
        gb = []
        for slug, c in sorted(groups.items()):
            total = c["for"] + c["against"] + c["abstain"]
            maj = max(("for", "against", "abstain"), key=lambda k: (c[k], k == "for")) if total else None
            top = c[maj] if maj else 0
            tie = maj is not None and sum(1 for k in ("for", "against", "abstain") if c[k] == top) > 1
            majority = None if tie else maj
            cohesion = round(top / total, 3) if total and not tie else None
            entry = {
                "group": slug, "group_code": self.group_code(slug) or slug.upper(),
                "for": c["for"], "against": c["against"], "abstain": c["abstain"],
                "majority": majority, "cohesion": cohesion,
            }  # fmt: skip
            gb.append(entry)
            if slug != "unknown":
                self.group_votes[slug].append({
                    "vote_id": v.id, "majority": majority, "cohesion": cohesion,
                    "counts": {"for": c["for"], "against": c["against"], "abstain": c["abstain"]}, "_d": v.date,
                })  # fmt: skip
        gb.sort(key=lambda g: (-(g["for"] + g["against"] + g["abstain"]), g["group"]))
        cb = [
            {"country": k, "for": c["for"], "against": c["against"], "abstain": c["abstain"]}
            for k, c in sorted(countries.items())
        ]
        return {
            **summ,
            "reference_text": v.reference_text,
            "doc_ids": v.doc_ids,
            "attendees": v.attendees,
            "groups": gb,
            "countries": cb,
            "ballots": ballots,
            "mep_names": dict(sorted(names.items())),
            "reconciliation": recon,
        }

    # ---------------------------------------------------------------- Council
    def build_council(self) -> None:
        assess = _lazy("pipeline.analysis.council_qmv", "assess")
        self.council_of: dict[str, list[dict]] = defaultdict(list)
        self.council_public: list[dict] = []
        for cv in sorted(self.s.council, key=lambda c: (c.date, c.id), reverse=True):
            ds = sorted({p.id for r in cv.procedure_refs if (p := self.resolve_ref(r))})
            did = ds[0] if len(ds) == 1 else None
            p = self.proc.get(did) if did else None
            assessment = None
            if assess is not None and cv.voting_rule != "unknown" and cv.positions:
                try:
                    assessment = self.council_rule_assessment(assess, cv, p)
                except Exception as e:  # noqa: BLE001
                    log.warning("council assessment failed for %s: %r", cv.id, e)
            if assessment and cv.voting_rule != "unanimity":
                assessment["single_state_veto_possible"] = False
            rec = {
                "id": cv.id, "date": cv.date, "title": cv.title, "dossier_id": did,
                "dossier_ref": p.reference if p else None, "configuration": cv.configuration,
                "stage": getattr(cv, "stage", None), "meeting": getattr(cv, "meeting", None),
                "written_procedure": getattr(cv, "written_procedure", None), "council_doc": cv.council_doc,
                "voting_rule": cv.voting_rule, "outcome": cv.outcome, "positions": dict(sorted(cv.positions.items())),
                "assessment": assessment, "statements": cv.statements, "source": _src(cv.source),
            }  # fmt: skip
            self.council_public.append(rec)
            for d in ds:
                self.council_of[d].append(rec)
        self.files["council/index.json"] = self.council_public

    def council_rule_assessment(self, assess: Any, cv: CouncilVote, p: Procedure | None) -> dict | None:
        """Apply the voting rule. Whether the Council acted on a Commission proposal (which changes the QMV
        threshold, TEU 16(4) vs TFEU 238(2)) is taken as established only when the linked procedure records
        a COM document; otherwise both thresholds are computed and the result is kept only if they agree,
        without asserting a legal basis."""
        year = int(cv.date[:4])
        if p is not None and p.com_refs:
            return council_assessment(_as_dict(assess(cv.positions, cv.voting_rule, True, year=year)))
        a = council_assessment(_as_dict(assess(cv.positions, cv.voting_rule, True, year=year)))
        b = council_assessment(_as_dict(assess(cv.positions, cv.voting_rule, False, year=year)))
        if a is None or b is None:
            return None
        if cv.voting_rule != "qmv":
            return a  # the proposal origin only matters for qualified majority
        if (a["adopted_by_rule"], a["blocking_minority_existed"]) != (
            b["adopted_by_rule"],
            b["blocking_minority_existed"],
        ):
            return None
        a["legal_basis"] = None
        a["note"] = (a["note"] + " " if a["note"] else "") + (
            "Whether the Council acted on a Commission proposal is not recorded in our data; the result is the "
            "same under both qualified-majority thresholds (55% and 72% of Member States, 65% of the population)."
        )
        return a

    # ---------------------------------------------------------------- dossiers
    def classify(self, p: Procedure) -> dict:
        children = self.split_children.get(p.id)
        if children:
            refs = ", ".join(self.proc[c].reference for c in children)
            text = (
                f"This file was split into separate procedures ({refs}). Follow those for the current status."
            )
            return self._status_dict({
                "status": {"stage": "unknown", "label": "Split into separate procedures", "explanation": text,
                           "since": None, "basis": "derived"},
                "next_step": {"text": text, "institution": None, "basis": "derived"},
            })  # fmt: skip
        fn = (
            _lazy("pipeline.analysis.status", "classify")
            if not hasattr(self, "_classify")
            else self._classify
        )
        self._classify = fn
        acts = self.acts_of.get(p.id, [])
        train = self.train_of.get(p.id, [])
        if fn is not None:
            try:
                return self._status_dict(_as_dict(fn(p, acts, train, date.fromisoformat(self.today))))
            except Exception as e:  # noqa: BLE001 - never let one dossier break the build
                log.warning("classify failed for %s: %r", p.id, e)
                self.s.issues.append(f"status.classify failed for {p.id}: {e!r}"[:300])
        return self.fallback_status(p, acts, train)

    @staticmethod
    def _status_dict(r: dict) -> dict:
        status = r.get("status") if isinstance(r.get("status"), dict) else {
            "stage": r.get("stage", "unknown"), "label": r.get("label") or STAGE_LABELS.get(r.get("stage"), ""),
            "explanation": r.get("explanation") or "", "since": r.get("since"), "basis": r.get("basis", "derived"),
        }  # fmt: skip
        stall = r.get("stall")
        if stall:
            stall = {k: stall.get(k) for k in STALL_KEYS}
        ns = r.get("next_step") or {}
        return {
            "status": {k: status.get(k) for k in ("stage", "label", "explanation", "since", "basis")},
            "next_step": {"text": ns.get("text") or "Not available.", "institution": ns.get("institution"),
                          "basis": ns.get("basis") or "unknown"} if ns else
                         {"text": "Not available.", "institution": None, "basis": "unknown"},
            "stall": stall,
            "application": r.get("application"),
        }  # fmt: skip

    def fallback_status(self, p: Procedure, acts: list[LegalAct], train: list[TrainFile]) -> dict:
        """Minimal conservative classification used only when pipeline.analysis.status is unavailable."""
        kinds = {e.kind.value: e.date for e in p.events if e.date <= self.today}
        stage, since = "proposed" if p.events else "unknown", p.started
        for k, st in (("negotiation_mandate", "negotiations"), ("ep_position", "parliament_position"),
                      ("provisional_agreement", "provisional_agreement")):  # fmt: skip
            if k in kinds:
                stage, since = st, kinds[k]
        for k, st in (("withdrawal", "withdrawn"), ("rejection", "rejected"), ("lapsed", "lapsed")):
            if k in kinds:
                stage, since = st, kinds[k]
        for a in acts:
            if a.date_signature and a.date_signature <= self.today:
                stage, since = "adopted", a.date_signature
            if a.date_publication and a.date_publication <= self.today:
                stage, since = "published", a.date_publication
            if a.in_force or (a.entry_into_force and a.entry_into_force <= self.today):
                stage, since = "in_force", a.entry_into_force or since
        return {
            "status": {
                "stage": stage, "label": STAGE_LABELS[stage],
                "explanation": "Status derived from the latest recorded procedural step.", "since": since,
                "basis": "derived",
            },
            "next_step": {"text": "Not available.", "institution": None, "basis": "unknown"},
            "stall": None,
            "application": None,
        }  # fmt: skip

    def derived_next_step(self, det: dict) -> dict:
        """Next step for in-force acts when the status module gives none (basis 'derived')."""
        ns = det["next_step"]
        if det["stage"] != "in_force" or (
            ns.get("basis") != "unknown" and ns.get("text") not in UNKNOWN_STEPS
        ):
            return ns
        app = det.get("application") or {}
        apply_dates = [d for d in app.get("application_dates", []) if d > self.today]
        general = next((x["date"] for x in app.get("transposition", []) if x["kind"] == "deadline"), None)
        if general and general > self.today and (not apply_dates or general <= apply_dates[0]):
            text = f"Member States must transpose the directive by {_long_date(general)}."
        elif apply_dates:
            text = f"Further provisions apply from {_long_date(apply_dates[0])}."
        else:
            text = "The legislative procedure is complete; the act applies."
        return {"text": text, "institution": None, "basis": "derived"}

    def application_info(self, acts: list[LegalAct]) -> dict | None:
        if not acts:
            return None
        eif = sorted({a.entry_into_force for a in acts if a.entry_into_force})
        app = sorted({d for a in acts for d in a.other_application_dates})
        tr_all = next(
            (classify_transposition(a) for a in acts if a.act_type == "directive" and a.transposition_deadlines), []
        )
        pending = not eif and any(a.entry_into_force_pending for a in acts)
        if not (eif or app or tr_all or pending):
            return None
        return {
            "entry_into_force": eif[0] if eif else None,
            "entry_into_force_pending": pending,
            "application_dates": app,
            "transposition_deadlines": [x.date for x in tr_all if x.kind != "application"],
            "transposition": [
                {"date": x.date, "kind": x.kind, "articles": [article_label(r) for r in x.articles]} for x in tr_all
            ],
            "future": any(d > self.today for d in eif + app + [x.date for x in tr_all]),
        }

    def timeline(self, p: Procedure, acts: list[LegalAct], votes: list[EpVote]) -> list[dict]:
        votes_by_date: dict[str, list[EpVote]] = defaultdict(list)
        for v in votes:
            if v.id in self.indexed_vote_ids:
                votes_by_date[v.date].append(v)
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        seen_ev: set[tuple[str, str, str]] = set()
        for e in p.events:
            if e.date > self.today:  # forecasts are not legally fixed dates
                continue
            kind = e.kind.value
            if (kind, e.date, e.title) in seen_ev:  # same step recorded by two EP sources (API and OEIL)
                continue
            seen_ev.add((kind, e.date, e.title))
            vote_id = None
            if kind in VOTE_EVENT_KINDS and votes_by_date.get(e.date):
                docs = {d.id for d in e.docs}
                cands = votes_by_date[e.date]
                by_doc = [v for v in cands if docs & set(v.doc_ids)]
                finals = [v for v in (by_doc or cands) if v.kind == "final"]
                pick = finals or by_doc or (cands if len(cands) == 1 else [])
                vote_id = pick[0].id if pick else None
            out.append({
                "id": e.id, "date": e.date, "kind": kind, "title": e.title, "detail": e.detail,
                "institution": e.institution, "state": "done", "key": kind in KEY_KINDS,
                "docs": [d.model_dump(mode="json") for d in e.docs], "source": _src(e.source), "vote_id": vote_id,
            })  # fmt: skip
            seen.add((kind, e.date))
        for a in acts:
            src = _src(a.source)
            label = f"{a.act_type.capitalize()} {a.celex}" if a.act_type != "other" else f"Act {a.celex}"
            # (kind, date, title, title once the date has passed)
            synth: list[tuple[str, str, str, str | None]] = []
            if a.date_signature:
                synth.append(
                    ("signature", a.date_signature, "Signed by the Presidents of Parliament and Council", None)
                )
            if a.date_publication:
                synth.append(
                    ("publication", a.date_publication, "Published in the Official Journal of the EU", None)
                )
            if a.entry_into_force:
                synth.append(("entry_into_force", a.entry_into_force, "Enters into force", None))
            for d in a.other_application_dates:
                synth.append(
                    ("application", d, "Further provisions start to apply (date recorded by EUR-Lex)", None)
                )
            for x in classify_transposition(a):
                arts = f" ({articles_text(x.articles)})" if x.articles else ""
                if x.kind == "deadline":
                    synth.append(("transposition_deadline", x.date,
                                  "Deadline for Member States to transpose the directive", None))  # fmt: skip
                elif x.kind == "further_deadline":
                    t = f"Further transposition deadline for specific provisions{arts}"
                    synth.append(("transposition_deadline", x.date, t, t + " (passed)"))
                else:
                    t = f"Application date for national transposition measures{arts}"
                    synth.append(("transposition_application", x.date, t, t))
            for kind, d, title, past_title in synth:
                if (kind, d) in seen:
                    continue
                seen.add((kind, d))
                future = d > self.today
                if not future:
                    title = past_title or PAST_TITLES.get(kind, title)
                out.append({
                    "id": f"act-{a.celex}-{kind}-{d}", "date": d, "kind": kind, "title": title,
                    "detail": label, "institution": "EUR-Lex", "state": "scheduled" if future else "done",
                    "key": True, "docs": [{"id": a.celex, "label": a.oj_ref or a.celex, "kind": "act", "date": a.date_document,
                                           "url": a.eurlex_url}],
                    "source": src, "vote_id": None,
                })  # fmt: skip
            for r in getattr(a, "court_rulings", []):
                if not r.date:
                    continue
                rs = ruling_summary(r)
                out.append({
                    "id": f"act-{a.celex}-ruling-{r.celex}", "date": r.date, "kind": "other",
                    "title": f"Court of Justice judgment ({r.case_number or r.celex})",
                    "detail": rs["summary"], "institution": "CJEU", "state": "done", "key": True,
                    "docs": [{"id": r.case_number or r.celex, "label": r.case_number or r.celex, "kind": "judgment",
                              "date": r.date, "url": r.url}],
                    "source": {"institution": "EUR-Lex", "url": r.url, "label": f"Judgment {r.case_number or r.celex}",
                               "identifier": r.ecli or r.celex, "retrieved_at": None, "published": r.date},
                    "vote_id": None,
                })  # fmt: skip
        out.sort(key=lambda x: (x["date"], x["state"] == "scheduled", x["id"]))
        return out

    def act_summary(self, a: LegalAct) -> dict:
        return {
            "celex": a.celex, "eli": a.eli, "act_type": a.act_type, "title": a.title,
            "date_document": a.date_document, "date_publication": a.date_publication,
            "entry_into_force": a.entry_into_force, "other_application_dates": a.other_application_dates,
            "transposition_deadlines": a.transposition_deadlines if a.act_type == "directive" else [],
            "in_force": a.in_force, "end_of_validity": a.end_of_validity, "eurlex_url": a.eurlex_url,
            "amends": a.amends, "amended_by": a.amended_by, "repeals": a.repeals, "repealed_by": a.repealed_by,
            "court_rulings": [ruling_summary(r) for r in getattr(a, "court_rulings", [])],
        }  # fmt: skip

    def transposition_status(self, celex: str, country: str, deadline: str | None) -> str:
        if celex not in self.measure_celexes:
            return "unavailable"
        if self.measures_by.get((celex, country)):
            return "measures_notified"
        if self.not_participating(celex, country):
            return "not_participating"
        if not deadline:
            return "no_deadline"
        if deadline > self.today:
            return "deadline_not_reached"
        return "none_found"

    def infr_info(self, ic: InfringementCase, celex: str | None = None) -> dict:
        return {
            "id": ic.id, "country": ic.country, "celex": celex or ic.celex, "title": ic.title,
            "non_communication": ic.non_communication, "latest_stage": ic.latest_stage,
            "latest_decision_date": ic.latest_decision_date, "status": ic.status, "source": _src(ic.source),
        }  # fmt: skip

    def implementation(self, acts: list[LegalAct]) -> dict | None:
        dirs = [a for a in acts if a.act_type == "directive"]
        if not dirs:
            return None
        a = dirs[0]
        deadline = general_deadline(a)
        countries = []
        for c in sorted(MEMBER_STATES):
            ms = self.measures_by.get((a.celex, c), [])
            dates = sorted(m.date for m in ms if m.date)
            countries.append({
                "country": c, "measures": len(ms), "status": self.transposition_status(a.celex, c, deadline),
                "latest_measure_date": dates[-1] if dates else None,
                "infringements": [self.infr_info(i, a.celex) for i in self.infr_by_celex.get(a.celex, [])
                                  if i.country == c],
            })  # fmt: skip
        note = (
            "Counts are national measures notified to the Commission and listed by EUR-Lex. "
            "'No measures found' means none appear in the available dataset; it is not, by itself, "
            "evidence that a country has failed to transpose the directive."
        )
        if a.celex not in self.measure_celexes:
            note = "National transposition data for this directive is not available in this release. " + note
        return {
            "celex": a.celex, "deadline": deadline, "countries": countries,
            "nim_url": f"https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:{a.celex}",
            "source": _src(a.source), "note": note,
        }  # fmt: skip

    def build_dossiers(self) -> None:
        self.dossier_summary: dict[str, dict] = {}
        self.dossier_detail: dict[str, dict] = {}
        for pid in self.dossier_ids:
            p = self.proc[pid]
            acts = self.acts_of.get(pid, [])
            votes = sorted(self.votes_of.get(pid, []), key=lambda v: (v.date, v.id), reverse=True)
            st = self.classify(p)
            tl = self.timeline(p, acts, votes)
            cur = self.curated_of.get(pid)
            done = [e for e in tl if e["state"] == "done"]
            instrument = None
            for a in acts:
                if a.act_type != "other":
                    instrument = a.act_type
                    break
            instrument = instrument or instrument_from_title(p.title)
            sigs = sorted(a.date_signature for a in acts if a.date_signature)
            pubs = sorted(a.date_publication for a in acts if a.date_publication)
            adopted = sigs[0] if sigs else (pubs[0] if pubs else None)
            if adopted and adopted > self.today:
                adopted = None
            fut = sorted(
                d
                for a in acts
                for d in [
                    *a.other_application_dates,
                    *(a.transposition_deadlines if a.act_type == "directive" else []),
                ]
                + ([a.entry_into_force] if a.entry_into_force else [])
                if d > self.today
            )
            if self._classify is not None:
                blocked = bool(st.get("stall") and st["stall"].get("official_label"))
            else:
                blocked = any("block" in t.status.lower() for t in self.train_of.get(pid, []))
            summ = {
                "id": pid,
                "ref": p.reference,
                "type": p.type,
                "type_label": TYPE_LABELS.get(p.type, f"Procedure ({p.type})"),
                "title": self.dossier_title(p),
                "official_title": p.title,
                "short": (cur or {}).get("what") or None,
                "topics": self.topics_for(p),
                "stage": st["status"].get("stage", "unknown"),
                "status_label": st["status"].get("label") or STAGE_LABELS.get(st["status"].get("stage"), ""),
                "started": p.started,
                "last_event": done[-1]["date"] if done else None,
                "adopted": adopted,
                "next_date": fut[0] if fut else None,
                "instrument": instrument,
                "celex": sorted({a.celex for a in acts}),
                "featured": bool(cur and cur.get("featured")),
                "officially_blocked": blocked,
                "has_ep_votes": any(v.id in self.indexed_vote_ids for v in votes),
                "has_council_votes": bool(self.council_of.get(pid)),
            }
            if summ["short"]:
                summ["short"] = re.sub(r"\s+", " ", str(summ["short"])).strip()
            self.dossier_summary[pid] = summ
            editorial = None
            if cur:
                editorial = {
                    "short_title": str(cur.get("short_title") or summ["title"]),
                    "what": str(cur.get("what") or "").strip(),
                    "why": str(cur.get("why") or "").strip(),
                    "aliases": _as_list(cur.get("aliases")),
                    "sources": [
                        {"label": str(s.get("label", "")), "url": str(s.get("url", ""))}
                        for s in cur.get("sources") or []
                        if isinstance(s, dict)
                    ],
                    "reviewed": str(cur.get("reviewed") or ""),
                }
            rapps = []
            for r in p.rapporteurs:
                m = self.mep.get(r.mep_id or "")
                gslug = None
                if m:
                    gid = self.current_or_last(self.mep_groups.get(m.id, []))
                    gslug = self.org_slug.get(gid) if gid else None
                rapps.append({
                    "mep_id": r.mep_id, "name": r.name, "group": gslug, "country": m.country if m else None,
                    "role": r.role,
                })  # fmt: skip
            sources = [_src(p.source)] + [_src(a.source) for a in acts]
            sources += [_src(t.source) for t in self.train_of.get(pid, [])]
            sources = _dedupe_sources(sources)
            det = {
                **summ,
                "editorial": editorial,
                **{k: st[k] for k in ("status", "next_step", "stall", "application")},
                "timeline": tl,
                "acts": [self.act_summary(a) for a in acts],
                "ep_votes": [self.vote_summary[v.id] for v in votes if v.id in self.vote_summary],
                "council_votes": self.council_of.get(pid, []),
                "implementation": self.implementation(acts),
                "committees": [{"code": c.code, "name": c.name, "role": c.role} for c in p.committees],
                "rapporteurs": rapps,
                "documents": [d.model_dump(mode="json") for d in p.documents],
                "related": [],
                "oeil_url": p.oeil_url,
                "sources": [x for x in sources if x],
                "changes": [],
            }
            if det["application"] is None:
                det["application"] = self.application_info(acts)
            det["next_step"] = self.derived_next_step(det)
            self.dossier_detail[pid] = det
        # officially established relations between dossiers (act amends/repeals another dossier's act)
        rels = (("amends", "Amends"), ("repeals", "Repeals"), ("repealed_by", "Repealed by"))
        # the inverse of a recorded "amends"/"repeals" is the same official fact
        inv_amended: dict[str, set[str]] = defaultdict(set)
        inv_repealed: dict[str, set[str]] = defaultdict(set)
        for a in self.s.acts:
            for c in a.amends:
                inv_amended[c].add(a.celex)
            for c in a.repeals:
                inv_repealed[c].add(a.celex)
        for pid, det in self.dossier_detail.items():
            related: dict[str, dict] = {}
            for a in self.acts_of.get(pid, []):
                # one item per amending act: its dossier when known, else the act itself (id = CELEX)
                for c in sorted(set(a.amended_by) | inv_amended.get(a.celex, set())):
                    others = sorted(o for o in self.act_dossiers.get(c, ()) if o != pid)
                    if others:
                        for other in others:
                            related.setdefault(f"amended_by:{other}", {
                                "id": other, "title": _truncate(self.dossier_summary[other]["title"], 160), "relation": "Amended by",
                            })  # fmt: skip
                    elif c not in self.act_dossiers:
                        related.setdefault(f"amended_by:{c}", {
                            "id": c, "title": f"Act {c} (EUR-Lex)", "relation": "Amended by",
                        })  # fmt: skip
                for attr, label in rels:
                    extra = inv_repealed.get(a.celex, set()) if attr == "repealed_by" else set()
                    for c in sorted(set(getattr(a, attr)) | extra):
                        for other in sorted(self.act_dossiers.get(c, ())):
                            if other != pid:
                                related.setdefault(f"{attr}:{other}", {
                                    "id": other, "title": _truncate(self.dossier_summary[other]["title"], 160), "relation": label,
                                })  # fmt: skip
            for child in self.split_children.get(pid, []):
                related.setdefault(f"split:{child}", {
                    "id": child, "title": _truncate(self.dossier_summary[child]["title"], 160), "relation": "Split into",
                })  # fmt: skip
            if (m := re.fullmatch(r"(\d{4}-\d{4})[A-Z]", pid)) and m.group(1) in self.dossier_summary:
                related.setdefault(f"split_from:{m.group(1)}", {
                    "id": m.group(1), "title": _truncate(self.dossier_summary[m.group(1)]["title"], 160),
                    "relation": "Split from",
                })  # fmt: skip
            order = {
                "Split into": 0,
                "Split from": 0,
                "Amended by": 1,
                "Repealed by": 2,
                "Amends": 3,
                "Repeals": 4,
            }
            det["related"] = sorted(related.values(), key=lambda r: (order.get(r["relation"], 9), r["id"]))
        index = sorted(
            self.dossier_summary.values(), key=lambda d: (d["last_event"] or "", d["id"]), reverse=True
        )
        self.files["dossiers/index.json"] = [_index_entry(d) for d in index]

    # ---------------------------------------------------------------- people
    def membership_periods(self, m: Mep, kind: str) -> list[dict]:
        out = []
        for x in m.memberships:
            if x.kind != kind:
                continue
            o = self.org.get(x.org_id)
            oid = self.org_slug.get(x.org_id, x.org_id) if kind == "group" else x.org_id
            out.append({
                "id": oid, "label": o.label if o else x.org_id, "code": o.code if o else None,
                "from": x.start, "to": x.end, "role": x.role,
            })  # fmt: skip
        out.sort(key=lambda r: (r["from"] or "", r["to"] or "9999"), reverse=True)
        return out

    def build_people(self) -> None:
        s = self.s
        rapp_for: dict[str, list[dict]] = defaultdict(list)
        for pid in self.dossier_ids:
            for r in self.proc[pid].rapporteurs:
                if r.mep_id:
                    rapp_for[r.mep_id].append({"dossier_id": pid, "title": self.dossier_summary[pid]["title"],
                                               "role": r.role})  # fmt: skip
        self.mep_summary: dict[str, dict] = {}
        for m in sorted(s.meps, key=lambda m: m.id):
            gid = self.current_or_last(self.mep_groups.get(m.id, []))
            pid = self.current_or_last(self.mep_parties.get(m.id, []))
            slug = self.org_slug.get(gid) if gid else None
            po = self.org.get(pid) if pid else None
            summ = {
                "id": m.id, "name": m.name, "sort": (m.sort_label or m.family_name or m.name).upper(),
                "country": m.country, "group": slug, "group_code": self.group_code(slug),
                "party": pid, "party_label": po.label if po else None, "active": m.active, "terms": m.terms,
            }  # fmt: skip
            self.mep_summary[m.id] = summ
            votes = sorted(self.mep_votes.get(m.id, []), key=lambda x: (x["_d"], x["vote_id"]), reverse=True)
            self.files[f"people/meps/{m.id}.json"] = {
                **summ,
                "groups": self.membership_periods(m, "group"),
                "parties": self.membership_periods(m, "party"),
                "committees": self.membership_periods(m, "committee"),
                "rapporteur_for": rapp_for.get(m.id, []),
                "votes": [{"vote_id": x["vote_id"], "pos": x["pos"]} for x in votes],
                "official_url": m.official_url,
                "source": _src(m.source),
            }
        self.files["people/meps.json"] = sorted(self.mep_summary.values(), key=lambda x: (x["sort"], x["id"]))
        active = [m for m in s.meps if m.active]
        # groups
        groups = []
        for slug, orgs in sorted(self.group_orgs.items()):
            latest = max(orgs, key=lambda o: o.start or "")
            ids = {o.id for o in orgs}
            members = [m for m in active if (g := self.current_or_last(self.mep_groups.get(m.id, []))) in ids
                       and any(sp[1] is None and sp[2] == g for sp in self.mep_groups.get(m.id, []))]  # fmt: skip
            terms = sorted({x.term for m in s.meps for x in m.memberships
                            if x.kind == "group" and x.org_id in ids and x.term})  # fmt: skip
            summ = {
                "id": slug, "code": latest.code or latest.label, "name": latest.label,
                "active": any(o.end is None for o in orgs), "terms": terms, "members": len(members),
                "countries": dict(sorted(Counter(m.country for m in members).items())),
            }  # fmt: skip
            groups.append(summ)
            parties: Counter = Counter()
            for m in members:
                pid = self.current_or_last(self.mep_parties.get(m.id, []))
                if pid:
                    parties[pid] += 1
            gv = sorted(self.group_votes.get(slug, []), key=lambda x: (x["_d"], x["vote_id"]), reverse=True)
            self.files[f"people/groups/{slug}.json"] = {
                **summ,
                "member_ids": sorted(m.id for m in members),
                "parties": [
                    {
                        "id": pid,
                        "label": self.org[pid].label if pid in self.org else pid,
                        "country": (self.org[pid].country if pid in self.org else None) or "",
                        "members": n,
                    }
                    for pid, n in sorted(parties.items(), key=lambda kv: (-kv[1], kv[0]))
                ],  # fmt: skip
                "votes": [{k: x[k] for k in ("vote_id", "majority", "cohesion", "counts")} for x in gv],
                "source": _src(latest.source),
            }
        groups.sort(key=lambda g: (not g["active"], -g["members"], g["id"]))
        self.group_summaries = groups
        self.files["people/groups.json"] = groups
        # parties
        party_meps: dict[str, list[tuple[Mep, str | None, str | None]]] = defaultdict(list)
        for m in s.meps:
            for start, end, oid in self.mep_parties.get(m.id, []):
                party_meps[oid].append((m, start, end))
        parties_out = []
        self.party_summary: dict[str, dict] = {}
        for oid in sorted(party_meps):
            o = self.org.get(oid)
            if o is None:
                continue
            rows = party_meps[oid]
            gh: dict[str, dict] = {}
            for m, start, end in rows:
                for gs, ge, gid in self.mep_groups.get(m.id, []):
                    lo = max(start or "", gs or "")
                    hi = min(end or "9999-12-31", ge or "9999-12-31")
                    if lo <= hi and gid in self.org_slug:
                        slug = self.org_slug[gid]
                        h = gh.setdefault(slug, {"group": slug, "from": lo or None, "to": hi, "meps": set()})
                        h["from"] = min(h["from"] or lo, lo) or None
                        h["to"] = max(h["to"], hi)
                        h["meps"].add(m.id)
            ongoing_ids = {m.id for m, _s, e in rows if e is None and m.active}
            summ = {
                "id": oid, "label": o.label, "code": o.code, "country": o.country or "",
                "members_active": len(ongoing_ids), "members_total": len({m.id for m, _s, _e in rows}),
                "groups": sorted(gh),
            }  # fmt: skip
            self.party_summary[oid] = summ
            parties_out.append(summ)
            meps_rows: dict[str, dict] = {}
            for m, start, end in sorted(rows, key=lambda r: (r[0].id, r[1] or "")):
                r = meps_rows.setdefault(m.id, {"id": m.id, "name": m.name, "active": m.active and False,
                                                "from": start, "to": end})  # fmt: skip
                r["from"] = min(r["from"] or start or "", start or "") or None
                r["to"] = None if (end is None or r["to"] is None) else max(r["to"], end)
                r["active"] = m.id in ongoing_ids
            self.files[f"people/parties/{oid}.json"] = {
                **summ,
                "meps": sorted(meps_rows.values(), key=lambda r: (not r["active"], r["name"], r["id"])),
                "group_history": [
                    {
                        "group": h["group"],
                        "from": h["from"],
                        "to": None if h["to"] == "9999-12-31" else h["to"],
                        "meps": len(h["meps"]),
                    }
                    for h in sorted(gh.values(), key=lambda h: (h["from"] or "", h["group"]))
                ],  # fmt: skip
                "source": _src(o.source),
            }
        parties_out.sort(key=lambda p: (p["country"], -p["members_active"], p["label"], p["id"]))
        self.files["people/parties.json"] = parties_out

    # ---------------------------------------------------------------- countries
    def build_countries(self) -> None:
        s = self.s
        infr_available = s.file_exists("implementation", "infringements")
        directives = sorted(
            {
                a.celex: a
                for d in self.dossier_ids
                for a in self.acts_of.get(d, [])
                if a.act_type == "directive"
            }.values(),
            key=lambda a: a.celex,
        )
        index = []
        for code, name in sorted(MEMBER_STATES.items()):
            active = sorted(
                (m for m in s.meps if m.active and m.country == code), key=lambda m: m.sort_label or m.name
            )
            groups = Counter(self.mep_summary[m.id]["group"] or "unknown" for m in active)
            cpos = Counter({"for": 0, "against": 0, "abstain": 0, "not_participating": 0})
            cvotes = []
            for cv in self.council_public:
                pos = cv["positions"].get(code)
                if pos:
                    cpos[pos] += 1
                    cvotes.append({"vote_id": cv["id"], "date": cv["date"], "title": cv["title"], "pos": pos,
                                   "dossier_id": cv["dossier_id"]})  # fmt: skip
            indicators = [
                {"indicator": i.indicator, "label": i.label, "value": i.value, "unit": i.unit, "period": i.period,
                 "definition": i.definition, "source": _src(i.source)}
                for i in sorted(s.indicators, key=lambda i: (i.indicator, i.period))
                if i.country == code
            ]  # fmt: skip
            infr = sorted(self.infr_by_country.get(code, []),
                          key=lambda i: (i.latest_decision_date or "", i.id), reverse=True)  # fmt: skip
            summ = {
                "code": code, "name": name, "meps_active": len(active),
                "groups": dict(sorted(groups.items())),
                "council_positions": {k: cpos[k] for k in ("for", "against", "abstain", "not_participating")},
                "indicators": indicators,
                "open_infringements": sum(1 for i in infr if i.status == "open") if infr_available else None,
            }  # fmt: skip
            index.append(summ)
            party_counts: Counter = Counter(self.mep_summary[m.id]["party"] for m in active
                                            if self.mep_summary[m.id]["party"])  # fmt: skip
            trans = []
            for a in directives:
                deadline = general_deadline(a)
                ds = sorted(self.act_dossiers.get(a.celex, ()))
                trans.append({
                    "celex": a.celex, "title": self.dossier_summary[ds[0]]["title"] if len(ds) == 1 else a.title,
                    "dossier_id": ds[0] if len(ds) == 1 else None, "deadline": deadline,
                    "measures": len(self.measures_by.get((a.celex, code), [])),
                    "status": self.transposition_status(a.celex, code, deadline),
                })  # fmt: skip
            self.files[f"countries/{code}.json"] = {
                **summ,
                "meps": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "group": self.mep_summary[m.id]["group"],
                        "party_label": self.mep_summary[m.id]["party_label"],
                    }
                    for m in active
                ],  # fmt: skip
                "parties": [
                    {"id": pid, "label": self.org[pid].label if pid in self.org else pid, "members_active": n}
                    for pid, n in sorted(party_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                ],  # fmt: skip
                "council_votes": cvotes,
                "transposition": trans,
                "infringements": [self.infr_info(i) for i in infr],
            }
        self.files["countries/index.json"] = index

    # ---------------------------------------------------------------- topics
    def build_topics(self) -> None:
        counts = Counter(t for d in self.dossier_summary.values() for t in d["topics"])
        self.topic_list = [
            {"slug": slug, "label": str(t.get("label") or slug), "description": str(t.get("description") or ""),
             "count": counts.get(slug, 0)}
            for slug, t in self.topics_cur.items()
        ]  # fmt: skip
        self.files["topics.json"] = self.topic_list

    # ---------------------------------------------------------------- activity
    def build_activity(self) -> None:
        from pipeline.analysis import activity

        snapshot_items = activity.snapshot_items(self)
        record = os.environ.get("EU_INTEL_RECORD_ACTIVITY") == "1"
        recorded = activity.update_state(self, self.state_dir, record=record)
        items = activity.merge(recorded, snapshot_items, today=self.today)
        self.activity_items = items
        self.files["activity.json"] = items
        by_dossier: dict[str, list[dict]] = defaultdict(list)
        for it in recorded:
            if it.get("dossier_id"):
                by_dossier[it["dossier_id"]].append(it)
        for pid, its in by_dossier.items():
            if pid in self.dossier_detail:
                self.dossier_detail[pid]["changes"] = sorted(
                    its, key=lambda x: (x["date"], x["id"]), reverse=True
                )
        for pid, det in self.dossier_detail.items():
            self.files[f"dossiers/{pid}.json"] = det

    # ---------------------------------------------------------------- home
    def latest_event(self, pid: str) -> dict | None:
        done = [e for e in self.dossier_detail[pid]["timeline"] if e["state"] == "done"]
        key = [e for e in done if e["key"]]
        return (key or done or [None])[-1]

    def build_home(self) -> None:
        featured = []
        cur_sorted = sorted(
            ((pid, c) for pid, c in self.curated_of.items() if c.get("featured")),
            key=lambda kv: (
                kv[1].get("feature_order") if isinstance(kv[1].get("feature_order"), (int, float)) else 1e9,
                kv[0],
            ),
        )
        for pid, c in cur_sorted:
            det = self.dossier_detail[pid]
            featured.append({
                "dossier": self.dossier_summary[pid], "what": str(c.get("what") or "").strip(),
                "why": str(c.get("why") or "").strip(), "status": det["status"], "latest": self.latest_event(pid),
                "next_step": det["next_step"], "source": _src(self.proc[pid].source),
            })  # fmt: skip
        today = self.today
        summ = self.dossier_summary
        # recently adopted (formal adoption = signature/publication of the final act)
        adopted = sorted(
            (d for d in summ.values() if d["stage"] in ADOPTED_STAGES and d["adopted"] and d["type"] in LEGISLATIVE_TYPES),
            key=lambda d: (d["adopted"], d["id"]), reverse=True,
        )[:12]  # fmt: skip
        recently_adopted = [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                             "date": d["adopted"], "badge": d["instrument"]} for d in adopted]  # fmt: skip
        debate = sorted(
            (d for d in summ.values() if d["stage"] in ACTIVE_STAGES and d["type"] in LEGISLATIVE_TYPES
             and d["last_event"] and _days_between(d["last_event"], today) <= 120),
            key=lambda d: (d["last_event"], d["featured"], d["id"]), reverse=True,
        )[:12]  # fmt: skip
        under_debate = [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                         "date": d["last_event"], "badge": d["type"]} for d in debate]  # fmt: skip
        recent_cut = _add_days(today, -365)
        close = [
            v for v in self.vote_summary.values()
            if v["kind"] == "final" and v.get("margin") and v["date"] >= recent_cut
            and isinstance(v["margin"].get("relative"), (int, float))
        ]  # fmt: skip
        close.sort(
            key=lambda v: (
                abs(v["margin"]["relative"]),
                v["date"] and -int(v["date"].replace("-", "")),
                v["id"],
            )
        )
        close_votes = [{"vote_id": v["id"], "dossier_id": v["dossier_id"], "title": v["display_title"],
                        "subtitle": v["margin"].get("label"), "date": v["date"], "badge": v["outcome"]}
                       for v in close[:10]]  # fmt: skip
        rej_votes = [
            v
            for v in self.vote_summary.values()
            if v["outcome"] == "rejected" and v["kind"] in ("final", "motion")
        ]
        rej_items = [{"vote_id": v["id"], "dossier_id": v["dossier_id"], "title": v["display_title"],
                      "subtitle": v["kind_label"], "date": v["date"], "badge": "Rejected"} for v in rej_votes]  # fmt: skip
        rej_items += [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                       "date": self.dossier_detail[d["id"]]["status"].get("since") or d["last_event"], "badge": "Rejected"}
                      for d in summ.values() if d["stage"] == "rejected"]  # fmt: skip
        rej_items.sort(
            key=lambda x: (x["date"] or "", x.get("vote_id") or x.get("dossier_id") or ""), reverse=True
        )
        stalled_items = []
        for d in sorted(summ.values(), key=lambda d: d["id"]):
            if d["officially_blocked"]:
                stall = self.dossier_detail[d["id"]].get("stall") or {}
                label = stall.get("official_label")
                stalled_items.append({"dossier_id": d["id"], "title": d["title"],
                                      "subtitle": f"Legislative Train: {label}" if label else "Officially reported as blocked",
                                      "date": d["last_event"], "badge": "Officially blocked", "_o": 0})  # fmt: skip
        inactive = []
        for d in summ.values():
            # inactivity is only meaningful where both co-legislators must still act (ordinary procedure);
            # old consultation/consent files often end with a Council step that Parliament does not record
            if d["officially_blocked"] or d["stage"] not in ACTIVE_STAGES or d["type"] != "COD":
                continue
            if not d["last_event"]:
                continue
            n = _days_between(d["last_event"], today)
            if n >= 365:
                inactive.append((n, d))
        inactive.sort(key=lambda x: (-x[0], x[1]["id"]))
        stalled_items = stalled_items[:12]
        for n, d in inactive[:6]:
            stalled_items.append({"dossier_id": d["id"], "title": d["title"],
                                  "subtitle": f"No recorded procedural update in {n} days", "date": d["last_event"],
                                  "badge": d["status_label"], "_o": 1})  # fmt: skip
        for x in stalled_items:
            x.pop("_o", None)
        horizon = _add_days(today, 365)
        upcoming = []
        for pid in self.dossier_ids:
            for e in self.dossier_detail[pid]["timeline"]:
                if (
                    e["state"] == "scheduled"
                    and e["kind"] in ("application", "transposition_deadline", "transposition_application",
                                      "entry_into_force")
                    and today < e["date"] <= horizon
                ):
                    upcoming.append({"dossier_id": pid, "title": summ[pid]["title"], "subtitle": e["title"],
                                     "date": e["date"], "badge": "Deadline" if e["kind"] == "transposition_deadline"
                                     else "Applies"})  # fmt: skip
        upcoming.sort(key=lambda x: (x["date"], not summ[x["dossier_id"]]["featured"], x["dossier_id"]))
        lists = [
            {"id": "recently_adopted", "title": "Recently adopted",
             "description": "Laws formally adopted (signed or published in the Official Journal), newest first.",
             "items": recently_adopted},
            {"id": "under_debate", "title": "Under discussion",
             "description": "Legislative files with a recorded procedural step in the last 120 days that are not yet adopted.",
             "items": under_debate},
            {"id": "close_votes", "title": "Close votes",
             "description": "Final Parliament votes of the last 12 months decided by the smallest margin against the applicable majority.",
             "items": close_votes},
            {"id": "rejected", "title": "Rejected",
             "description": "Votes on whole texts or motions that Parliament rejected, and files recorded as rejected. "
                            "A rejected amendment is not a rejected law, so amendments are not listed.",
             "items": rej_items[:12]},
            {"id": "stalled", "title": "Stalled",
             "description": "Files officially reported as blocked (Legislative Train), then files with no recorded "
                            "procedural update for a year or more.",
             "items": stalled_items},
            {"id": "upcoming", "title": "Coming up",
             "description": "Legally fixed dates in the next 12 months: provisions starting to apply and transposition deadlines.",
             "items": upcoming[:15]},
        ]  # fmt: skip
        self.files["home.json"] = {"featured": featured, "lists": lists, "topics": self.topic_list}

    # ---------------------------------------------------------------- search
    def build_search(self) -> None:
        self.files["search.json"] = build_search_docs(self)

    # ---------------------------------------------------------------- meta
    def build_meta(self) -> None:
        s = self.s
        m = s.manifest
        sources = []
        for sid, info in SOURCES.items():
            st = m.get(sid)
            sources.append({
                "id": sid, "name": info["name"], "institution": info["institution"], "url": info["url"],
                "licence": info["licence"], "status": st.status if st else "unavailable",
                "fetched_at": st.fetched_at if st else None, "records": dict(sorted(st.records.items())) if st else {},
                "note": st.note if st else "Not yet retrieved in this release.",
            })  # fmt: skip
        fetched = [x.fetched_at for x in m.values() if x.fetched_at]
        notes = self.coverage_notes()
        self.files["meta.json"] = {
            "built_at": os.environ.get("EU_INTEL_BUILT_AT") or now_iso(),
            "snapshot_at": max(fetched) if fetched else None,
            "sources": sources,
            "counts": {
                "dossiers": len(self.dossier_summary),
                "legal_acts": len(s.acts),
                "meps": len(s.meps),
                "meps_active": sum(1 for x in s.meps if x.active),
                "ep_votes": len(self.indexed_votes),
                "ep_votes_with_ballots": sum(
                    1 for v in self.indexed_votes if v.id in self.ballots and v.has_ballots
                ),
                "council_votes": len(s.council),
                "national_measures": len(s.measures),
                "infringements": len(s.infringements),
            },
            "coverage_notes": notes,
        }

    def coverage_notes(self) -> list[str]:
        s = self.s
        m = s.manifest
        notes: list[str] = []

        def avail(sid: str) -> bool:
            st = m.get(sid)
            return bool(st and st.fetched_at and st.status in ("ok", "partial"))

        if avail("ep_people"):
            notes.append("MEPs: everyone who sat in the 9th (2019–2024) or 10th (from 2024) Parliament, with their "
                         "political group and national party memberships as recorded by the European Parliament.")  # fmt: skip
        else:
            notes.append("MEPs: not available in this release.")
        n_ep = len(self.dossier_summary) - len(self.stub_ids)
        if avail("ep_procedures") and n_ep:
            notes.append(f"Legislation: {n_ep:,} procedures recorded by the European Parliament. Status is derived "
                         "from the recorded procedural steps and EUR-Lex dates.")  # fmt: skip
        else:
            notes.append(
                "Legislation: the European Parliament procedure data was not available for this release."
            )
        if self.stub_ids:
            notes.append(f"{len(self.stub_ids):,} adopted laws are shown from their EUR-Lex record only (procedure "
                         "reference, title and legal dates), because the European Parliament procedure record is "
                         "not in this release; their Parliament steps are not shown.")  # fmt: skip
        if avail("ep_votes"):
            notes.append(f"Parliament votes: {len(self.indexed_votes)} plenary votes are listed (votes on whole texts, "
                         "resolutions and motions with roll-call results, and all final votes linked to a procedure). "
                         "Group and country breakdowns use each MEP's membership on the day of the vote. "
                         "MEPs who did not vote are not counted as abstentions.")  # fmt: skip
        else:
            notes.append("Parliament votes: not available in this release.")
        if avail("eurlex"):
            notes.append(f"Adopted acts: {len(s.acts)} legal acts from EUR-Lex/Cellar, linked to procedures only "
                         "through the procedure reference recorded by the Publications Office or Parliament.")  # fmt: skip
        else:
            notes.append("Adopted acts (EUR-Lex): not available in this release, so adoption, entry-into-force "
                         "and application dates may be missing.")  # fmt: skip
        if avail("council") and s.council:
            dates = sorted(c.date for c in s.council)
            unread = sum(1 for c in s.council if not c.positions)
            note = (f"Council votes: {len(s.council):,} voting results of the Council of the EU "
                    f"({dates[0][:4]}–{dates[-1][:4]}), with each Member State government's position read from the "
                    "official Council voting-result documents. These are positions of national governments in "
                    "the Council, not of MEPs. Only a vote under unanimity can be blocked by a single country.")  # fmt: skip
            if unread:
                note += (
                    f" {unread} voting-result document(s) could not be read and are shown without positions."
                )
            notes.append(note)
        else:
            notes.append("Council votes: not available from an accessible official machine-readable source in "
                         "this release.")  # fmt: skip
        if s.measures:
            with_m = len({m.directive_celex for m in s.measures})
            notes.append(f"National implementation: {len(s.measures):,} national transposition measures listed by "
                         f"EUR-Lex for the {len(self.measure_celexes):,} directives queried ({with_m:,} with at least "
                         "one measure). Directives not queried are shown as 'not available'. 'No measures found' "
                         "only means none appear in the available dataset — it is not, by itself, evidence that a "
                         "country has failed to transpose a directive.")  # fmt: skip
        else:
            notes.append("National transposition measures: not available in this release.")
        if s.infringements:
            notes.append(f"Infringements: {len(s.infringements):,} cases from the European Commission's infringement "
                         "decisions register, shown separately from transposition data. A case is linked to a "
                         "directive only when the register names it as the legal basis.")  # fmt: skip
        else:
            notes.append("Infringement cases: not available in this release.")
        if not s.indicators:
            notes.append("Country indicators (e.g. Single Market Scoreboard transposition deficit): not available "
                         "from an accessible official machine-readable source in this release.")  # fmt: skip
        if avail("train"):
            notes.append("'Officially blocked' labels come only from the European Parliament's Legislative Train "
                         "Schedule; other inactivity is shown as the number of days without a recorded procedural update.")  # fmt: skip
        else:
            notes.append("Legislative Train Schedule: not available in this release, so no file is labelled as "
                         "officially blocked; inactivity is shown only as days without a recorded update.")  # fmt: skip
        return notes


# ------------------------------------------------------------------------------------------- search
def _norm_key(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFD", s)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _join_alts(values: list[str], exclude: str = "") -> str | None:
    seen = {_norm_key(exclude)} if exclude else set()
    out = []
    for v in values:
        v = re.sub(r"\s+", " ", str(v)).strip()
        k = _norm_key(v)
        if v and k and k not in seen:
            seen.add(k)
            out.append(v)
    return " | ".join(out) or None


def _com_variants(ref: str) -> list[str]:
    """'COM(2021)0206' -> also 'COM(2021)206' and 'COM/2021/206'."""
    m = re.match(r"^COM\((\d{4})\)0*(\d+)", ref.replace(" ", ""), re.IGNORECASE)
    if not m:
        return [ref]
    return [ref, f"COM({m.group(1)}){m.group(2)}", f"COM/{m.group(1)}/{m.group(2)}"]


ALIAS_RULE_MAX_DOCS = 60

# "Regulation (EU) 2024/1689 of ...", "Regulation (EU) No 1316/2013 ...", "Directive 2014/24/EU ...",
# "Council Implementing Decision (EU) 2024/123 ...", "2014/335/EU, Euratom: Council Decision of ..."
_ACT_NUMBER = re.compile(
    r"^(?:(?:Commission\s+|Council\s+)?(?:Implementing\s+|Delegated\s+)?(?:Regulation|Directive|Decision)\s*"
    r"(?:\((?:EU|EC|EEC|Euratom)(?:,\s*Euratom)?\)\s+)?(?:No\s+)?(\d{1,4}/\d{1,4})\b"
    r"|(\d{4}/\d{1,4})/(?:EU|EC|EEC|Euratom)\b)"
)
_ACT_TITLE_TAIL = re.compile(r"\s*\((?:Text with EEA relevance|recast|codification)\)\s*$", re.IGNORECASE)
_ACT_OWN_SHORT = re.compile(
    r"\(['‘’\"“]?([A-Z][^()]{2,70}?(?:Act|Regulation|Directive|Code|Mechanism|Instrument|Fund|Programme|Law))"
    r"['‘’\"”]?\)$"
)
_ACT_SUBJECT = re.compile(r"\bof\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\s+(.*)$", re.DOTALL)
TRAIN_NAME_MAX = 60


def act_number(celex: str, title: str = "") -> str | None:
    """The act's number as the Official Journal cites it: '2024/1689' for Regulation (EU) 2024/1689,
    '1316/2013' for Regulation (EU) No 1316/2013, '2014/24' for Directive 2014/24/EU.

    Read from the start of the act's own title; for acts from 2015 on (one numbering for all acts,
    'YYYY/N') it can also be derived from a sector-3 CELEX number ('32024R1689').
    """
    m = _ACT_NUMBER.match(title or "")
    if m:
        return m.group(1) or m.group(2)
    m = re.fullmatch(r"3(\d{4})[RLD]0*(\d+)", celex or "")
    if m and int(m.group(1)) >= 2015:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def act_short_name(title: str) -> str | None:
    """The act's own short title, which the Official Journal title gives in parentheses at its end:
    '... and Directive (EU) 2020/1828 (Cyber Resilience Act) (Text with EEA relevance)'.

    An act whose subject is amending or repealing another act ('of 20 June 2019 amending Regulation
    (EC) No 810/2009 establishing a Community Code on Visas (Visa Code)') ends with the short title
    of that other act, so none is returned for it.
    """
    t = (title or "").strip()
    while (s := _ACT_TITLE_TAIL.sub("", t)) != t:
        t = s
    m = _ACT_OWN_SHORT.search(t)
    if not m:
        return None
    subject = _ACT_SUBJECT.search(t[: m.start()])
    if subject and re.match(r"(?:amending|repealing|correcting|supplementing)\b", subject.group(1)):
        return None
    return m.group(1).strip()


def train_names(files: list[TrainFile]) -> list[str]:
    """Short names the EP Legislative Train gives a file ('New Batteries Regulation'); long titles that
    restate the proposal ('Proposal for a Regulation on ...') are not names."""
    out = []
    for f in files:
        t = re.sub(r"\s+", " ", f.title or "").strip()
        if t and len(t) <= TRAIN_NAME_MAX and not t.lower().startswith("proposal"):
            out.append(t)
    return out


def curated_file_names(b: Builder) -> dict[str, list[str]]:
    """aliases.yaml entries {procedure, names}: verified common names of one legislative file
    ("Right to repair"), by procedure id. Each entry cites its source in a YAML comment."""
    out: dict[str, list[str]] = defaultdict(list)
    for e in b.alias_rules:
        ref = str(e.get("procedure") or "").strip()
        if not ref:
            continue
        p = b.resolve_ref(ref)
        if p is None:
            log.info("aliases.yaml: %s not in snapshot", ref)
            continue
        out[p.id] += _as_list(e.get("names"))
    return out


def ep_term_label(terms: set[int]) -> str:
    """{9} -> '2019–2024 term', {9, 10} -> '2019–2024 and 2024–2029 terms' (EP terms run five years from 1979)."""
    spans = [f"{1979 + 5 * (t - 1)}–{1984 + 5 * (t - 1)}" for t in sorted(terms)]
    return f"{' and '.join(spans)} term{'s' if len(spans) > 1 else ''}"


def build_search_docs(b: Builder) -> list[dict]:
    """SearchDoc[] for src/lib/search.ts. Field `a` holds alternative names separated by ' | '."""
    docs: list[dict] = []
    named = curated_file_names(b)
    for pid in sorted(b.dossier_summary):
        d = b.dossier_summary[pid]
        p = b.proc[pid]
        cur = b.curated_of.get(pid) or {}
        acts = b.acts_of.get(pid, [])
        alts = _as_list(cur.get("aliases")) + named.get(pid, []) + short_names(p.title)
        alts += [n for a in acts if (n := act_short_name(a.title))]
        alts += train_names(b.train_of.get(pid, []))
        if cur.get("short_title"):
            alts.append(clean_title(p.title))
        ids = [p.reference, ref_number(p.reference) or "", *d["celex"]]
        title_of = {a.celex: a.title for a in acts}
        ids += [n for c in d["celex"] if (n := act_number(c, title_of.get(c, "")))]
        for c in p.com_refs:
            ids += _com_variants(c)
        doc = {
            "id": pid, "k": "dossier", "t": d["title"], "s": f"{d['ref']} · {d['status_label']}",
            "a": _join_alts(alts, d["title"]), "x": " ".join(dict.fromkeys(i for i in ids if i)),
            "u": f"/legislation/{pid}",
            "w": 3.0 if d["featured"] else (1.2 if d["type"] in LEGISLATIVE_TYPES else 0.8),
            "d": d["last_event"],
        }  # fmt: skip
        docs.append(doc)
    # curated alias rules (data/curated/aliases.yaml): add `terms` as keywords to the documents whose
    # title, aliases or official title contain an `expands_to` phrase (or identifier)
    match_keys = []
    for doc in docs:
        names = [_norm_key(doc["t"])] + [_norm_key(a) for a in (doc.get("a") or "").split(" | ")]
        if doc["k"] == "dossier":
            names.append(_norm_key(b.proc[doc["id"]].title))
        match_keys.append((doc, names, {_norm_key(x) for x in (doc.get("x") or "").split()}))
    for rule in b.alias_rules:
        terms = _as_list(rule.get("terms"))
        targets = [_norm_key(t) for t in _as_list(rule.get("expands_to")) if _norm_key(t)]
        if not terms or not targets:
            continue
        hits = []
        for doc, names, idk in match_keys:
            if any(t in idk or any(f" {t} " in f" {n} " for n in names) for t in targets):
                hits.append(doc)
        if 0 < len(hits) <= ALIAS_RULE_MAX_DOCS:
            for doc in hits:
                have = set((doc.get("x") or "").split())
                add = [w for t in terms for w in [re.sub(r"\s+", "-", t.strip())] if w and w not in have]
                doc["x"] = " ".join([*(doc.get("x") or "").split(), *add]).strip() or None
        elif hits:
            log.info("alias rule %s matches %d documents; not embedded", terms[:1], len(hits))
    for m in sorted(b.mep_summary.values(), key=lambda m: m["id"]):
        sub = ["MEP" if m["active"] else "Former MEP", MEMBER_STATES.get(m["country"], m["country"])]
        if m["group_code"]:
            sub.append(m["group_code"])
        docs.append({"id": m["id"], "k": "mep", "t": m["name"], "s": " · ".join(sub),
                     "u": f"/people/meps/{m['id']}", "w": 1.5 if m["active"] else 0.7})  # fmt: skip
    for g in b.group_summaries:
        alts = [g["code"], *GROUP_ALIASES.get(g["id"], [])]
        sub = f"Political group · {g['members']} MEPs" if g["active"] else "Former political group"
        docs.append({"id": g["id"], "k": "group", "t": g["name"], "s": sub, "a": _join_alts(alts, g["name"]),
                     "u": f"/people/groups/{g['id']}", "w": 4.0 if g["active"] else 1.5})  # fmt: skip
    # EP open data has one record per party per parliamentary term, often with the same name: such
    # records say which term they cover, and earlier-term records rank below the latest one.
    party_terms: dict[str, set[int]] = defaultdict(set)
    for m in b.s.meps:
        for x in m.memberships:
            if x.kind == "party" and x.term:
                party_terms[x.org_id].add(x.term)
    same_party: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, pt in b.party_summary.items():
        same_party[(_norm_key(pt["label"]), pt["country"])].append(pid)
    for pid in sorted(b.party_summary):
        pt = b.party_summary[pid]
        sub = f"National party · {MEMBER_STATES.get(pt['country'], pt['country'] or 'unknown country')}"
        w = 1.3 if pt["members_active"] else 0.8
        twins = same_party[(_norm_key(pt["label"]), pt["country"])]
        if len(twins) > 1 and party_terms.get(pid):
            sub += f" · {ep_term_label(party_terms[pid])}"
            if max(party_terms[pid]) < max(max(party_terms.get(t) or {0}) for t in twins):
                w = 0.5
        doc = {"id": pid, "k": "party", "t": pt["label"], "s": sub, "u": f"/people/parties/{pid}", "w": w}
        if pt.get("code") and _norm_key(pt["code"]) != _norm_key(pt["label"]):
            doc["a"] = pt["code"]
        docs.append(doc)
    for code, name in sorted(MEMBER_STATES.items()):
        docs.append({"id": code, "k": "country", "t": name, "s": "EU Member State",
                     "a": _join_alts([*DEMONYMS.get(code, []), code], name), "u": f"/countries/{code}", "w": 5.0})  # fmt: skip
    for t in b.topic_list:
        cur = b.topics_cur.get(t["slug"], {})
        docs.append({"id": t["slug"], "k": "topic", "t": t["label"], "s": f"Topic · {t['count']} files",
                     "a": _join_alts(_as_list(cur.get("search_aliases")), t["label"]),
                     "u": f"/legislation?topic={t['slug']}", "w": 3.0})  # fmt: skip
    for g in GUIDE_PAGES:
        docs.append({"id": g["id"], "k": "page", "t": g["t"], "s": "How the EU works", "a": g["a"], "u": g["u"],
                     "w": 2.0})  # fmt: skip
    return [{k: v for k, v in d.items() if v is not None} for d in docs]


# ------------------------------------------------------------------------------------------- feeds/out
def write_output(files: dict[str, Any], extra: dict[str, str], out: Path = OUT) -> None:
    """Write into a private temp dir, then swap it in (old dir renamed away first, deleted last), so
    readers and concurrent builds see either the old or the new tree, never a half-written one."""
    tmp = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for rel in sorted(files):
        _write(rel, files[rel], tmp)
    for rel, text in sorted(extra.items()):
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    old = out.with_name(f"{out.name}.old-{os.getpid()}")
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def build(
    out: Path | None = None,
    snapshot: Path | None = None,
    curated: Path | None = None,
    state: Path | None = None,
    today: str | None = None,
) -> int:
    from pipeline.analysis import feeds

    out = out or OUT
    snap = Snapshot(snapshot or SNAPSHOT)
    b = Builder(snap, today=today, curated=curated or CURATED, state=state or STATE)
    files = b.run()
    site = os.environ.get("SITE_URL") or DEFAULT_SITE_URL
    extra = feeds.build_feeds(b, site_url=site)
    write_output(files, extra, out)
    sizes = {
        k: len(json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode()) for k, v in files.items()
    }
    for k in ("dossiers/index.json", "votes/index.json", "search.json", "home.json", "people/meps.json"):
        log.info("%-22s %8.1f KB", k, sizes.get(k, 0) / 1024)
    total = sum(sizes.values())
    log.info("wrote %d files (%.1f MB) to %s", len(files) + len(extra), total / 1e6, out)
    for i in snap.issues:
        log.warning("snapshot issue: %s", i)
    for k in ("dossiers/index.json", "search.json"):
        if sizes.get(k, 0) > 1_500_000:
            log.warning("%s exceeds 1.5 MB (%.2f MB)", k, sizes[k] / 1e6)
    return 0
