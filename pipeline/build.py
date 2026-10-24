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

from pipeline.analysis.transposition import application_start, article_label, articles_text, general_deadline
from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.models import entities
from pipeline.models.countries import FORMER_MEMBER_STATES, MEMBER_STATES
from pipeline.models.entities import (
    CouncilVote,
    CountryIndicator,
    DirectiveOptOut,
    DocRef,
    EpBallots,
    EpVote,
    Event,
    EventKind,
    InfringementCase,
    LegalAct,
    Mep,
    NationalMeasure,
    Organization,
    Procedure,
    ProcedureNotice,
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
# Verified 2026-10-23 (docs/DATA_SOURCES.md, "Licences", quotes the texts):
# - the EP Open Data Portal (data.europarl.europa.eu, OdpDatasetService/DatasetsLight and LabelSite/en) gives the
#   licence "CC BY 4.0 - Attribution 4.0 International" to its datasets of MEPs (every term), of the EP's corporate
#   bodies, of "EU procedures involving the European Parliament" (every year) and of "Results of votes" (2024 and
#   2025, the only years it lists). CC BY 4.0, Section 3(a)(1), asks for the credit, a notice and URI of the
#   licence, and an indication of changes;
# - the EP legal notice (https://www.europarl.europa.eu/legal-notice/en/), the general rule for the EP's data and
#   websites (Legislative Observatory, Legislative Train, plenary minutes): reuse "is authorised ... provided that
#   the entire item is reproduced and the source is acknowledged", and "Any partial reproduction ... must also cite
#   the URL link of the complete item or the web page from which it was sourced". Each page that shows such data
#   links the item it comes from (procedure file, Train page, minutes of the vote).
EP_CREDIT = "© European Union – Source: European Parliament."
EP_CC_BY = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
EP_LEGAL_NOTICE = (
    "the European Parliament legal notice authorises reuse provided that the entire item is reproduced and the "
    "source is acknowledged; a partial reproduction must cite the URL of the complete item or of the web page it "
    "comes from"
)
EP_ADAPTED = "Shown here adapted: selected, combined with other sources and reformatted."
SOURCES: dict[str, dict[str, str]] = {
    "ep_people": {
        "name": "European Parliament – MEPs, political groups and national parties",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": f"{EP_CREDIT} The EP Open Data Portal publishes its datasets of Members of the European "
        f"Parliament and of the Parliament's bodies under {EP_CC_BY}. {EP_ADAPTED}",
    },
    "ep_procedures": {
        "name": "European Parliament – legislative procedures (Legislative Observatory data)",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": f"{EP_CREDIT} The EP Open Data Portal publishes its datasets of EU procedures involving the "
        f"European Parliament under {EP_CC_BY}. For the Legislative Observatory's procedure files, {EP_LEGAL_NOTICE} "
        f"(each file here links its procedure file). {EP_ADAPTED}",
    },
    "ep_votes": {
        "name": "European Parliament – plenary votes and roll-call results",
        "institution": "EP",
        "url": "https://data.europarl.europa.eu/en/developer-corner/opendata-api",
        "licence": f"{EP_CREDIT} The EP Open Data Portal publishes its datasets of results of votes (2024 and "
        f"2025) under {EP_CC_BY}. For the other years, {EP_LEGAL_NOTICE} (each vote here links the minutes it "
        f"comes from). {EP_ADAPTED}",
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
        "name": "European Commission / EUR-Lex – national transposition measures and infringements",
        "institution": "Commission",
        "url": "https://commission.europa.eu/law/application-eu-law_en",
        "licence": "© European Union. Reuse authorised under Commission Decision 2011/833/EU, with "
        "acknowledgement of the source.",
    },
    "optouts": {
        "name": "EUR-Lex / Publications Office (Cellar) – directives' texts: Danish and Irish participation "
        "(Protocols No 21 and 22)",
        "institution": "EUR-Lex",
        "url": "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html",
        "licence": "© European Union, https://eur-lex.europa.eu. Reuse authorised under Commission "
        "Decision 2011/833/EU, with acknowledgement of the source.",
    },
    "train": {
        "name": "European Parliament – Legislative Train Schedule",
        "institution": "LegislativeTrain",
        "url": "https://www.europarl.europa.eu/legislative-train/",
        "licence": f"{EP_CREDIT} Under the European Parliament legal notice, reuse is authorised provided that the "
        "entire item is reproduced and the source is acknowledged; a partial reproduction must cite the URL of the "
        "complete item or of the web page it comes from (each file here links its Legislative Train page).",
    },
}

# Short plain-language badge for a procedure type on the home "Under discussion" list (else TYPE_LABELS); a bare
# "Consent" next to a file not yet adopted could read as consent given
HOME_PROCEDURE_BADGES: dict[str, str] = {
    "COD": "Ordinary procedure",
    "CNS": "Consultation procedure",
    "APP": "Consent procedure",
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
# What a final vote decides (EpVoteSummary.final_role, see final_role): the type of its one linked procedure, else
# the procedure symbol ending its published subject. Labels and phrases replace the kind's where given.
FINAL_ROLE_BY_SYMBOL = {"*": "consultation", "***": "consent", "***I": "legislative", "***II": "legislative",
                        "***III": "legislative"}  # fmt: skip
FINAL_ROLE_BY_TYPE = {
    "COD": "legislative", "SYN": "legislative", "CNS": "consultation", "APP": "consent", "AVC": "consent",
    "BUD": "budget", "DEC": "discharge", "RSO": "parliament_decision", "REG": "parliament_decision",
    "ACI": "parliament_decision",
}  # fmt: skip
FINAL_ROLE_LABELS: dict[str, str] = {
    "consent": "Vote on consent",
    "consultation": "Vote on Parliament's opinion (consultation)",
    "discharge": "Vote on discharge",
    "commission_election": "Vote of consent on the Commission",
}
FINAL_ROLE_PHRASE: dict[str, str] = {
    "consent": "vote on consent",
    "consultation": "vote on Parliament's opinion",
    "discharge": "vote on discharge",
    "commission_election": "vote of consent on the Commission",
}
# A discharge report's "proposal for a decision" grants, postpones or refuses discharge. Where the record says which
# (kind_detail grant_discharge / postpone_discharge / refuse_discharge, see ep_votes.discharge_proposal), the note
# says what the outcome decided; otherwise the record does not say (175931 of 7 May 2025: "Proposal for a decision"
# under the heading "European Council and Council")
DISCHARGE_NOTES = {
    "adopted": "Parliament adopted the proposal for a decision on discharge. The vote record does not say whether "
               "that decision grants, postpones or refuses discharge; the adopted text does.",
    "rejected": "Parliament rejected the proposal for a decision on discharge. The vote record does not say whether "
                "it proposed to grant, postpone or refuse discharge, and what the rejection means depends on that.",
}  # fmt: skip
DISCHARGE_PROPOSED = {"grant_discharge": "grant discharge", "postpone_discharge": "postpone discharge",
                      "refuse_discharge": "refuse discharge"}  # fmt: skip
DISCHARGE_ADOPTED = {
    "grant_discharge": "Parliament adopted the proposal and so granted discharge.",
    "postpone_discharge": "Parliament adopted the proposal and so postponed its decision on discharge.",
    "refuse_discharge": "Parliament adopted the proposal and so refused discharge.",
}
# What a rejected proposal means under the Rules of Procedure of the 9th term, Annex V, Article 5 (OJ L 302,
# 22.11.2019, p. 113): "If a proposal to postpone discharge fails to secure a majority, discharge shall be deemed to
# have been granted" (5(1)(b)), likewise a proposal to refuse discharge (5(2)(b)); a failed proposal to grant it
# postpones discharge at the April vote and refuses it at the October vote (5(1)(a), 5(2)(a)), which the record does
# not tell apart. Not stated for votes of later terms, whose Rules we have not checked.
DISCHARGE_REJECTED_9 = {
    "postpone_discharge": "Under its Rules of Procedure, discharge is therefore deemed to have been granted "
                          "(Annex V, Article 5(1)(b)).",
    "refuse_discharge": "Under its Rules of Procedure, discharge is therefore deemed to have been granted "
                        "(Annex V, Article 5(2)(b)).",
    "grant_discharge": "Under its Rules of Procedure, discharge is then deemed to have been postponed if this was "
                       "the first vote on the report, and refused if it was the second (Annex V, Article 5).",
}  # fmt: skip


def discharge_note(v: EpVote) -> str | None:
    """What the outcome of a vote on discharge means (DISCHARGE_ADOPTED / DISCHARGE_REJECTED_9 where the record says
    what was proposed, else DISCHARGE_NOTES): 142787, 4 May 2022, rejected a proposal to postpone discharge for the
    Court of Auditors (minutes: "Proposal for a decision to postpone the discharge"), so discharge was granted."""
    if v.kind_detail not in DISCHARGE_PROPOSED:
        return DISCHARGE_NOTES.get(v.outcome)
    if v.outcome == "adopted":
        return DISCHARGE_ADOPTED[v.kind_detail]
    if v.outcome != "rejected":
        return None
    effect = DISCHARGE_REJECTED_9[v.kind_detail] if v.term == 9 else None
    return " ".join(x for x in (f"Parliament rejected the proposal to {DISCHARGE_PROPOSED[v.kind_detail]}.", effect) if x)
# EpVote.kind_detail: what a motion or procedural vote decides (labels and phrases replace the kind's)
VOTE_DETAIL_LABELS: dict[str, str] = {
    "reject_proposal": "Vote on a motion to reject the Commission proposal",
    "reject_council_position": "Vote on a motion to reject the Council's position",
    "censure": "Vote on a motion of censure on the Commission",
    "objection": "Vote on an objection to a Commission measure",
    "no_objection": "Vote on a recommendation to raise no objections to a Commission measure",
    "negotiation_decision": "Vote on the committee's decision to enter into negotiations",
    "grant_discharge": "Vote on a proposal to grant discharge",
    "postpone_discharge": "Vote on a proposal to postpone discharge",
    "refuse_discharge": "Vote on a proposal to refuse discharge",
    "recommendation": "Vote on a recommendation of Parliament",
}
VOTE_DETAIL_PHRASE: dict[str, str] = {
    "reject_proposal": "motion to reject the Commission proposal",
    "reject_council_position": "motion to reject the Council's position (second reading)",
    "censure": "vote on a motion of censure",
    "objection": "vote on an objection",
    "no_objection": "vote on a recommendation to raise no objections",
    "negotiation_decision": "vote on the committee's decision to enter into negotiations with the Council",
    "grant_discharge": "vote on a proposal to grant discharge",
    "postpone_discharge": "vote on a proposal to postpone discharge",
    "refuse_discharge": "vote on a proposal to refuse discharge",
    "recommendation": "vote on the recommendation",
}
# What the official outcome means for these votes ("rejected" for a motion to reject is not a rejected law)
VOTE_OUTCOME_NOTES: dict[tuple[str, str], str] = {
    ("reject_proposal", "adopted"): "Parliament adopted the motion and so rejected the Commission proposal.",
    ("reject_proposal", "rejected"): "The motion was rejected: Parliament did not reject the Commission proposal.",
    ("reject_council_position", "adopted"): "Parliament adopted the motion and so rejected the Council's position.",
    ("reject_council_position", "rejected"): "The motion was rejected: Parliament did not reject the Council's position.",
    ("censure", "adopted"): "Parliament adopted the motion of censure.",
    ("censure", "rejected"): "The motion of censure was rejected: Parliament did not censure the Commission.",
    ("objection", "adopted"): "Parliament adopted the objection: it objects to the Commission measure.",
    ("objection", "rejected"): "The objection was rejected: Parliament did not object to the Commission measure.",
    ("no_objection", "adopted"): "Parliament adopted the recommendation: it declared that it has no objections to the "
                                 "Commission measure, which makes any later objection to it inadmissible.",
    ("no_objection", "rejected"): "The recommendation was rejected: Parliament did not declare that it has no "
                                  "objections to the Commission measure.",
    ("negotiation_decision", "adopted"): "Parliament approved the committee's decision to enter into negotiations "
                                         "with the Council.",
    ("negotiation_decision", "rejected"): "Parliament rejected the committee's decision to enter into negotiations "
                                          "with the Council.",
}  # fmt: skip
OEIL_PROCEDURE = "https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference="
# References for which OEIL has no procedure file (HTTP 404 "This procedure either does not exist", checked
# 2026-10-23), with the file that covers the act when there is one. Split parents (e.g. 2016/0224(COD)) have
# none either: OEIL files only the parts. Regulation (EU, Euratom) 2015/2422 is filed as 2011/0901B(COD).
OEIL_NO_FILE: dict[str, str | None] = {"2011-0901": f"{OEIL_PROCEDURE}2011/0901B(COD)", "2020-3521": None}
# Parliament's confirmation of a committee's decision to enter into negotiations (linked to the vote on that decision;
# a referral back to committee for negotiations, PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS, to none)
ENDORSE_NEGOTIATIONS_EVENT = "def/ep-activities/PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"
_SUBJECT_SYMBOL = re.compile(r"\s*\*{1,3}\s*(?:I{1,3})?\s*$")
_SUBJECT_NUMBER = re.compile(r"^\d{1,3}\.\s+")


def vote_subject(subject: str | None) -> str | None:
    """The published subject of a vote without its procedure symbol ("***I") or agenda number ("11. ")."""
    if not subject:
        return None
    s = _SUBJECT_NUMBER.sub("", _SUBJECT_SYMBOL.sub("", subject)).strip()
    return s or None


# Parliament's procedure symbols, as the "Keys to symbols used" of its minutes explain them (PV-9-2022-12-13)
PROCEDURE_SYMBOLS: dict[str, str] = {
    "*": "consultation procedure",
    "***": "consent procedure",
    "***I": "ordinary legislative procedure, first reading",
    "***II": "ordinary legislative procedure, second reading",
    "***III": "ordinary legislative procedure, third reading",
}


def subject_procedure(subject: str | None) -> str | None:
    """The procedure symbol ending a vote's published subject, in words (PROCEDURE_SYMBOLS), else None."""
    m = _SUBJECT_SYMBOL.search(subject or "")
    return PROCEDURE_SYMBOLS.get(re.sub(r"\s+", "", m.group(0))) if m else None


_ELECTION_OF_THE_COMMISSION = re.compile(r"^election of the commission\b", re.I)
# The last part of a label naming the consent procedure ("A9-0199/2020 - Iuliu Winkler - Consent procedure", 124729;
# "… - Approval procedure"; "… - procédure d'approbation"; "… - Consent")
_CONSENT_LABEL = re.compile(r"[-–]\s*(consent( procedure)?|approval procedure|procédure d.approbation)\s*$", re.I)


def final_role(v: EpVote) -> str | None:
    """What a final vote decides: "commission_election" for the vote titled "Election of the Commission" (the vote
    of consent on the Commission as a body, Art. 17(7) TEU), else by the type of its one linked procedure
    (FINAL_ROLE_BY_TYPE; an interim report "…R(APP)" or a resolution accompanying a consent "…M(APP)" has none),
    else by the symbol ending its published subject (FINAL_ROLE_BY_SYMBOL: NLE files are consents or
    consultations), else, for an NLE file, by its label naming the consent procedure (_CONSENT_LABEL: the subjects
    of the 2020 votes recorded only in French minutes carry no symbol, e.g. 113700, 124729); None when not
    established (e.g. a vote linked to no procedure and titled without a symbol).
    The type comes first: an EGF mobilisation, 2024/0003(BUD), is titled "… ***I" in Parliament's records (168353)."""
    if v.kind != "final":
        return None
    if _ELECTION_OF_THE_COMMISSION.match(v.title) or _ELECTION_OF_THE_COMMISSION.match(v.subject or ""):
        return "commission_election"
    types = {t.group(2) for r in v.procedure_refs if (t := re.fullmatch(r"\d{4}/\d{4}([A-Z]?)\(([A-Z]{3})\)", r))
             and t.group(1) not in ("R", "M")}  # fmt: skip
    if len(types) == 1 and (role := FINAL_ROLE_BY_TYPE.get(next(iter(types)))):
        return role
    m = _SUBJECT_SYMBOL.search(v.subject or "")
    if m:
        return FINAL_ROLE_BY_SYMBOL.get(re.sub(r"\s+", "", m.group(0)))
    return "consent" if types == {"NLE"} and _CONSENT_LABEL.search(v.title) else None


# Parliament's fixed procedural wording in French vote labels and referenceTexts, with the wording its English
# labels use for the same step (e.g. 199517 "RC-B10-0476/2026 - Proposition de résolution (ensemble du texte)",
# 153265 "RC-B9-0107/2023 – Motion for a resolution (text as a whole)")
FR_PROCEDURAL_TERMS: dict[str, str] = {
    "proposition de résolution (ensemble du texte)": "Motion for a resolution (text as a whole)",
    "proposition de résolution": "Motion for a resolution",
    "résolution": "Resolution",
    "proposition de la commission": "Commission proposal",
    "accord provisoire": "Provisional agreement",
    "proposition de rejet": "Proposal for rejection",
    "demande de renvoi en commission": "Request for referral back to committee",
    "proposition de décision (ensemble du texte)": "Proposal for a decision (text as a whole)",
    "proposition de décision": "Proposal for a decision",
    "projet de décision du conseil": "Draft Council decision",
    "vote unique": "Single vote",
    "procédure d'approbation": "Consent procedure",
}


def english_procedural(text: str | None) -> str | None:
    """`text` with every label segment that is one of FR_PROCEDURAL_TERMS in English; other text as published."""
    if not text:
        return text
    segs, seps = _segments(text)
    segs = [FR_PROCEDURAL_TERMS.get(seg.strip().replace("’", "'").casefold(), seg) for seg in segs]
    return _joined(segs, seps, 0, len(segs))


def search_subject(subject: str | None, *shown: str) -> str | None:
    """The published subject of a vote for keyword search, when the titles shown lack some of its words
    (vote 195775: "Temporary derogation from the ePrivacy directive", under the title of the act it amends)."""
    s = vote_subject(subject)
    if not s:
        return None
    return s if set(_norm_key(s).split()) - set(_norm_key(" ".join(shown)).split()) else None


# Parliament publishes some vote labels with the title in French, English and German, in that order, joined by
# " - " before the rest of the label (document reference, rapporteur, what was voted), e.g. vote 164581:
#   "Mise en œuvre de l’accord de partenariat économique (APE) UE-Communauté … - Implementation of the
#    EU-Southern African Development Community (SADC) Economic Partnership Agreement (EPA) - Umsetzung des …
#    - A9-0024/2024 - Joachim Schuster - Proposition de résolution (ensemble du texte)"
# Labels of recent sittings have no document reference and an en dash before the tail (vote 199407):
#   "Escalade des attaques des Houthis … - Escalation of Houthi attacks … - Eskalation der Huthi-Angriffe …
#    – Proposition de résolution (ensemble du texte)"
# A title can itself contain " - " ("Orientations pour le budget 2022 - section III - Guidelines for the 2022
# Budget - Section III - Leitlinien für den Haushaltsplan 2022 – Einzelplan III"), so the part before the
# reference is cut into three equal runs of segments. The cut is used only when the first run reads as French,
# the third as German and the second as neither (see label_languages); otherwise the label is left as it is.
_LABEL_SEP = re.compile(r"(\s+[-–]\s+)")
_LABEL_DOC_REF = re.compile(r"(?:RC-B|A|B|C)\d{1,2}-\d{4}/\d{4}")
_FR_ACCENT = re.compile(r"[àâçéèêëîïôûùœÀÂÇÉÈÊÎÔ]")
_FR_WORD = re.compile(
    r"\b(?:[Ll]es?|[Ll]a|[Dd]es?|[Dd]u|aux?|et|en|pour|sur|une?|dans|par|entre|concernant)\b|\b[LlDd][’']"
)
_FR_ONLY_WORD = re.compile(r"\b(?:[Ll]es?|[Ll]a|[Dd]u|aux?|et|pour|sur|une?|dans|par|entre)\b|\b[LlDd][’']")
_DE_LETTER = re.compile(r"[äöüßÄÖÜ]")
_DE_WORD = re.compile(
    r"\b(?:[Dd]er|[Dd]ie|[Dd]as|dem|den|und|für|über|zur|zum|von|vom|mit|im|zwischen|eines|einer|einem|"
    r"auf|bei|gegen|nach|sowie)\b"
)
# German titles without such a word ("Berichtspflichten", "Kritische Lage in Kuba", "Neue Strategie EU-Afrika"):
# endings and words found in the third title of such labels, none of them English
_DE_STEM = re.compile(
    r"\w(?:bericht|pflicht(?:en)?|politik|abkommen|ungen|heit|keit|schaft)\b|\w(?:isch|ziell)e[nrs]?\b|"
    r"\b(?:[Nn]eue[nrs]?|Lage)\b"
)
# French wording in the other segments of a label, as found in the data: procedural terms ("Proposition de
# résolution (ensemble du texte)", "Accord provisoire", "Après le considérant 3", "Article 2, alinéa 1") and
# French function words ("Protection des sols", "Cour des comptes"). Names of Members contain neither ("de" and
# "la" are left out for "Nicolás Pascual de la Parte", capitals for "Rosa D'Amato"). A segment with English or
# German words ("Motion for a resolution", "Durchführung des Programms") is not marked.
_FR_LABEL_TERM = re.compile(
    r"\b(?:proposition|projet|résolution|considérant|après|avant|alinéa|amendements?|séparés?|accord provisoire|"
    r"rejet|décharge|renvoi|ensemble du texte|ordre du jour|demande|procédure|annexe|décision|règlement|"
    r"commission compétente)\b",
    re.I,
)
_FR_LABEL_WORD = re.compile(r"\b(?:du|des|aux|pour|sur|et)\b|\b[ld][’']")
_EN_WORD = re.compile(r"\b(?:the|of|for|and|on|to|in|with|by|from|as)\b", re.I)


def _french_segment(s: str) -> bool:
    return bool(_FR_LABEL_TERM.search(s) or _FR_LABEL_WORD.search(s)) and not (
        _EN_WORD.search(s) or _DE_WORD.search(s) or _DE_LETTER.search(s)
    )


def _segments(label: str) -> tuple[list[str], list[str]]:
    """Label segments and the separators between them (len(seps) == len(segs) - 1)."""
    parts = _LABEL_SEP.split(label)
    return parts[0::2], parts[1::2]


def _joined(segs: list[str], seps: list[str], a: int, b: int) -> str:
    """Segments a..b-1 with their own separators, as published."""
    out = segs[a]
    for i in range(a + 1, b):
        out += seps[i - 1] + segs[i]
    return out


def _reads_french(s: str) -> bool:
    return bool(_FR_ACCENT.search(s) or _FR_WORD.search(s)) and not (
        _DE_LETTER.search(s) or _DE_WORD.search(s)
    )


def _reads_german(s: str) -> bool:
    return bool(_DE_LETTER.search(s) or _DE_WORD.search(s) or _DE_STEM.search(s)) and not (
        _FR_ACCENT.search(s) or _FR_ONLY_WORD.search(s)
    )


def _reads_neither(s: str) -> bool:
    return not (_FR_ACCENT.search(s) or _FR_WORD.search(s) or _DE_WORD.search(s)) and bool(
        re.search(r"[A-Za-z]{2}", s)
    )


def label_languages(label: str | None) -> tuple[int, int, int] | None:
    """(i, j, end) when `label` starts with the same title in French (segments 0..i-1), English (i..j-1) and
    German (j..end-1); None when the label is not such a concatenation or when in doubt.

    The titles end where the document reference starts ("A9-0024/2024"); without a reference, the whole label
    or the label without its last segment (the tail "Proposition de résolution …"). Runs of equal length are
    tried first; a title may also have more segments in one language than in another, where one translation
    uses " – " and another a colon (vote 145677). A joint motion repeats the three titles before its reference
    (vote 165966); the first three are used."""
    if not label:
        return None
    segs, seps = _segments(label)
    ref = next((i for i, s in enumerate(segs) if _LABEL_DOC_REF.fullmatch(s.strip())), None)
    ends = [ref] if ref is not None else [len(segs), len(segs) - 1]
    ends = [e // 2 if e >= 6 and e % 2 == 0 and segs[: e // 2] == segs[e // 2 : e] else e for e in ends]
    equal = [(e // 3, 2 * e // 3, e) for e in ends if 3 <= e <= 9 and e % 3 == 0]
    unequal = [
        (i, j, e)
        for e in ends
        if 3 <= e <= 9
        for i in range(1, 4)
        for j in range(i + 1, min(i + 4, e))
        if e - j <= 3 and not any(_french_segment(s) for s in segs[i:e])
    ]
    for i, j, end in equal + unequal:
        fr, en, de = _joined(segs, seps, 0, i), _joined(segs, seps, i, j), _joined(segs, seps, j, end)
        if len({fr, en, de}) == 3 and _reads_french(fr) and _reads_neither(en) and _reads_german(de):
            return i, j, end
    return None


def english_title(label: str | None) -> str | None:
    """The English title of a French-English-German vote label (see label_languages), else None."""
    found = label_languages(label)
    if not found or not label:
        return None
    i, j, _ = found
    segs, seps = _segments(label)
    return _joined(segs, seps, i, j).strip() or None


def label_parts(label: str | None) -> list[list[str | None]] | None:
    """`label` as consecutive [lang, text] runs whose texts join to the label: "fr" and "de" for the French and
    German titles of a trilingual label (label_languages) and for other French segments ("Proposition de
    résolution", see _french_segment); None (English, references, names) for the rest. None when nothing is
    French or German, so the page language applies to the whole label."""
    if not label:
        return None
    segs, seps = _segments(label)
    langs: list[str | None] = [None] * len(segs)
    start = 0
    found = label_languages(label)
    if found:
        i, j, start = found
        langs[:start] = ["fr"] * i + [None] * (j - i) + ["de"] * (start - j)
        if segs[start : 2 * start] == segs[:start]:  # the titles repeated (joint motion)
            langs[start : 2 * start] = langs[:start]
            start *= 2
    for i in range(start, len(segs)):
        if _french_segment(segs[i]):
            langs[i] = "fr"
    if not any(langs):
        return None
    out: list[list[str | None]] = []
    for i, s in enumerate(segs):
        pieces = [(langs[i], s)]
        if i:  # a separator inside a run of one language belongs to that run
            pieces.insert(0, (langs[i] if langs[i - 1] == langs[i] else None, seps[i - 1]))
        for lang, text in pieces:
            if out and out[-1][0] == lang:
                out[-1][1] = f"{out[-1][1]}{text}"
            elif text:
                out.append([lang, text])
    return out


_DOC_SERIES = (("RC-", "joint motion"), ("B", "motion"), ("A", "report"))
_DOC_HYPHENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2212"})  # in some document numbers


def vote_label_document(v: EpVote) -> str | None:
    """The text a vote's label names last, by its kind of document: "motion B9-0069/2020" (a motion for a
    resolution), "joint motion RC-B9-0073/2020", "report A9-0355/2023"."""
    refs = _LABEL_DOC_REF.findall(v.title.translate(_DOC_HYPHENS))
    if not refs:
        return None
    return next((f"{what} {refs[-1]}" for prefix, what in _DOC_SERIES if refs[-1].startswith(prefix)), refs[-1])


def vote_label_amendments(v: EpVote) -> str | None:
    """The amendments a label ends with: "… – Proposal for rejection – Am 1= 2= 7=" -> "amendments 1, 2 and 7"."""
    m = re.search(r"\bAms?\s+((?:\d+[A-Z]?=?[\s,]*)+)$", v.title)
    nums = re.findall(r"\d+[A-Z]?", m.group(1)) if m else []
    if not nums:
        return None
    return f"amendment {nums[0]}" if len(nums) == 1 else f"amendments {', '.join(nums[:-1])} and {nums[-1]}"


def vote_label_last(v: EpVote) -> str | None:
    """The last part of a vote's label when it is English text: "Proposal for a decision on discharge (EUAA)"."""
    segs, _ = _segments(v.title)
    last = segs[-1].strip() if len(segs) > 1 else ""
    return last if last and not _french_segment(last) and not _LABEL_DOC_REF.fullmatch(last) else None


def vote_held(v: EpVote) -> bool:
    """False for a vote that lapsed without being held (no counts): it decided nothing and is not shown."""
    return not (v.outcome == "lapsed" and v.n_for is None and not v.has_ballots)


KEY_KINDS = {
    "proposal",
    "committee_report",
    "negotiation_mandate",
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
# Steps of one day in procedural order, not by id ("2020-0055-PUB-…" < "council-ST-…"): a plenary vote before the
# decision it made, Parliament before the Council (consent and the opinion precede the Council's act; so does
# Parliament's first-reading position), then signature, publication and the act's dates (2020/0055(APP), 17 Apr
# 2020: Council Regulation (EU, Euratom) 2020/538 adopted by written procedure, published and in force that day)
DAY_ORDER = {k: i for i, k in enumerate((
    "proposal", "referral", "committee_opinion", "committee_report", "other", "provisional_agreement",
    "plenary_debate", "plenary_vote", "negotiation_mandate", "ep_position", "rejection", "council_position",
    "council_adoption", "signature", "publication", "entry_into_force", "application", "transposition_application",
    "transposition_deadline", "withdrawal", "lapsed",
))}  # fmt: skip
# Same-day steps that their kind does not place: a trilogue follows Parliament's decisions of the day (negotiations
# open on Parliament's mandate, Rule 72: 2025/0132(COD), 17 Dec 2025, the mandate confirmed by vote 182896 and the
# first trilogue); a text tabled for the plenary follows the committee's approval of it (2024/0071(COD), 16 Jun
# 2025); a second-reading step follows the Council's first-reading position of that day (2018/0136(COD), 14 Dec 2020:
# ST 14020/20, then the referral and the committee's recommendation for second reading)
TRILOGUE_TITLE = "Negotiation meeting with the Council (trilogue)"
TABLED_RE = re.compile(r"\btabled for the plenary$")
SITTING_RECORD_RE = re.compile(r"(?:CRE|PV)-")  # the sitting's verbatim report and minutes (EP document ids)
EP_REPORT_ID_RE = re.compile(r"A-\d+-\d{4}-\d{4}")  # a committee report (EP document id A-10-2026-0067)
SECOND_READING_RE = re.compile(r"(?<!early )\bsecond[ -]reading\b")


def day_rank(x: dict, position_days: set[str]) -> tuple[int, int]:
    """Sort key of a timeline step among the steps of its day (see DAY_ORDER)."""
    rank = DAY_ORDER.get(x["kind"], 99)
    if x["kind"] == "other" and x["title"] == TRILOGUE_TITLE:
        return DAY_ORDER["ep_position"], 1
    if x["date"] in position_days and rank < DAY_ORDER["council_position"] and SECOND_READING_RE.search(x["title"]):
        return DAY_ORDER["council_position"], 1 + rank  # (also a recommendation tabled that day: 2018/0136(COD))
    if x["kind"] == "other" and TABLED_RE.search(x["title"]):
        return DAY_ORDER["provisional_agreement"], 1
    return rank, 0


# The title of an act that Parliament and the Council adopt (not one that merely names such an act: "Council
# Regulation (EU) 2021/1696 ... extending ... Regulation (EU) 2021/840 of the European Parliament and of the Council";
# the official title of Regulation (EU) 2016/2031 omits the "and": "of the European Parliament of the Council")
JOINT_ACT_RE = re.compile(
    r"^(?:Regulation|Directive|Decision)(?:(?! of ).){0,40} of the European Parliament (?:and )?of the Council\b"
)
VOTE_EVENT_KINDS = {"ep_position", "plenary_vote", "rejection"}
REJECTION_MOTIONS = ("reject_proposal", "reject_council_position")  # EpVote.kind_detail of motions to reject the text
EP_VOTE_RECORDS = ("PLENARY_VOTE", "PLENARY_VOTE_RESULTS")  # an item of the sitting, not a decision
_VOTE_EVENT_ID = re.compile(r"^vote-(\d+)-")  # a step built from a vote (with_recorded_events: "vote-199592-…")
# a vote on a request to deal with a file by urgent procedure, as the EP labels it (the 2020 remote sittings only in
# French: "Demande d'application de la procédure d'urgence")
URGENCY_RE = re.compile(
    r"request\s+for\s+(?:an\s+)?urgen(?:t|cy)\s+(?:procedure|decision)|proc[ée]dure\s+d['’]urgence", re.I
)
JOINT_SIGNATURE = "Signed by the Presidents of Parliament and Council"
# Days from a Parliament decision recorded without a vote of the file that day to the vote that decided it (the
# remote voting of 2020-22 recorded votes up to a day before or two days after the decision: decision_vote_near)
DECISION_VOTE_DAYS = (-1, 2)
ADOPTION_EVENT_KINDS = (EventKind.council_adoption, EventKind.signature, EventKind.publication)
MANDATE_ANNOUNCED = "oeil:Committee decision to enter into interinstitutional negotiations announced in plenary"
ACTIVE_STAGES = {"proposed", "parliament_position", "negotiations", "provisional_agreement"}
ADOPTED_STAGES = {"adopted", "published", "in_force", "takes_effect_on_notification", "no_longer_in_force"}

# Days for which the membership records do not give the number of Members Parliament counted. They date the
# mandates of Oriol Junqueras i Vies, Carles Puigdemont i Casamajó and Antoni Comín i Oliveres from 2 July 2019,
# but Parliament took note of their election only on 13 January 2020, after the CJEU judgment of 19 December
# 2019, "with effect from 2 July 2019" (minutes PV-9-2020-01-13, item 6 "Composition of Parliament"). Until then
# it did not count them: "Parliament currently comprises 747 MEPs as per the official notifications received by
# member state authorities" (press release 20190711IPR56824, 16 July 2019), while the records give 751.
MEMBERS_COUNT_UNKNOWN = (("2019-07-02", "2020-01-12"),)
RULE_LABELS = {
    "votes_cast": "Majority of votes cast (abstentions are not counted)",
    "component_members": "Majority of Parliament's component Members (abstentions and absences count like votes against)",
    "two_thirds_cast": "Two-thirds of the votes cast, representing a majority of component Members",
}
# a close vote: the votes in favour within this share of the votes counted towards the threshold (the same
# rule as CLOSE_RELATIVE in src/features/votes/labels.ts, which the /votes page explains)
CLOSE_RELATIVE = 0.05
PAST_TITLES = {
    "entry_into_force": "Entered into force",
    "application": "Further provisions started to apply (date recorded by EUR-Lex)",
    "transposition_deadline": "Deadline for Member States to transpose the directive (passed)",
}
# status.py's in-force explanation for an act with later application dates; reworded for checked dates
EURLEX_LATER_DATES = "EUR-Lex records later dates from which (parts of) the act apply."
# The infringement register is read for open cases and cases with a decision since this date
# (pipeline/sources/implementation.py INFRINGEMENTS_SINCE_YEAR): earlier closed cases are not in the data
INFRINGEMENTS_FROM = "2019-01-01"
INDEX_OFFICIAL_TITLE_MAX = 140  # dossiers/index.json only; full titles are in dossiers/<id>.json
INDEX_TITLE_MAX = 180
VOTE_LABEL_TITLE_MAX = 200  # a vote titled by Parliament's raw label; the full label stays in `title`

STAGE_LABELS: dict[str, str] = {
    "proposed": "Proposed",
    "parliament_position": "Approved by Parliament",
    "negotiations": "In negotiations",
    "provisional_agreement": "Provisional agreement reached",
    "adopted": "Adopted",
    "published": "Published",
    "in_force": "In force",
    "takes_effect_on_notification": "Takes effect on notification",
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

# shown for a party record whose name in EP open data is only a placeholder ("-")
PARTY_NAME_MISSING = "Party name not recorded"


def unnamed_parties(orgs: list[Organization]) -> set[str]:
    """Party records whose only name in EP open data is a placeholder: corporate bodies 5500 and 5719 are
    labelled "-" in every language."""
    return {o.id for o in orgs if o.kind == "party" and not re.search(r"\w", o.label or "")}


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
     "a": "European Parliament | EP | parliament | MEP | MEPs | political group | political groups | plenary",
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


def _event_src(ref: Any) -> dict | None:
    """A timeline step's source. An EP Open Data API record (RDF/XML or JSON-LD, not a page to read) is labelled as
    data; the dossier links the human-readable procedure file (OEIL) separately."""
    src = _src(ref)
    if src and not src.get("label") and "data.europarl.europa.eu/api/" in (src.get("url") or ""):
        src["label"] = "Machine-readable record (EP Open Data API)"
    return src


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


# a drafting placeholder in a procedure title: "Extending Directive [XXXX] to ...", "Regulation (EU) No XXX/2011",
# "Directive (EU) .../...", "Regulation (EU) [...]"
TITLE_PLACEHOLDER_RE = re.compile(r"\[(?:X+|…|\.\.\.)\]|\bX{3,}\b|\.\.\./\.\.\.")
TITLE_NUMBER_RE = re.compile(r"\b\d{1,4}/\d{1,4}\b")  # an act cited by its number: "2014/41", "1316/2013"


def title_misfit(title: str, act_title: str) -> bool:
    """A procedure's title that does not describe the act it adopted: it has a drafting placeholder, or it cites acts
    (by number) that the act's official title does not. Directive (EU) 2023/2843 amends Directive 2011/99/EU and no
    Framework Decision 2002/465/JHA; its procedure's title (2021/0395(COD), the proposal's) says the reverse."""
    if TITLE_PLACEHOLDER_RE.search(title or ""):
        return True
    return bool(set(TITLE_NUMBER_RE.findall(title or "")) - set(TITLE_NUMBER_RE.findall(act_title or "")))


PARLIAMENT_REPORT_RE = re.compile(r"(\d{4}-\d{4})([RM])")
EP_TEXT_RE = re.compile(r"T\d{1,2}-\d{4}/\d{4}")  # a text adopted by Parliament, as OEIL cites it: T9-0129/2022
# Legislative proposals that OEIL lists under another institution than the Commission (documentation gateway)
OEIL_PROPOSAL_AUTHORS: dict[str, tuple[str, str]] = {
    # 2015/0906(COD): "CJEC - Legislative proposal", the Court's request under Article 281 TFEU
    "N8-0110/2015": ("Court of Justice submitted its request (legislative proposal)", "CJEU"),
    "N8-0050/2017": ("Council text submitted to Parliament", "Council"),  # 2016/0357B(COD): "Council of the EU"
}
# OEIL labels of the ordinary legislative procedure that do not fit consultation or consent (no readings there)
SPECIAL_PROCEDURE_TITLES = {
    "Parliament committee decided to open second-reading negotiations with the Council": (
        "Parliament committee decided to open negotiations with the Council"
    ),
    "Parliament committee decided to open negotiations with the Council after Parliament's first reading": (
        "Parliament committee decided to open negotiations with the Council"
    ),
    "Parliament committee approved the agreement reached with the Council for an early second reading": (
        "Parliament committee approved the text agreed with the Council"
    ),
}


def _plenary_decision(e: Event) -> bool:
    """Parliament's decision at a sitting; in consent files the EP API often records it as PLENARY_AMEND."""
    return e.kind == EventKind.ep_position or (e.raw_type or "").endswith("/PLENARY_AMEND")


def parliament_proposal_day(p: Procedure) -> str | None:
    """The day of Parliament's own proposal for the act of a consent file with no COM document: the file opens
    with a text adopted by Parliament (Article 223(1) TFEU, the Council acting "upon a proposal drawn up by the
    European Parliament"). OEIL lists that text as a "Preparatory document" (2022/0902(APP): T9-0129/2022 of 3 May
    2022, "Adopts the annexed proposal and submits it to the Council"; 2025/0900(APP): T10-0257/2025) or as the
    legislative proposal (2019/0900(APP): T8-0080/2019)."""
    if p.type != "APP" or p.com_refs or not p.events:
        return None
    first = min(e.date for e in p.events)
    return first if any(
        e.date == first and (e.kind == EventKind.proposal or e.raw_type == "oeil:Preparatory document")
        and any(EP_TEXT_RE.fullmatch(d.id) for d in e.docs)
        for e in p.events
    ) else None  # fmt: skip


ACT_NUMBER_RE = re.compile(
    r"^((?:Council |Commission )?(?:Implementing |Delegated )?(?:Regulation|Directive|Decision)"
    r"(?: \([A-Z][A-Za-z, ]*\))?(?: No)? \d{1,4}/\d{1,4}(?:/[A-Z]+)*)"
)


# an older act's number before its title: "2014/335/EU, Euratom: Council Decision of 26 May 2014 ..."
LEGACY_ACT_NUMBER_RE = re.compile(
    r"^(\d{4}/\d{1,4}/(?:EU|EC|EEC|CFSP|JHA)(?:, Euratom)?): "
    r"((?:Council |Commission )?(?:Implementing |Delegated )?(?:Regulation|Directive|Decision))\b"
)


def act_label(a: LegalAct) -> str:
    """'Regulation (EU) 2026/1744' from the act's official title, else its CELEX id. Cellar records a few titles
    without the space after the act type ('Directive2014/63/EU of the European Parliament ...', 'Regulation(EU)
    2022/870 ...'): the number is read with it; one with a Greek capital Epsilon in '(\u0395U)' (32024D2829); and
    older ones begin with the number ('2014/335/EU, Euratom: Council Decision ...' -> 'Council Decision 2014/335/EU,
    Euratom')."""
    title = re.sub(r"^((?:Council |Commission )?(?:Implementing |Delegated )?(?:Regulation|Directive|Decision))(?=[\d(])",
                   r"\1 ", (a.title or "").replace("(\u0395U)", "(EU)"))  # fmt: skip
    m = ACT_NUMBER_RE.match(title)
    if m:
        return m.group(1)
    m = LEGACY_ACT_NUMBER_RE.match(title)
    return f"{m.group(2)} {m.group(1)}" if m else a.celex


CELEX_ACT_RE = re.compile(r"^3(\d{4})([RLD])(\d{4})$")


def celex_act_label(celex: str) -> str | None:
    """'Regulation 2026/2102' for an act known only by its CELEX id: from 2015, when every act in the
    Official Journal L series is numbered year/number and the CELEX id carries that number, and for
    directives, always numbered year/number, from 1999 (four-digit years)."""
    m = CELEX_ACT_RE.match(celex)
    if not m or int(m.group(1)) < (1999 if m.group(2) == "L" else 2015):
        return None
    kind = {"R": "Regulation", "L": "Directive", "D": "Decision"}[m.group(2)]
    return f"{kind} {m.group(1)}/{int(m.group(3))}"


def _squash(text: Any) -> str:
    return " ".join(str(text or "").split())


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


_OPTIONAL_SUMMARY = ("short", "started", "last_event", "adopted", "published", "next_date", "instrument")


def _index_entry(d: dict) -> dict:
    """Compact DossierSummary for dossiers/index.json: long official titles shortened (full text in
    dossiers/<id>.json), optional fields omitted when empty."""
    out = {k: v for k, v in d.items() if not (k in _OPTIONAL_SUMMARY and v is None)}
    out["official_title"] = d["official_title"] and _truncate(d["official_title"], INDEX_OFFICIAL_TITLE_MAX)
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


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


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


_DOC_NUMBER_DASH = re.compile(r"\b((?:RC-B|A|B|C)\d{1,2})[\u2010-\u2015\u2212](\d{4}/\d{4})\b")


def _vote_index_entry(v: dict) -> dict:
    """Compact EpVoteSummary for votes/index.json (full record in votes/<id>.json)."""
    optional = (
        "dossier_id", "dossier_ref", "margin", "kind_detail", "outcome_note", "procedure_ref", "subject", "final_role",
        "distinction",
    )  # fmt: skip
    out = {k: x for k, x in v.items() if not (k in optional and x is None)}
    # session document numbers as officially written, with an ASCII hyphen ("A10–0049/2025" in vote 175067's label):
    # the votes search reads them from this title
    out["title"] = _DOC_NUMBER_DASH.sub(r"\1-\2", v["title"])
    src = v.get("source") or {}
    out["source"] = {k: src[k] for k in ("institution", "url") if src.get(k)}
    return out


def _valid_on(start: str | None, end: str | None, d: str) -> bool:
    return (start is None or start <= d) and (end is None or d <= end)


def mark_after_end_of_validity(timeline: list[dict], acts: list[LegalAct]) -> list[dict]:
    """Flag an act's own timeline entries (application dates, deadlines, amendments...) dated after the end of
    its validity, e.g. Regulation 2024/2822: validity ended 30 June 2026, provisions recorded to apply from
    1 July 2026. Such an entry is not the file's latest development. Not done when Cellar's end of validity
    is earlier than the act itself (a retroactive repeal), where every date of the act is later."""
    for a in acts:
        eov = a.end_of_validity
        if not eov or eov < (a.date_document or a.date_publication or ""):
            continue
        for e in timeline:
            if e["id"].startswith(f"act-{a.celex}-") and e["date"] > eov:
                e["after_end_of_validity"] = eov
    return timeline


# Title ep_procedures gives the OEIL key event "Council position published" (see `timeline`).
OEIL_POSITION_PUBLISHED = "Council adopted its first-reading position"
# Council document numbers: a voting result's reference "ST 9890/20" and OEIL's position "09890/2/2020"
_COUNCIL_DOC_NO = re.compile(r"\bST\s+0*(\d+)/(\d{2})\b")
_COUNCIL_POSITION_NO = re.compile(r"0*(\d+)/(?:\d+/)?(\d{4})")
# Parliament's decision on the Council's position at second reading (EP API activity types)
SECOND_READING_DECISION_RE = re.compile(r"PLENARY_(?:APPROVE|AMEND|REJECT)_COUNCIL_POSITION$")
_ACT_TITLE_HEAD = re.compile(r"^.*?\bof\s+the\s+council\b(?:\s+of\s+\d{1,2}\s+[a-z]+\s+\d{4})?", re.I | re.S)


def _act_subject_key(title: str) -> str:
    """First words of an act's title after "… of the European Parliament and of the Council [of <date>]", so
    a Council voting result ("REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending …") and the
    act ("Regulation (EU) 2023/957 of the European Parliament and of the Council of 10 May 2023 amending …")
    compare equal."""
    return " ".join(re.findall(r"[a-z0-9]+", _ACT_TITLE_HEAD.sub("", title, count=1).lower())[:12])


# Parliament's decision at first (or single) reading, recorded without saying what it was ("took its decision")
PLENARY_DECISION_TYPES = ("def/ep-activities/PLENARY_ADOPT_POSITION", "def/ep-activities/PLENARY_DECISION")
# The Council's own decision, by a separate vote, to derogate from the eight-week period between a draft act being
# made available to national parliaments and its placing on the Council's agenda (Rules of Procedure, Art. 3(3)):
# ST 8160/20 (2020/0067(COD)), next to ST 8159/20 adopting the act. Not the note "= Derogation from the 8-week
# period provided for in ..." that accompanies an adoption (ST 8159/20, ST 7391/20 REV 1).
COUNCIL_DEROGATION_RE = re.compile(
    r"Derogation,\s+on\s+the\s+basis\s+of\s+the\s+second\s+subparagraph\s+of\s+Article\s+3\(3\)\s+of\s+the\s+"
    r"Council['’]s\s+Rules\s+of\s+Procedure"
)
COUNCIL_CONSENT_RE = re.compile(r"Consent\s+of\s+the\s+Council\b")  # Art. 223(2), 226, 228(4) TFEU: ST 9947/21


def rejection_title(p: Procedure) -> str:
    """Title of Parliament's first-reading (or single-reading) decision whose final vote was a rejection."""
    council_text = any(
        e.kind == EventKind.proposal
        and e.institution != "CJEU"
        and e.docs
        and not any(d.id.startswith("COM(") for d in e.docs)
        and any(re.fullmatch(r"\d{5}/\d{2,4}", d.id) for d in e.docs)
        for e in p.events
    )
    what = "the Council's draft" if council_text and p.type != "COD" else "the proposal"  # see procedure_event
    if p.type == "COD":
        return f"Parliament rejected {what} at first reading"
    if p.type == "CNS":
        return f"Parliament delivered its opinion: it rejected {what}"
    if p.type == "APP":
        return "Parliament did not give its consent"
    return f"Parliament rejected {what}"


# The Council's consent to a regulation Parliament adopts on its own initiative after seeking the Commission's
# opinion (Article 228(4) TFEU, Ombudsman Statute: "with the consent of the Council"), e.g. ST 9947/21: the
# Council does not act on a Commission proposal, so the 72% threshold of Article 238(2) TFEU applies.
COUNCIL_CONSENT_TO_EP_ACT = re.compile(r"\bConsent\s+of\s+the\s+Council\s+\(Article\s+228\(4\)\s+TFEU\)", re.I)
_LEADING_DOC_REF = re.compile(r"^(?:RC-B|A|B|C)\d{1,2}[-\u2010-\u2013\u2212]\d{4}/\d{4}\s*[-\u2013]\s*")
# Parliament's referral of a file back to committee after its vote on the whole draft act (as its labels cite it)
_RULE_59_4 = re.compile(r"rule 59\(4\)|article 59, paragraphe 4", re.I)


def second_reading_amendments(votes: list[EpVote], day: str) -> str | None:
    """The votes by which Parliament amended the Council's position at second reading on `day`: those on amendments
    adopted with the votes of a majority of its component Members (Art. 294(7)(c) TFEU), named as Parliament labels
    them, since votes on amendments are not listed (2025/0429(COD), 9 July 2026: Am 30, 369 for; Am 26 CP3= …, 362
    for). Votes are counted, not amendments: one vote may cover several ("Am 1-243", 2013/0072(COD), 21 Jan 2026)."""
    adopted = sorted(
        (v for v in votes if v.date == day and v.kind == "amendment" and v.outcome == "adopted"
         and v.majority_rule == "component_members"),
        key=lambda v: (len(v.id), v.id),
    )  # fmt: skip
    if not adopted:
        return None
    names = [
        f"“{_LEADING_DOC_REF.sub('', v.title)}”" + (f" ({v.n_for} for)" if v.n_for else "")
        for v in adopted
    ]
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    what = "in one vote, adopted" if len(names) == 1 else f"in {len(names)} votes, each adopted"
    return (
        f"Parliament amended the Council's position {what} with the votes of a majority of its component Members: "
        f"{listed}. Votes on amendments are not listed on this site."
    )


def vote_label_doc_ids(v: EpVote) -> set[str]:
    """EP document ids of the session documents a vote's label names ("A9-0201/2021" -> "A-9-2021-0201")."""
    out = set()
    for ref in _LABEL_DOC_REF.findall(v.title.translate(_DOC_HYPHENS)):
        if m := re.fullmatch(r"(RC-B|A|B|C)(\d{1,2})-(\d{4})/(\d{4})", ref):
            series, term, num, year = m.groups()
            out.add(f"{'RC' if series == 'RC-B' else series}-{term}-{year}-{num}")
    return out


def referred_back(votes: list[EpVote]) -> set[str]:
    """Final votes followed later in their sitting by an adopted Rule 59(4) referral of the file back to committee
    on the same document (9th-term numbering; see Builder.referral_note)."""
    referrals: dict[str, list[EpVote]] = defaultdict(list)
    for v in votes:
        tail = _segments(v.title)[0][-1]
        if v.term == 9 and v.kind == "procedural" and v.outcome == "adopted" and _RULE_59_4.search(tail):
            referrals[v.event_id[:17]].append(v)
    return {
        v.id
        for v in votes
        if v.kind == "final"
        and any(
            int(r.id) > int(v.id) and vote_label_doc_ids(r) & vote_label_doc_ids(v)
            for r in referrals.get(v.event_id[:17], ())
        )
    }


def decision_vote_near(e: Event, votes_by_date: dict[str, list[EpVote]]) -> EpVote | None:
    """The vote that decided a Parliament decision recorded on a day without a vote of the file: its one final
    vote (for a second-reading decision: motion to reject the Council's position; for a decision recording the
    amendments voted before a referral back for negotiations, PLENARY_AMEND: the mandate vote on the amended text)
    dated DECISION_VOTE_DAYS around the decision, one that names a report the decision lists if any does; None unless
    exactly one, and None for a decision amending the Council's position (its amendments decided it).
    During remote voting (2020-22) the vote and the decision were recorded on different days: 2020/0331(CNS),
    vote 134869 on 6 July 2021, decision 7 July 2021; 2020/0065(COD), decision 13 May 2020, vote 114183 on 15 May;
    2021/0008(COD), mandate vote 135241 on 15 Sep 2021, decision on the amendments 16 Sep 2021."""
    raw = e.raw_type or ""
    second = bool(SECOND_READING_DECISION_RE.search(raw))
    if raw.endswith("PLENARY_AMEND_COUNCIL_POSITION"):
        return None
    if e.kind == EventKind.plenary_vote and not raw.endswith("/PLENARY_AMEND"):
        return None  # a step recording that a vote took place, not a decision
    want = "mandate" if e.kind == EventKind.plenary_vote else "final"
    lo, hi = DECISION_VOTE_DAYS
    cands = [
        v
        for day, vs in votes_by_date.items()
        if lo <= _days_between(e.date, day) <= hi
        for v in vs
        if (v.kind_detail == "reject_council_position" if second else v.kind == want)
    ]
    docs = {d.id for d in e.docs}
    own = [v for v in cands if docs & (vote_label_doc_ids(v) | {x.split("-AM-")[0] for x in v.doc_ids})]
    pick = own or cands
    return pick[0] if len(pick) == 1 else None


def council_vote_event(cv: dict) -> dict:
    """Timeline event for a Council vote, dated and sourced by the Council's voting-result document."""
    on, outcome = cv.get("vote_on"), cv["outcome"]
    kind = "other"
    if on == "first_reading_position":
        kind = "council_position"
        title = {
            "adopted": "Council adopted its position at first reading",
            "not_adopted": "Council did not adopt a position at first reading",
        }.get(outcome, "Council voted on its position at first reading")
    elif on == "act":
        kind = "council_adoption" if outcome == "adopted" else "other"
        title = {
            "adopted": "Council adopted the act",
            "not_adopted": "Council did not adopt the act",
        }.get(outcome, "Council voted on adopting the act")
    elif COUNCIL_CONSENT_RE.match(cv.get("stage") or ""):
        # the Council's consent to an act Parliament adopts: the step OEIL records as the Council's adoption
        kind = "council_adoption" if outcome == "adopted" else "other"
        title = {
            "adopted": "Council gave its consent",
            "not_adopted": "Council did not give its consent",
        }.get(outcome, "Council voted on its consent")
    elif COUNCIL_DEROGATION_RE.search(cv.get("stage") or ""):
        title = "Council decided to derogate from the eight-week period for national parliaments"
    elif cv.get("vote_on_label"):  # the item(s) voted on as lists name them (council_vote_items)
        title = f"Council vote: {cv['vote_on_label']}"
    elif cv.get("stage"):
        title = f"Council vote: {cv['stage']}"
    else:
        title = "Council vote (the voting-result document does not name the item voted on)"
    if cv.get("written_procedure"):
        title += " (written procedure)"
    detail = None
    if cv["positions"]:
        n = Counter(cv["positions"].values())
        detail = f"{n['for']} Member States in favour, {n['against']} against, {n['abstain']} abstained"
        if n["not_participating"]:
            detail += f", {n['not_participating']} not taking part"
    if cv.get("outcome_note"):  # an outcome corrected from the sheet's (council_votes.yaml): why, as on the vote
        detail = f"{detail}. {cv['outcome_note']}" if detail else cv["outcome_note"]
    # the texts a council_votes.yaml correction was checked against
    docs = [{"id": x["label"], "label": x["label"], "kind": "other", "date": None, "url": x["url"]}
            for x in cv.get("correction_sources") or []]  # fmt: skip
    return {
        "id": f"council-{cv['id']}", "date": cv["date"], "kind": kind, "title": title, "detail": detail,
        "institution": "Council", "state": "done", "key": kind != "other", "docs": docs, "source": cv["source"],
        "vote_id": None,
    }  # fmt: skip


def urgency_vote(
    e: Event, votes: list[EpVote], indexed: set[str]
) -> tuple[str, str | None, dict | None, str | None] | None:
    """(title, detail, source, vote id) of an EP vote record ("Vote in Parliament", "Results of vote in
    Parliament") whose only votes on the file (`votes`) that day are on a request for urgent procedure, else None
    (2025/3502(COD), 16 Dec 2025: decision 182690 "Request for an urgent decision", adopted by show of hands)."""
    if e.kind != EventKind.plenary_vote or (e.raw_type or "").rsplit("/", 1)[-1] not in EP_VOTE_RECORDS:
        return None
    day = [v for v in votes if v.date == e.date and vote_held(v)]
    texts = [f"{v.title} {v.reference_text or ''}" for v in day]
    if not day or not all(URGENCY_RE.search(t) for t in texts):
        return None
    what = "an urgent decision" if all(re.search(r"urgent decision", t, re.I) for t in texts) else "urgent procedure"
    outcomes = {v.outcome for v in day}
    outcome = outcomes.pop() if len(outcomes) == 1 else ""
    title = {
        "adopted": f"Parliament approved the request for {what}",
        "rejected": f"Parliament rejected the request for {what}",
    }.get(outcome, f"Parliament voted on a request for {what}")
    v = day[0]
    detail = None
    if len(day) == 1 and v.n_for is not None:
        detail = f"{v.n_for} in favour, {v.n_against or 0} against, {v.n_abstain or 0} abstentions"
    elif len(day) == 1 and v.method == "VOTE_HAND":
        detail = "By show of hands"
    return title, detail, _src(v.source), v.id if len(day) == 1 and v.id in indexed else None


def commission_cod_proposal(p: Procedure) -> bool:
    """An ordinary legislative procedure whose recorded proposal is the Commission's: the Legislative
    Observatory's "Legislative proposal published" key event, with its COM document and no document of another
    initiator (the initiatives of Member States, the ECB or the Court under Art. 294(15) TFEU are recorded with
    their own document, e.g. 2010/0817(COD) 09288/2010, 2022/0906(COD) the Court's request 07307/2022)."""
    props = [e for e in p.events if e.kind == EventKind.proposal]
    docs = [d.id for e in props for d in e.docs]
    return (
        p.type == "COD"
        and any(e.institution == "Commission" and (e.raw_type or "").startswith("oeil:") for e in props)
        and bool(docs)
        and all(d.startswith("COM(") for d in docs)
    )


def court_request(p: Procedure) -> bool:
    """An ordinary legislative procedure whose recorded proposal is the Court of Justice's request (Art. 281 TFEU,
    second paragraph; Art. 294(15)), as OEIL's documentation gateway lists it, with no COM document: 2022/0906(COD),
    "CJEC | Legislative proposal | 07307/2022"; 2015/0906(COD), N8-0110/2015 (OEIL_PROPOSAL_AUTHORS)."""
    props = [e for e in p.events if e.kind == EventKind.proposal]
    return (
        p.type == "COD"
        and not p.com_refs
        and bool(props)
        and all(
            e.institution == "CJEU" or any(OEIL_PROPOSAL_AUTHORS.get(d.id, ("", ""))[1] == "CJEU" for d in e.docs)
            for e in props
        )
    )


def council_assessment(a: dict | None) -> dict | None:
    """pipeline.analysis.council_qmv.CouncilAssessment -> CouncilAssessment in src/types/data.ts."""
    if not a:
        return None
    notes = a.get("notes") or ([a["note"]] if a.get("note") else [])
    return {
        "rule": a.get("rule"),
        "states_for": a.get("states_for"),
        "states_required": a.get("states_required"),
        # set by Builder.council_rule_assessment when the legal basis is not established (72% variant)
        "states_required_alt": a.get("states_required_alt"),
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
        # Member States taking part; thresholds and population shares are computed over these only.
        "states_participating": a.get("participating"),
        # Minimum size of a blocking minority under the applicable rule (4 under TEU Art. 16(4); computed
        # under TFEU Art. 238(3)(a)); None where no such clause applies or the legal basis is not established.
        "blocking_minority_min_states": a.get("blocking_minority_min_states"),
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


def proposed_instrument(p: Procedure) -> str | None:
    """The type of act proposed, as the OEIL procedure file records it ("Legislative instrument"). Checked on
    2026-10-23: it names the same type as the English title of the Commission proposal in Cellar for all 257 files
    without a linked act that have both (e.g. 2023/0085(COD), COM(2023) 166 "Proposal for a DIRECTIVE ...")."""
    v = (p.instrument or "").strip().lower()
    return v if v in ("regulation", "directive", "decision", "recommendation") else None


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


# Council voting-result documents name each item by its full legal form before the subject, often in capitals.
_CV_FORM_AHEAD = r"(?=(?:council\s+)?(?:implementing\s+|delegated\s+)?(?:regulation|directive|decision)\b)"
_CV_POSITION = re.compile(
    r"^position\s+of\s+the\s+council\s+at\s+first\s+reading\s+(?:with|in)\s+a\s+view\s+to\s+(?:the\s+)?"
    r"adoption\s+of\s+(?:an?\s+|the\s+)?" + _CV_FORM_AHEAD,
    re.IGNORECASE,
)
_CV_PROPOSAL = re.compile(r"^(?:amended\s+)?proposal\s+for\s+an?\s+" + _CV_FORM_AHEAD, re.IGNORECASE)
_CV_FORM = re.compile(
    r"^(?P<form>(?:council\s+)?(?:implementing\s+|delegated\s+)?(?:regulation|directive|decision))\b"
    r"(?P<joint>\s+(?:of\s+)?the\s+european\s+parliament\s+and\s+(?:of\s+)?the\s+council\b"
    # "... of the Council Council establishing": a doubled word in the published title
    r"(?:\s+council\b(?!\s+(?:implementing\s+|delegated\s+)?(?:regulation|directive|decision)\b))?)?",
    re.IGNORECASE,
)


def council_display_title(title: str, vote_on: str | None = None) -> str:
    """Shorter title for lists of Council votes; the official title itself is always kept as well.

    Deterministic rules, applied only at the start of the title:
      - "of the European Parliament and of the Council" after the kind of act is dropped, and a kind of act
        written in capitals is written normally: "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL on X"
        -> "Regulation on X", "COUNCIL DIRECTIVE amending Y" -> "Council Directive amending Y". The kind of
        act (regulation, directive, decision; Council-only or not) is kept: it is information.
      - a leading "Proposal for a" before the kind of act is dropped;
      - "Position of the Council at first reading with a view to the adoption of a" is dropped only when the
        vote is recorded as being on that position (vote_on), which lists show separately;
      - a legal form printed twice in a row, or a doubled "Council", counts as one.
    Anything else, or a title that would keep fewer than two words after the kind of act, is returned as
    published (with runs of whitespace collapsed)."""
    official = re.sub(r"\s+", " ", (title or "").strip())
    t = official
    if vote_on == "first_reading_position":
        t = _CV_POSITION.sub("", t, count=1)
    t = _CV_PROPOSAL.sub("", t, count=1)
    m = _CV_FORM.match(t)
    if not m:
        return official
    rest = t[m.end() :].strip()
    again = _CV_FORM.match(rest)  # the whole legal form printed twice
    if m.group("joint") and again and again.group("joint") and again["form"].lower() == m["form"].lower():
        rest = rest[again.end() :].strip()
    if len(rest.split()) < 2:
        return official
    form = re.sub(r"\s+", " ", m.group("form"))
    if form.isupper():
        form = " ".join(w.capitalize() for w in form.split())
    return f"{form[:1].upper()}{form[1:]} {rest}"


_CV_ACT_ADOPTION = re.compile(r"^Adoption\s+of\s+(?:the\s+|a\s+)?legi\w*\s+act$", re.I)


# The item of a separate vote on derogating from the eight-week period (COUNCIL_DEROGATION_RE), as shown
COUNCIL_DEROGATION_ITEM = (
    "Derogation from the eight-week period for national parliaments (Article 3(3) of the Council’s Rules of Procedure)"
)


def council_vote_items(title: str, vote_on: str | None, stage: str | None, refs: list[str] | None = None) -> str | None:
    """The item(s) a vote on another item than an act or the Council's first-reading position was on, as the
    voting-result document's subject lists them (`vote_on_label`): "Non-approval of the European Parliament's
    amendment(s)" (ST 14700/26). A separate vote on derogating from the eight-week period (ST 8160/20, whose subject
    lists "Adoption of the legislative act" first; ST 8159/20 adopted the act) is named as that derogation. In the
    budget procedure (a budget title or a BUD reference) "Adoption of the legislative act", which some notes add
    (ST 14735/24, 10354/25), is left out: the Council's vote there does not by itself adopt the budget, which
    Parliament and the Council establish together (Art. 314(1) TFEU) and the President of Parliament declares
    adopted (Art. 314(9)). None when no item remains."""
    if vote_on != "other" or not stage:
        return None
    if COUNCIL_DEROGATION_RE.search(stage):
        return COUNCIL_DEROGATION_ITEM
    items = [i.strip() for i in stage.split(";") if i.strip()]
    if re.search(r"\bbudget\b", title, re.I) or any(r.endswith("(BUD)") for r in refs or []):
        items = [i for i in items if not _CV_ACT_ADOPTION.match(i)]
    return "; ".join(items) or None


def council_vote_label(title: str, vote_on: str | None, stage: str | None, refs: list[str] | None = None) -> str:
    """Title for lists of Council votes (country pages, activity): council_display_title, and for a vote on another
    item than an act or the Council's first-reading position, the item(s) voted on (council_vote_items), so that a
    Member State's "For" reads as support for that item: "Amendments of the European Parliament to the Council's
    position on the draft budget for 2027 – Non-approval of the European Parliament's amendment(s)" (ST 14700/26)."""
    t = council_display_title(title, vote_on)
    items = council_vote_items(title, vote_on, stage, refs)
    return f"{t} – {items}" if items else t


# ------------------------------------------------------------------------------------------- curated
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_act_dates(curated: Path = CURATED) -> dict[str, dict]:
    """Checked corrections to EUR-Lex act dates (data/curated/act_dates.yaml), by CELEX. Entries with a
    malformed date are skipped whole: a partial correction would be worse than none."""
    raw = _load_yaml("act_dates.yaml", curated) or []
    out: dict[str, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("celex"), str):
            continue
        app = e.get("application")
        ok = app is None or (isinstance(app, list) and all(isinstance(x, dict) for x in app))
        dates = ([e["entry_into_force"]] if e.get("entry_into_force") else []) + [x.get("date") for x in app or []]
        if not ok or not all(isinstance(d, str) and ISO_DATE_RE.match(d) for d in dates):
            log.warning("curated act_dates.yaml: entry %s has a malformed date; ignored", e["celex"])
            continue
        n_src = max(len(e.get("sources") or []), 1)  # a date's own source: an index into sources
        if not all(type(x.get("source", 0)) is int and 0 <= x.get("source", 0) < n_src for x in app or []):
            log.warning("curated act_dates.yaml: entry %s cites a source it does not list; ignored", e["celex"])
            continue
        out[e["celex"]] = e
    return out


def apply_act_dates(a: LegalAct, e: dict | None) -> LegalAct:
    """The act with the curated dates in place of Cellar's (see load_act_dates)."""
    if not e:
        return a
    upd: dict[str, Any] = {}
    if e.get("entry_into_force"):
        upd |= {"entry_into_force": e["entry_into_force"], "entry_into_force_pending": False}
    if e.get("application") is not None:
        eif = upd.get("entry_into_force", a.entry_into_force)
        items = [x for x in e["application"] if x["date"] != eif]
        upd["other_application_dates"] = sorted({x["date"] for x in items})
        upd["partial_application_dates"] = sorted({x["date"] for x in items if x.get("partial")})
        upd["partial_on_entry_into_force"] = False  # a checked date on that day names its provisions instead
        upd["application_unrecorded"] = []  # the checked dates are the act's dates, incl. one EUR-Lex lacks
    return a.model_copy(update=upd)


CELEX_RE = re.compile(r"^3\d{4}[A-Z]{1,2}\d{4}$")


def load_act_relations(curated: Path = CURATED) -> list[dict]:
    """Checked corrections of the amendment links EUR-Lex records (data/curated/act_relations.yaml); an entry
    without the three CELEX ids or its evidence is skipped."""
    raw = _load_yaml("act_relations.yaml", curated) or []
    out = []
    for e in raw if isinstance(raw, list) else []:
        ids = isinstance(e, dict) and all(isinstance(e.get(k), str) and CELEX_RE.match(e[k]) for k in ("act", "replace", "with"))
        if ids and isinstance(e.get("evidence"), str) and e["evidence"].strip():
            out.append(e)
        else:
            log.warning("curated act_relations.yaml: malformed entry %r; ignored", e)
    return out


def apply_act_relations(acts: list[LegalAct], fixes: list[dict]) -> list[LegalAct]:
    """The acts with each curated link in place of Cellar's, in both directions (see load_act_relations): only while
    Cellar still links the act to `replace` (validate.py reports an entry that no longer matches)."""
    by_celex = {a.celex: a for a in acts}
    live = [f for f in fixes if f["act"] in by_celex and f["replace"] in by_celex[f["act"]].amends]
    out = []
    for a in acts:
        amends, amended_by = set(a.amends), set(a.amended_by)
        for f in live:
            if a.celex == f["act"]:
                amends = (amends - {f["replace"]}) | {f["with"]}
            if a.celex == f["with"]:
                amended_by.add(f["act"])
            if a.celex == f["replace"]:
                amended_by.discard(f["act"])
        if (sorted(amends), sorted(amended_by)) != (a.amends, a.amended_by):
            a = a.model_copy(update={"amends": sorted(amends), "amended_by": sorted(amended_by)})
        out.append(a)
    return out


def act_date_source(e: dict, d: str) -> dict | None:
    """The text a curated act_dates entry cites for date d: the date's own source (e.g. the amending act
    that set it), else the entry's first source."""
    srcs = e.get("sources") or []
    item = next((x for x in e.get("application") or [] if x["date"] == d), {})
    s = srcs[item.get("source", 0)] if item.get("source", 0) < len(srcs) else None
    return s if isinstance(s, dict) else None


# Treaty provisions under which the Council acts unanimously, quoted from the Treaty (Cellar 12016E019,
# 12016E081, 12016E312). Only these can replace a voting sheet's "qualified majority" (data/curated/council_votes.yaml).
UNANIMITY_BASES: dict[str, str] = {
    "TFEU Art. 19(1)": "the Council, acting unanimously in accordance with a special legislative procedure and after "
    "obtaining the consent of the European Parliament, may take appropriate action to combat discrimination",
    "TFEU Art. 81(3)": "measures concerning family law with cross-border implications shall be established by the "
    "Council, acting in accordance with a special legislative procedure. The Council shall act unanimously after "
    "consulting the European Parliament",
    "TFEU Art. 312(2)": "The Council shall act unanimously after obtaining the consent of the European Parliament",
}


def load_council_votes(curated: Path = CURATED) -> tuple[dict[str, dict], list[CouncilVote], dict[str, str]]:
    """Checked Council vote corrections and records (data/curated/council_votes.yaml): corrections by vote id,
    the records, and each record's note. An entry that does not validate is skipped whole."""
    raw = _load_yaml("council_votes.yaml", curated)
    raw = raw if isinstance(raw, dict) else {}
    corrections: dict[str, dict] = {}
    for e in raw.get("corrections") or []:
        if not isinstance(e, dict) or not isinstance(e.get("vote"), str):
            continue
        if e.get("legal_basis") not in UNANIMITY_BASES or not e.get("citation"):
            log.warning("curated council_votes.yaml: %s has no listed unanimity legal basis; ignored", e["vote"])
            continue
        if e.get("outcome") not in (None, "not_adopted") or (e.get("outcome") and not e.get("outcome_note")):
            log.warning("curated council_votes.yaml: %s has an unsupported outcome; ignored", e["vote"])
            continue
        srcs = e.get("sources")
        if not isinstance(srcs, list) or not srcs or not all(
            isinstance(x, dict) and isinstance(x.get("label"), str) and str(x.get("url") or "").startswith("https://")
            for x in srcs
        ):  # the texts checked are shown with the correction (`correction_sources`)
            log.warning("curated council_votes.yaml: %s lists no texts it was checked against; ignored", e["vote"])
            continue
        corrections[e["vote"]] = e
    records: list[CouncilVote] = []
    notes: dict[str, str] = {}
    for e in raw.get("records") or []:
        try:
            cv = CouncilVote.model_validate({k: v for k, v in e.items() if k not in ("note", "reviewed")})
        except (ValidationError, AttributeError, TypeError):
            log.warning("curated council_votes.yaml: record %r invalid; ignored", e)
            continue
        records.append(cv)
        notes[cv.id] = str(e.get("note") or "").strip()
    return corrections, records, notes


def council_rule_note(e: dict) -> str:
    """What a vote's sheet prints and why the rule shown is unanimity (a council_votes.yaml correction)."""
    article = e["legal_basis"].removeprefix("TFEU ").replace("Art.", "Article")
    return (
        "The Council's voting-result document labels the voting rule “qualified majority”. The act is based on "
        f"{article} of the Treaty on the Functioning of the European Union (“{e['citation']}”), under which the "
        f"Council acts unanimously: “{UNANIMITY_BASES[e['legal_basis']]}”. The rule is shown here as unanimity."
    )


def load_transposition_checks(curated: Path = CURATED) -> dict[str, dict]:
    """Directives' general transposition deadlines checked against their text (data/curated/transposition.yaml),
    by CELEX. Entries with a malformed date are skipped."""
    raw = _load_yaml("transposition.yaml", curated) or []
    out: dict[str, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("celex"), str):
            continue
        dates = [e.get("deadline")] + ([e["applies_from"]] if e.get("applies_from") else []) + list(e.get("other") or [])
        if not all(isinstance(d, str) and ISO_DATE_RE.match(d) for d in dates):
            log.warning("curated transposition.yaml: entry %s has a malformed date; ignored", e["celex"])
            continue
        if e.get("amends") is not None and not _amends_ok(e["amends"]):
            log.warning("curated transposition.yaml: entry %s has a malformed amends list; ignored", e["celex"])
            e = {k: v for k, v in e.items() if k != "amends"}
        ex = e.get("exemption")
        if ex is not None and not (
            isinstance(ex, dict) and all(isinstance(ex.get(k), str) and ex[k] for k in ("provision", "quote"))
            and all(isinstance(ex.get(k) or [], list) and set(ex.get(k) or []) <= set(MEMBER_STATES)
                    for k in ("countries", "named"))
            and isinstance(ex.get("country_note") or "", str)
        ):  # fmt: skip
            log.warning("curated transposition.yaml: entry %s has a malformed exemption; ignored", e["celex"])
            e = {k: v for k, v in e.items() if k != "exemption"}
        if not isinstance(e.get("exceptions") or "", str):
            log.warning("curated transposition.yaml: entry %s has malformed exceptions; ignored", e["celex"])
            e = {k: v for k, v in e.items() if k != "exceptions"}
        if e.get("application_exceptions") and not (isinstance(e["application_exceptions"], str) and e.get("applies_from")):
            # they qualify the general date from which the national measures apply, which the entry must name
            log.warning("curated transposition.yaml: entry %s has application_exceptions without applies_from; ignored",
                        e["celex"])  # fmt: skip
            e = {k: v for k, v in e.items() if k != "application_exceptions"}
        out[e["celex"]] = e
    return out


def _amends_ok(items: Any) -> bool:
    """transposition.yaml `amends`: [{celex, provision, deadline, further: [{date, provisions}]}]."""
    def dated(x: Any, *keys: str) -> bool:
        return isinstance(x, dict) and all(isinstance(x.get(k), str) and x[k] for k in keys) and bool(
            ISO_DATE_RE.match(x.get("deadline") or x.get("date") or ""))  # fmt: skip

    return isinstance(items, list) and all(
        dated(x, "celex", "provision", "deadline")
        and isinstance(x.get("further") or [], list)
        and all(dated(f, "date", "provisions") for f in x.get("further") or [])
        for x in items
    )


def apply_transposition_checks(a: LegalAct, e: dict | None) -> LegalAct:
    """The act with its checked transposition dates (see load_transposition_checks); an entry naming a date
    EUR-Lex does not record for the act is not applied (validate.py reports it)."""
    if not e or a.act_type != "directive":
        return a
    recorded = set(a.transposition_deadlines)
    if not {e["deadline"], e.get("applies_from") or e["deadline"], *(e.get("other") or [])} <= recorded:
        return a
    chk = entities.CheckedTransposition(
        deadline=e["deadline"], applies_from=e.get("applies_from"), other=list(e.get("other") or []),
        exceptions=_squash(e.get("exceptions")) or None,
        application_exceptions=_squash(e.get("application_exceptions")) or None,
    )
    return a.model_copy(update={"transposition_checked": chk})


def load_denmark_schengen(curated: Path = CURATED) -> dict[str, dict]:
    """Denmark's decisions under Article 4 of Protocol No 22 on directives building upon the Schengen acquis
    (data/curated/denmark_schengen.yaml), by CELEX. An entry without its decision, date or document is skipped."""
    raw = _load_yaml("denmark_schengen.yaml", curated) or []
    out: dict[str, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        ok = isinstance(e, dict) and isinstance(e.get("celex"), str) and e.get("decision") in ("implement", "not_implement")
        if ok and ISO_DATE_RE.match(str(e.get("notified") or "")) and all(isinstance(e.get(k), str) for k in ("document", "url")):
            out[e["celex"]] = e
        else:
            log.warning("curated denmark_schengen.yaml: malformed entry %r; ignored", e)
    return out


def load_council_dates(curated: Path = CURATED) -> dict[str, dict]:
    """The Council's adoption of an act dated by the act's own text (data/curated/council_dates.yaml), by
    normalized procedure reference. An entry whose date is malformed or not the one its quote gives is skipped."""
    raw = _load_yaml("council_dates.yaml", curated) or []
    out: dict[str, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("procedure"), str) or not isinstance(e.get("celex"), str):
            continue
        d = e.get("date")
        if not (isinstance(d, str) and ISO_DATE_RE.match(d)) or f"Council of {_long_date(d)}" not in re.sub(
            r"Council decision of", "Council of", _squash(e.get("quote"))
        ):
            log.warning("curated council_dates.yaml: entry %s does not quote its date; ignored", e["procedure"])
            continue
        out[norm_ref(e["procedure"])] = e
    return out


def load_unlinked_acts(curated: Path = CURATED) -> dict[str, dict]:
    """Acts whose text cites a file's steps but which no official record links to the file
    (data/curated/unlinked_acts.yaml), by normalized procedure reference. An entry whose dates are malformed, or
    whose quote does not give the date of Parliament's opinion, is skipped."""
    raw = _load_yaml("unlinked_acts.yaml", curated) or []
    out: dict[str, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("procedure", "celex", "label")):
            continue
        dates = [e.get(k) for k in ("date", "published", "opinion")]
        if not all(isinstance(d, str) and ISO_DATE_RE.match(d) for d in dates) or (
            f"Opinion of {_long_date(e['opinion'])}" not in _squash(e.get("quote"))
        ):
            log.warning("curated unlinked_acts.yaml: entry %s does not quote its dates; ignored", e["procedure"])
            continue
        out[norm_ref(e["procedure"])] = e
    return out


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
        self.notices = _load("eurlex", "procedure_notices", ProcedureNotice, i, root)
        self.optouts = _load("optouts", "directives", DirectiveOptOut, i, root)

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
        self.act_relations = load_act_relations(curated)
        if self.act_relations:  # amendment links checked against the amending act's text
            snap.acts = apply_act_relations(snap.acts, self.act_relations)
        self.act_dates = load_act_dates(curated)
        if self.act_dates:
            snap.acts = [apply_act_dates(a, self.act_dates.get(a.celex)) for a in snap.acts]
        self.council_fixes, self.council_extra, self.council_extra_notes = load_council_votes(curated)
        self.transposition_checks = load_transposition_checks(curated)
        if self.transposition_checks:
            snap.acts = [apply_transposition_checks(a, self.transposition_checks.get(a.celex)) for a in snap.acts]
        self.council_dates = load_council_dates(curated)
        self.unlinked_acts = load_unlinked_acts(curated)
        self.denmark_schengen = load_denmark_schengen(curated)
        self.files: dict[str, Any] = {}
        self._index()

    # ---------------------------------------------------------------- indexes
    def _index(self) -> None:
        s = self.s
        self.org = {o.id: o for o in s.orgs}
        # the name is shown as not recorded, and the records are left out of the parties list and search
        self.unnamed_parties = unnamed_parties(s.orgs)
        for oid in self.unnamed_parties:
            self.org[oid] = self.org[oid].model_copy(update={"label": PARTY_NAME_MISSING})
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
        self.optouts = {o.celex: o for o in s.optouts if o.status == "ok"}
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

    def not_participating(self, celex: str, country: str) -> CouncilVote | DirectiveOptOut | None:
        """The record showing that `country` did not take part in adopting this act and is not bound by it:
        the directive's own recitals (Protocols 21 / 22), else the Council's voting result; None if neither."""
        oo = self.optouts.get(celex)
        if oo and country in oo.opted_in:  # took part after adoption (Protocol No 21, Article 4)
            return None
        if oo and country in oo.not_bound:
            return oo
        for ref in self.act_refs.get(celex, []):
            countries, cv = self.not_participating_by_ref.get(ref, (set(), None))
            if country in countries:
                return cv
        return None

    def known_as(self, p: Procedure, acts: list[LegalAct]) -> dict | None:
        """What the file is called besides its title: the number of each act it produced and verified common
        names (official short titles in the procedure's and the acts' titles, aliases.yaml names with a cited
        source). featured.yaml `aliases` are search keywords ("ESG reporting"), not names, and are not shown."""
        if not hasattr(self, "_file_names"):
            self._file_names = curated_file_names(self)
            # a name given to several files is the name of a package ("Pact on Migration and Asylum")
            n_files = Counter(n.casefold() for names in self._file_names.values() for n in set(names))
            self._package_names = {n for n, k in n_files.items() if k > 1}
        numbers = [n for a in acts if (n := act_label(a)) != a.celex]
        names = short_names(p.title) + [n for a in acts if (n := act_short_name(a.title))]  # official first
        part_of = [n for n in self._file_names.get(p.id, []) if n.casefold() in self._package_names]
        # short names only: a descriptive phrase used as a search name ("EU ban on the sale of new petrol and
        # diesel cars from 2035") is not what the file is called
        names += [n for n in self._file_names.get(p.id, [])
                  if n.casefold() not in self._package_names and len(n.split()) <= 5]  # fmt: skip
        seen = [self.dossier_title(p).casefold()]
        unique = []
        for n in names:
            k = n.casefold()
            # the title or a name already listed says it ("EU AI Act" after "AI Act")
            if not any(k in t or (t in k and t != seen[0]) for t in seen):
                seen.append(k)
                unique.append(n)
        out = {"acts": numbers[:4], "names": unique[:2], "part_of": part_of[:1]}
        return out if numbers or unique or part_of else None

    def participation_recorded(self, celex: str, country: str) -> bool:
        """Whether a record settles if `country` is bound by the act: the directive's recitals were read
        (they name every opt-out), or a Council voting result on it gives the country's position."""
        if celex in self.optouts:
            return True
        return any(country in cv.positions for r in self.act_refs.get(celex, [])
                   for cv in [self.not_participating_by_ref.get(r, (set(), None))[1]] if cv)  # fmt: skip

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

    def oeil_link(self, pid: str) -> str | None:
        """The procedure's OEIL file, or None where OEIL has none (see OEIL_NO_FILE; split parents)."""
        if pid in OEIL_NO_FILE:
            return OEIL_NO_FILE[pid]
        return None if self.split_children.get(pid) else self.proc[pid].oeil_url

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

    def rapporteur_entries(self, p: Procedure) -> list[dict]:
        """A file's rapporteurs with the political group they held in that role, never their current group:
        their group membership on the date the EP API gives for the appointment, else the group the OEIL file
        prints next to the name (older files). Left out when neither establishes it (memberships start July 2019)."""
        familiar = _lazy("pipeline.sources.ep_people", "GROUP_CODES") or {}
        out = []
        for r in p.rapporteurs:
            m = self.mep.get(r.mep_id or "")
            slug = code = None
            gid = self.group_at(m.id, r.date) if m and r.date else None
            if gid:
                o = self.org.get(gid)
                slug, code = self.org_slug.get(gid), (o.code or o.label) if o else None
            elif r.group:
                code = familiar.get(r.group, r.group)  # "PPE" -> "EPP", "Verts/ALE" -> "Greens/EFA"
                slug = group_slug(code) if group_slug(code) in self.group_orgs else None
            out.append({
                "mep_id": r.mep_id, "name": r.name, "group": slug, "group_code": code,
                "country": m.country if m else None, "role": r.role, "committee": r.committee,
                **({"former": True} if r.former else {}),
            })  # fmt: skip
        return out

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
            # R / M suffixes are Parliament reports on the procedure, not parts of a split procedure
            if m and m.group(1) in pids and not PARLIAMENT_REPORT_RE.fullmatch(pid):
                self.split_children[m.group(1)].append(pid)
        for celex, ds in act_dossiers.items():
            for parent, children in self.split_children.items():
                if parent in ds and any(c in claimed_by[celex] for c in children):
                    ds.discard(parent)
        # Where EUR-Lex and the EP disagree on which procedure adopted an act, the EP's final-act list wins: Cellar
        # links Regulation (EU) No 37/2014 to 2011/0153 and No 38/2014 to 2011/0039, while OEIL gives the reverse,
        # as the acts' titles do. A EUR-Lex link is dropped only when another procedure claims the act and the
        # linked procedure lists its own, different, final acts.
        for celex, ds in act_dossiers.items():
            for pid in sorted(ds - claimed_by[celex]):
                if claimed_by[celex] and self.proc[pid].celex_refs:
                    log.info("act %s: EUR-Lex names %s, the EP gives %s; kept on the EP's", celex, pid,
                             ", ".join(sorted(claimed_by[celex])))  # fmt: skip
                    ds.discard(pid)
        # a split parent known only from EUR-Lex was built from one part's act (Regulation (EU) 2017/2393 is part
        # B of 2016/0282): name it by the split instead of by that act's title
        for parent, children in self.split_children.items():
            if parent in self.stub_ids:
                p = self.proc[parent]
                parts = " and ".join(self.proc[c].reference for c in children)
                self.proc[parent] = p.model_copy(update={"title": f"Proposal {p.reference}, split into {parts}"})
        self.procedures = [self.proc[p.id] for p in self.procedures]
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
        # a Train page on one part of a split proposal, which records the proposal's reference ("New alignment of
        # regulatory procedure with scrutiny (RPS) measures - 2016/0400B(COD)", procedure 2016/0400(COD)), is that
        # part's, not the proposal's
        for parent, children in self.split_children.items():
            for t in self.train_of.get(parent, []):
                part = next((c for c in children if self.proc[c].reference in t.title), None)
                if part:
                    self.train_of[parent] = [x for x in self.train_of[parent] if x is not t]
                    self.train_of[part] = sorted([*self.train_of.get(part, []), t], key=lambda x: x.url)

    def vote_dossiers(self, v: EpVote) -> list[str]:
        out = {p.id for r in v.procedure_refs if (p := self.resolve_ref(r))}
        return sorted(out)

    def parent_negotiation_votes(self, p: Procedure) -> list[EpVote]:
        """For a split part: the votes of the file it was split from on the committee's decision to negotiate, held on
        the day of the part's own confirmation of that decision (ENDORSE_NEGOTIATIONS_EVENT) on a report among the part's
        documents. 2023/0077A(COD): confirmation of 14 Sep 2023, vote 158371 (366-186-18) on A9-0255/2023, which
        Parliament's records file under 2023/0077(COD)."""
        m = re.fullmatch(r"(\d{4}-\d{4})[A-Z]", p.id)
        days = {e.date for e in p.events if e.raw_type == ENDORSE_NEGOTIATIONS_EVENT}
        if not m or not days:
            return []
        docs = {d.id for d in p.documents} | {d.id for e in p.events for d in e.docs}
        own = {v.id for v in self.votes_of.get(p.id, [])}
        return [
            v for v in self.votes_of.get(m.group(1), [])
            if v.kind_detail == "negotiation_decision" and v.date in days and v.id not in own
            and docs & (vote_label_doc_ids(v) | {x.split("-AM-")[0] for x in v.doc_ids})
        ]  # fmt: skip

    # ---------------------------------------------------------------- titles/topics
    def adopted_title(self, p: Procedure) -> str | None:
        """The official title of the file's one adopted act (EUR-Lex), where the procedure's own title does not
        describe it (title_misfit): e.g. "Extending Directive [XXXX] to ..." for Directive (EU) 2024/2842."""
        acts = self.acts_of.get(p.id, [])
        if len(acts) != 1 or self.act_dossiers.get(acts[0].celex) != {p.id}:
            return None
        return acts[0].title if title_misfit(p.title, acts[0].title) else None

    def dossier_title(self, p: Procedure) -> str:
        cur = self.curated_of.get(p.id)
        if cur and cur.get("short_title"):
            return str(cur["short_title"])
        title = self.adopted_title(p) or p.title
        names = short_names(title)
        return names[0] if names else clean_title(title)

    def related_act_title(self, celex: str, pid: str | None, topic: bool = False) -> str:
        """A related act by its number ('Directive (EU) 2025/794'), followed by its file's short title when it
        has one (curated, or an official short name) or, with topic, by its file's title unless that is a
        run-on 'Amending …' title. Its file's title, or its CELEX id, when no number is known."""
        a = self.act.get(celex)
        label = act_label(a) if a and act_label(a) != celex else celex_act_label(celex)
        title = self.dossier_summary[pid]["title"] if pid else None
        if not label:
            return _truncate(title, 160) if title else f"Act {celex} (EUR-Lex)"
        named = pid and ((self.curated_of.get(pid) or {}).get("short_title") or short_names(self.proc[pid].title))
        if title and (named or (topic and not title.startswith("Amending"))):
            return f"{label} ({_truncate(_squash(title), 120)})"
        return label

    def topics_for(self, p: Procedure) -> list[str]:
        out: set[str] = set()
        codes = [s.code for s in p.subjects if s.scheme == "ep"]

        def under(code: str, pref: str) -> bool:
            pref = pref.strip().rstrip(".")
            return code == pref or code.startswith(pref + ".")

        for slug, t in self.topics_cur.items():
            excluded = _as_list(t.get("ep_subjects_exclude"))
            if any(under(c, pref) and not any(under(c, x) for x in excluded)
                   for pref in _as_list(t.get("ep_subjects")) for c in codes):  # fmt: skip
                out.add(slug)
        cur = self.curated_of.get(p.id)
        # a curated file's own topics come first, in their curated order: the first is the one its card shows
        first = [t for t in _as_list((cur or {}).get("topics")) if t in self.topics_cur or not self.topics_cur]
        return list(dict.fromkeys(first)) + sorted(out - set(first))

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
        # votes on whole texts with roll-call results, every final / mandate vote linked to a procedure, and
        # the votes on a committee's decision to enter into negotiations; never a vote that was not held
        decisive = ("final", "mandate")
        idx = [
            v
            for v in s.votes
            if vote_held(v)
            and (
                (v.has_ballots and (v.kind in (*decisive, "resolution", "motion") or v.kind_detail))
                or (
                    (v.kind in decisive or v.kind_detail == "negotiation_decision")
                    and self.vote_dossier_map.get(v.id)
                )
            )
        ]
        idx.sort(key=lambda v: (v.date, v.id), reverse=True)
        self.indexed_votes = idx
        self.indexed_vote_ids = {v.id for v in idx}
        self.votes_from = idx[-1].date if idx else "9999"  # the first vote listed (meta scope "ep_votes_from")
        self.referred_back = referred_back(s.votes)
        self.component_cache: dict[str, int | None] = {}
        margin_fn = _lazy("pipeline.analysis.ep_margin", "margin")
        self.vote_summary: dict[str, dict] = {}
        self.group_votes: dict[str, list[dict]] = defaultdict(list)
        self.mep_votes: dict[str, list[dict]] = defaultdict(list)
        for v in idx:
            summ = self.ep_vote_summary(v, margin_fn)
            self.vote_summary[v.id] = summ
        self.distinguish_vote_titles(idx)
        for v in idx:
            det = self.ep_vote_detail(v)
            self.files[f"votes/{v.id}.json"] = det
        self.files["votes/index.json"] = [_vote_index_entry(self.vote_summary[v.id]) for v in idx]

    def members_in_office(self, d: str) -> int:
        """MEPs whose political-group membership (non-attached included) covers day `d` in the EP's
        membership records (ep_people)."""
        return sum(1 for spans in self.mep_groups.values() if any(_valid_on(a, b, d) for a, b, _ in spans))

    def component_members(self, d: str) -> int | None:
        """Number of component Members for majority rules: the Members in office on the day of the vote.

        Parliament counts the Members actually in office, not the statutory seats: for the election of the
        Commission President on 18 July 2024 its press service gave "Parliament is currently composed of 719
        MEPs, so the necessary majority was 360 votes" (720 seats). The count comes from the membership
        records (members_in_office) and is used only when it is plausible against the statutory number of
        seats in pipeline.analysis.ep_margin (at most that number, at least 95% of it); otherwise None, and
        margins that need it are not computed. None also on the days of MEMBERS_COUNT_UNKNOWN."""
        if any(a <= d <= b for a, b in MEMBERS_COUNT_UNKNOWN):
            return None
        if d not in self.component_cache:
            seats_fn = _lazy("pipeline.analysis.ep_margin", "statutory_seats")
            seats = seats_fn(d) if seats_fn else None
            n = self.members_in_office(d) if seats else 0
            self.component_cache[d] = n if seats and seats * 0.95 <= n <= seats else None
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
                    if m["rule"] != "votes_cast" and isinstance(m.get("component_members"), int):
                        margin["component_members"] = m["component_members"]
                    if m["rule"] == "two_thirds_cast" and isinstance(m.get("two_thirds_of_cast"), int):
                        # both conditions of Art. 234 / 354 TFEU, so the page can state each (179569: 372 and 360)
                        margin |= {k: m[k] for k in ("votes_cast", "two_thirds_of_cast", "majority_of_members")}
            except Exception as e:  # noqa: BLE001
                log.debug("margin failed for %s: %r", v.id, e)
        refs = sorted(set(v.procedure_refs))
        proc_ref = p.reference if p else (refs[0] if len(refs) == 1 else None)
        display, from_label = self.vote_display_title(v, p)
        # French passages of a title that is Parliament's own label, for lang="fr" (omitted when none)
        parts = label_parts(display) if from_label else None
        role = final_role(v)
        return {
            "id": v.id,
            "date": v.date,
            "title": v.title,
            "display_title": display,
            **({"display_title_parts": parts} if parts else {}),
            "kind": v.kind,
            "kind_detail": v.kind_detail,
            "kind_label": VOTE_DETAIL_LABELS.get(v.kind_detail or "") or FINAL_ROLE_LABELS.get(role or "")
            or VOTE_KIND_LABELS.get(v.kind, "Vote"),
            "final_role": role,
            "outcome": v.outcome,
            "outcome_basis": getattr(v, "outcome_basis", None),
            "outcome_note": VOTE_OUTCOME_NOTES.get((v.kind_detail or "", v.outcome))
            or " ".join(x for x in (self.later_act_note(v, p), self.referral_note(v)) if x)
            or (discharge_note(v) if role == "discharge" or v.kind_detail in DISCHARGE_PROPOSED else None),
            "for": n_for,
            "against": n_against,
            "abstain": n_abs,
            "dossier_id": did,
            "dossier_ref": p.reference if p else None,
            # the official procedure reference, also for procedures that are not tracked as legislative files
            "procedure_ref": proc_ref,
            # the published subject, for keyword search, when the titles above do not already say it
            "subject": search_subject(v.subject, display, v.title),
            "topics": self.topics_for(p) if p else [],
            "margin": margin,
            "has_ballots": bool(b is not None),
            "source": _src(v.source),
        }

    def referral_note(self, v: EpVote) -> str | None:
        """A final vote recorded as rejected, followed in the same sitting by an adopted referral of the file back to
        committee on the same document (Rule 59(4) of the 9th-term Rules of Procedure: "If the whole draft
        legislative act … fails to secure a majority of the votes cast, … Parliament decides to refer the matter
        back to the committee responsible for reconsideration"): ETS revision, 8 June 2022, 144283 then 144284."""
        if v.kind != "final" or v.outcome != "rejected" or v.id not in self.referred_back:
            return None
        return (
            "After this vote Parliament referred the file back to the committee responsible for reconsideration "
            "(Rule 59(4) of its Rules of Procedure)."
        )

    def later_act_note(self, v: EpVote, p: Procedure | None) -> str | None:
        """A final vote recorded as rejected, on a file whose Legislative Observatory record names a final
        act dated after the vote: the rejection did not end the file (2025/0429(COD): rejected at first reading
        on 26 March 2026, then Regulation (EU) 2026/1881 after the second reading)."""
        if p is None or v.kind != "final" or v.outcome != "rejected":
            return None
        later = sorted(
            (a for a in self.acts_of.get(p.id, []) if a.celex in p.celex_refs and (a.date_document or "") > v.date),
            key=lambda a: (a.date_document or "", a.celex),
        )
        if not later:
            return None
        return (
            "Parliament rejected the text in this vote, but the procedure continued: it later produced "
            f"{act_label(later[0])}."
        )

    def vote_display_title(self, v: EpVote, p: Procedure | None) -> tuple[str, bool]:
        """Readable title: the file's title (or the published subject of the vote) + what was voted, and
        whether it is Parliament's own label.

        Without a tracked file or an English subject, the English title of a French-English-German label
        (english_title) stands in for the subject; failing that, Parliament's own label, shortened."""
        phrase = (
            VOTE_DETAIL_PHRASE.get(v.kind_detail or "")
            or FINAL_ROLE_PHRASE.get(final_role(v) or "")
            or VOTE_KIND_PHRASE.get(v.kind, "vote")
        )
        if p is not None:
            display = f"{_truncate(self.dossier_title(p), 120)} — {phrase}"
            if v.kind in ("amendment", "split_or_separate") and v.reference_text:
                display += f" ({v.reference_text})"
            return display, False
        subject = vote_subject(v.subject) or english_title(v.title)
        if not subject:
            label = english_procedural(v.title) or v.title
            return re.sub(r"\s+[-–]…$", "…", _truncate(label, VOTE_LABEL_TITLE_MAX)), True
        # the subject already says what was voted: "Objection pursuant to Rule 114(3): …", "Motion of censure …",
        # "Decision to raise no objections pursuant to Rule 111(6): …"
        says_it = {
            "objection": r"^objection\b",
            "censure": r"\bcensure\b",
            "no_objection": r"\bno objections?\b|\bnot to (oppose|object)\b",
        }.get(v.kind_detail or "")
        if says_it and re.search(says_it, subject, re.I):
            return _truncate(subject, 200), False
        return f"{_truncate(subject, 160)} — {phrase}", False

    def distinguish_vote_titles(self, votes: list[EpVote]) -> None:
        """Votes of one day that would share a display title (competing motions for a resolution, several
        objections to one act, two motions to reject) get what tells them apart in their own label: the text
        voted on ("motion B9-0069/2020", "joint motion RC-B9-0073/2020"), else the amendment numbers, else the
        label's last part. One vote of the group may keep the bare title."""
        groups: dict[tuple[str, str], list[EpVote]] = defaultdict(list)
        for v in votes:
            groups[(v.date, self.vote_summary[v.id]["display_title"])].append(v)
        for (_day, title), group in groups.items():
            if len(group) < 2:
                continue
            for distinction in (vote_label_document, vote_label_amendments, vote_label_last):
                keys = [distinction(v) for v in group]
                found = [k for k in keys if k]
                if len(found) >= len(keys) - 1 and len(set(found)) == len(found):
                    for v, key in zip(group, keys, strict=True):
                        if key:
                            summ = self.vote_summary[v.id]
                            summ["display_title"] = f"{title} ({key})"
                            # what tells it apart, also on its own: lists that cut long titles show it unclamped
                            summ["distinction"] = key
                            if summ.get("display_title_parts"):
                                summ["display_title_parts"].append([None, f" ({key})"])
                    break

    def ep_vote_detail(self, v: EpVote) -> dict:
        summ = self.vote_summary[v.id]
        b = self.ballots.get(v.id) if v.has_ballots else None
        ballots: list[dict] = []
        intentions: list[dict] = []
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
            # MEPs with no recorded vote who stated afterwards how they had intended to vote
            for mid, it in intended.items():
                if mid in seen:
                    continue
                m = self.mep.get(mid)
                gid = self.group_at(mid, v.date)
                entry = {"mep": mid, "intended": it, "group": self.org_slug.get(gid) if gid else None,
                         "country": m.country if m else None}  # fmt: skip
                intentions.append(entry)
                names[mid] = m.name if m else mid
            intentions.sort(key=lambda x: (x["intended"], names.get(x["mep"], ""), x["mep"]))
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
        proc_ref = summ.get("procedure_ref")
        reference = english_procedural(v.reference_text)
        return {
            **summ,
            # the full label, cut into French / German passages for lang attributes (None: nothing to mark)
            "title_parts": label_parts(v.title),
            # the published subject without Parliament's procedure symbol, which subject_procedure gives in words
            "subject": vote_subject(v.subject),
            "subject_procedure": subject_procedure(v.subject),
            "procedure_url": f"{OEIL_PROCEDURE}{proc_ref}" if proc_ref else None,
            # Parliament's fixed French terms in English (english_procedural); any other French text is marked
            "reference_text": reference,
            **({"reference_text_lang": "fr"} if reference and _french_segment(reference) else {}),
            "majority_rule": v.majority_rule,
            "doc_ids": v.doc_ids,
            "attendees": v.attendees,
            "groups": gb,
            "countries": cb,
            "ballots": ballots,
            "intentions": intentions,
            "mep_names": dict(sorted(names.items())),
            "reconciliation": recon,
        }

    # ---------------------------------------------------------------- Council
    def build_council(self) -> None:
        assess = _lazy("pipeline.analysis.council_qmv", "assess")
        self.council_of: dict[str, list[dict]] = defaultdict(list)
        self.council_public: list[dict] = []
        # split parent -> its Council votes, now listed on the part whose act each vote adopted
        self.council_in_parts: dict[str, list[dict]] = defaultdict(list)
        for cv in sorted(self.s.council + self.council_extra, key=lambda c: (c.date, c.id), reverse=True):
            ds = sorted({p.id for r in cv.procedure_refs if (p := self.resolve_ref(r))})
            moved = {d: part for d in ds if (part := self.council_split_part(cv, d))}
            ds = sorted({moved.get(d, d) for d in ds})
            did = ds[0] if len(ds) == 1 else None
            p = self.proc.get(did) if did else None
            vote_on, vote_on_note = self.council_vote_on(cv, p)
            # a sheet's "qualified majority" where the act's legal basis requires unanimity (council_votes.yaml)
            fix = self.council_fixes.get(cv.id) if cv.voting_rule == "qmv" else None
            sheet = cv
            if fix:
                cv = cv.model_copy(update={"voting_rule": "unanimity", "outcome": fix.get("outcome") or cv.outcome})
            assessment = None
            if assess is not None and cv.voting_rule != "unknown" and cv.positions:
                try:
                    assessment = self.council_rule_assessment(assess, cv, p)
                except Exception as e:  # noqa: BLE001
                    log.warning("council assessment failed for %s: %r", cv.id, e)
            if fix and (assessment is None or assessment["adopted_by_rule"] != (cv.outcome == "adopted")):
                # the outcome must follow from the corrected rule; otherwise the sheet is shown as published
                log.warning("curated council_votes.yaml: %s does not agree with its positions; ignored", cv.id)
                fix, cv, assessment = None, sheet, None
                if assess is not None and cv.voting_rule != "unknown" and cv.positions:
                    try:
                        assessment = self.council_rule_assessment(assess, cv, p)
                    except Exception as e:  # noqa: BLE001
                        log.warning("council assessment failed for %s: %r", cv.id, e)
            if assessment and cv.voting_rule != "unanimity":
                assessment["single_state_veto_possible"] = False
            when, date_note = self.council_vote_date(cv, p, vote_on)
            rec = {
                "id": cv.id, "date": when, "title": cv.title,
                "display_title": council_vote_label(cv.title, vote_on, cv.stage, cv.procedure_refs), "dossier_id": did,
                "dossier_ref": p.reference if p else None, "configuration": cv.configuration,
                "stage": cv.stage, "vote_on": vote_on,
                "vote_on_label": council_vote_items(cv.title, vote_on, cv.stage, cv.procedure_refs),
                "vote_on_note": vote_on_note, "meeting": cv.meeting,
                "written_procedure": cv.written_procedure, "council_doc": cv.council_doc,
                "voting_rule": cv.voting_rule, "outcome": cv.outcome, "positions": dict(sorted(cv.positions.items())),
                "positions_note": cv.positions_note if not cv.positions else None,
                "assessment": assessment, "statements": cv.statements, "source": _src(cv.source),
            }  # fmt: skip
            if fix:
                rec |= {"sheet_voting_rule": sheet.voting_rule, "voting_rule_note": council_rule_note(fix)}
                if fix.get("outcome"):
                    rec |= {"sheet_outcome": sheet.outcome, "outcome_note": " ".join(fix["outcome_note"].split())}
                rec["correction_sources"] = [{"label": x["label"], "url": x["url"]} for x in fix["sources"]]
            if self.council_extra_notes.get(cv.id):
                rec["source_note"] = self.council_extra_notes[cv.id]
            if date_note:
                rec["date_note"] = date_note
            self.council_public.append(rec)
            for d in ds:
                self.council_of[d].append(rec)
            for parent, part in sorted(moved.items()):
                self.council_in_parts[parent].append(
                    {"id": cv.id, "date": cv.date, "dossier_id": part, "dossier_ref": self.proc[part].reference}
                )
        for recs in self.council_of.values():  # newest first; on one day, the vote adopting the act first (stable)
            recs.sort(key=lambda r: (r["date"], r.get("vote_on") == "act"), reverse=True)
        self.files["council/index.json"] = self.council_public

    def council_vote_date(self, cv: CouncilVote, p: Procedure | None, vote_on: str | None) -> tuple[str, str | None]:
        """(date, note) of a Council voting result: its own date, or, for the vote adopting the act that a
        data/curated/council_dates.yaml entry names, the day the act's text gives for the Council's decision (a
        meeting held over several days is otherwise dated by its first day: ST 10263/24, 23-24 May 2024)."""
        cd = self.checked_council_date(p) if p is not None else None
        if not cd or cd.get("vote") != cv.id or vote_on != "act" or cv.outcome != "adopted":
            return cv.date, None
        if cd["date"] == cv.date or abs(_days_between(cv.date, cd["date"])) > 7:
            return cv.date, None
        note = (f"{_squash(cd.get('reason'))} The text of {act_label(self.act[cd['celex']])} gives the date of the "
                f"Council's decision: “{_squash(cd['quote'])}”")  # fmt: skip
        return cd["date"], note.strip()

    def council_split_part(self, cv: CouncilVote, pid: str) -> str | None:
        """The part of a split procedure whose act a Council vote on the parent reference adopted: the one
        part holding an act of the type voted on, dated on or after the vote (the Council's voting results
        cite the parent reference, e.g. ST 8688/23 "2021/0211 (COD)" for Directive (EU) 2023/959 of
        2021/0211A); among several such parts, the one whose act title matches the voting result's title."""
        cands = [
            (c, a)
            for c in self.split_children.get(pid, [])
            for a in self.acts_of.get(c, [])
            if a.act_type == cv.act_type and (a.date_document or a.date_publication or "") >= cv.date
        ]
        if len({c for c, _ in cands}) > 1:
            key = _act_subject_key(cv.title)
            cands = [(c, a) for c, a in cands if key and _act_subject_key(a.title) == key]
        parts = {c for c, _ in cands}
        return parts.pop() if len(parts) == 1 else None

    def council_vote_on(self, cv: CouncilVote, p: Procedure | None) -> tuple[str | None, str | None]:
        """(vote_on, note): what the Council voted on, from its voting result, corrected where the procedure
        record shows that the document's own label does not fit, with a note saying so.

        - Early second-reading agreement: a note labelled "Adoption of the legislative act" whose reference
          document is the Council's first-reading position (OEIL "Council position published", same document
          number), followed by Parliament's second-reading decision on that position, adopted the position:
          the act is adopted only by Parliament's approval (Art. 294(7)(a) TFEU), e.g. ST 12604/20 (9890/20).
        - A note that names no item, on a regulation, directive or decision, dated the day the Legislative
          Observatory records the Council's adoption of the act (e.g. ST 11980/21, PE-CONS 62/21).
        - A vote in the budget procedure (a BUD reference) is not the adoption of an act, even under the item
          "Adoption of the legislative act" (ST 10354/25, the Council's position on draft amending budget 1/2025)."""
        on = cv.vote_on
        bud = next((r for r in cv.procedure_refs if r.endswith("(BUD)")), None)
        if on == "act" and bud:
            return "other", (
                f"The voting-result document names the item “{cv.stage or 'Adoption of the legislative act'}”. The "
                f"vote is in the budget procedure ({bud}), in which a vote of the Council does not by itself adopt a "
                "budget: Parliament and the Council establish it together (Article 314 TFEU)."
            )
        if p is None:
            return on, None
        items = [i.strip() for i in (cv.stage or "").split(";")]
        if on == "act" and any(COUNCIL_DEROGATION_RE.match(i) for i in items):
            adoption = next((o for o in self.s.council if o.id != cv.id and o.vote_on == "act" and o.date == cv.date
                             and o.council_doc and o.council_doc == cv.council_doc
                             and set(o.procedure_refs) & set(cv.procedure_refs)
                             and not COUNCIL_DEROGATION_RE.search(o.stage or "")), None)  # fmt: skip
            if adoption is not None:
                return "other", (
                    "The voting-result document lists, after the adoption of the legislative act, the Council’s "
                    "decision to derogate from the eight-week period for national parliaments (Article 3(3) of the "
                    "Council’s Rules of Procedure). The Council’s vote adopting the act, on the same reference "
                    f"document {cv.council_doc}, is its voting result {adoption.source.identifier} of the same day; "
                    "this vote is on the derogation. Under that Article the Council decides on it “in accordance "
                    "with the voting rule applicable for the adoption of the act or position concerned”."
                )
        if on == "act" and p.type == "COD" and (m := _COUNCIL_DOC_NO.search(cv.council_doc or "")):
            number = (int(m.group(1)), 2000 + int(m.group(2)))  # "ST 9890/20" -> (9890, 2020)
            position = next(
                (
                    d.id
                    for e in p.events
                    if e.kind == EventKind.council_position
                    for d in e.docs
                    if (n := _COUNCIL_POSITION_NO.fullmatch(d.id)) and (int(n.group(1)), int(n.group(2))) == number
                ),
                None,
            )
            second = sorted(
                e.date for e in p.events if e.date > cv.date and SECOND_READING_DECISION_RE.search(e.raw_type or "")
            )
            if position and second:
                return "first_reading_position", (
                    f"The voting-result document names the item “{cv.stage or 'Adoption of the legislative act'}”, "
                    f"but its reference document {cv.council_doc} is the Council’s position at first reading "
                    f"({position}), on which Parliament decided at second reading on {_long_date(second[0])}."
                )
        if on is None and cv.act_type in ("regulation", "directive", "decision"):
            if any(e.kind == EventKind.council_adoption and e.date == cv.date for e in p.events):
                return "act", (
                    "The voting-result document does not name the item voted on; the Legislative Observatory "
                    "records the Council’s adoption of the act on this date."
                )
        return on, None

    def council_rule_assessment(self, assess: Any, cv: CouncilVote, p: Procedure | None) -> dict | None:
        """Apply the voting rule. Whether the Council acted on a Commission proposal (which changes the QMV
        threshold, TEU 16(4) vs TFEU 238(2)) is taken as established only when the linked procedure records
        a COM document or is an ordinary legislative procedure opened by a Commission proposal (see
        commission_cod_proposal); it is taken as excluded when the recorded proposal is the Court of Justice's
        request (court_request); otherwise both thresholds are computed and the result is kept only if they
        agree, without asserting a legal basis (both required numbers of Member States are then given)."""
        year = int(cv.date[:4])
        if p is not None and (p.com_refs or commission_cod_proposal(p)):
            return council_assessment(_as_dict(assess(cv.positions, cv.voting_rule, True, year=year)))
        if COUNCIL_CONSENT_TO_EP_ACT.search(cv.stage or "") or (p is not None and court_request(p)):
            # the Council's consent to Parliament's own regulation is never given on a Commission proposal; an act
            # adopted at the Court's request is not adopted on one (Art. 281 TFEU, second paragraph): 72% of the
            # Member States, TFEU Art. 238(2) (2022/0906(COD), Regulation (EU, Euratom) 2024/2019: "Having regard
            # to the request of the Court of Justice")
            return council_assessment(_as_dict(assess(cv.positions, cv.voting_rule, False, year=year)))
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
        a["blocking_minority_min_states"] = None
        a["states_required_alt"] = b["states_required"]  # 72% (not on a Commission proposal); a: 55%
        why = (
            "this vote is not linked to a procedure file in our data" if p is None
            else "our record of the procedure names no proposal" if not any(e.kind == EventKind.proposal for e in p.events)
            else "our record of the procedure does not establish whose proposal it was"
        )  # fmt: skip
        a["note"] = (a["note"] + " " if a["note"] else "") + (
            "Whether the Council acted on a Commission proposal is not established here: the voting sheet's footnote "
            f"on the threshold is part of an image we do not read, and {why}. The result is the same under both "
            "qualified-majority thresholds (55% and 72% of Member States, 65% of the population)."
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
                "named_acts": [self._procedure_ref(self.proc[c]) for c in children],  # linked to their files
            })  # fmt: skip
        if (m := PARLIAMENT_REPORT_RE.fullmatch(p.id)) is not None:
            # 2017/0333R(APP): Parliament's interim report (Rule 105(5)) or report accompanying a consent
            # (M) on the main procedure 2017/0333(APP); a resolution, not a legislative act
            main = self.proc.get(m.group(1))
            kind = "an interim report" if m.group(2) == "R" else "a report"
            ref = main.reference if main else m.group(1)
            text = (
                f"Parliament adopted {kind} on the procedure {ref}. It is a resolution of Parliament, not a "
                "legislative act; the proposal itself is followed on the main file."
            )
            return self._status_dict({
                "status": {"stage": "unknown", "label": "Parliament report (not a legislative act)",
                           "explanation": text, "since": None, "basis": "source"},
                "next_step": {"text": f"None for this report. See the main procedure {ref} for the proposal.",
                              "institution": None, "basis": "source"},
                "named_acts": [self._procedure_ref(main)] if main else [],  # linked to the main file
            })  # fmt: skip
        fn = (
            _lazy("pipeline.analysis.status", "classify")
            if not hasattr(self, "_classify")
            else self._classify
        )
        self._classify = fn
        acts = self.acts_of.get(p.id, [])
        train = self.train_of.get(p.id, [])
        p = self.council_dated(p)
        if fn is not None:
            try:
                st = fn(p, acts, train, date.fromisoformat(self.today), others=self.act,  # others: to name acts
                        votes=self.votes_of.get(p.id, []))  # fmt: skip
                return self.unlinked_act_status(p, acts, self._status_dict(_as_dict(st)))
            except Exception as e:  # noqa: BLE001 - never let one dossier break the build
                log.warning("classify failed for %s: %r", p.id, e)
                self.s.issues.append(f"status.classify failed for {p.id}: {e!r}"[:300])
        return self.fallback_status(p, acts, train)

    def unlinked_act_status(self, p: Procedure, acts: list[LegalAct], r: dict) -> dict:
        """The status of a file still awaiting a decision in the official records, while an act whose text cites
        Parliament's opinion on it is published (data/curated/unlinked_acts.yaml): the act is named with what it
        cites, not linked, and the file is not shown as still being decided (2025/0806(CNS): Council Regulation (EU)
        2026/415 cites "the Opinion of the European Parliament" of 26 November 2025; no official record links them).
        Only while no act is linked to the file and Parliament's opinion is recorded on the day the act cites."""
        e = self.unlinked_acts.get(norm_ref(p.reference))
        if not e or acts or r["status"].get("stage") not in ACTIVE_STAGES:
            return r
        if not any(x.kind == EventKind.ep_position and x.date == e["opinion"] for x in p.events):
            log.warning("curated unlinked_acts.yaml: %s records no opinion of Parliament on %s; ignored", p.reference,
                        e["opinion"])  # fmt: skip
            return r
        opened = isinstance(e.get("initiative"), str) and any(
            x.kind == EventKind.proposal and e.get("document") in {d.id for d in x.docs} for x in p.events
        )  # the text the act cites that the file's proposal step transmitted (2025/0806(CNS): ECB/2025/17, 09737/2025)
        text = (
            f"Parliament delivered its opinion on {_long_date(e['opinion'])}. {e['label']} of {_long_date(e['date'])}, "
            f"published in the Official Journal on {_long_date(e['published'])}, cites “the Opinion of the European "
            f"Parliament” of {_long_date(e['opinion'])}, the day of Parliament's opinion on this file"
            + (f", and the {e['initiative']}, which the file's proposal step, document {e['document']}, transmitted."
               if opened else ".")
            + " No official record links that act to this procedure: EUR-Lex records no procedure for it"
            + (f" (checked on {_long_date(e['reviewed'])})" if ISO_DATE_RE.match(str(e.get("reviewed"))) else "")
            + ", and the Legislative Observatory lists no final act for the file"
            + (f" and gives its stage as “{p.stage_raw}”." if p.stage_raw else ".")
        )  # fmt: skip
        return self._status_dict({
            "status": {"stage": "unknown", "label": "Final act not linked in the official records", "explanation": text,
                       "since": None, "basis": "source"},
            "next_step": {"text": "Not determined: no official record in our data links a final act to this procedure.",
                          "institution": None, "basis": "unknown"},
            "named_acts": [{"celex": e["celex"], "label": e["label"],
                            "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{e['celex']}"}],
            "application": r.get("application"),
        })  # fmt: skip

    @staticmethod
    def _procedure_ref(p: Procedure) -> dict:
        """A procedure named in a status text, in the form of `named_acts` (no CELEX id): linked to its file."""
        return {"celex": "", "label": p.reference, "url": p.oeil_url, "dossier": p.id}

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
            "status": {k: status.get(k) for k in ("stage", "label", "explanation", "since", "basis")}
            | ({"named_acts": r["named_acts"]} if r.get("named_acts") else {}),  # acts the explanation names
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

    def amending_deadlines(self, det: dict, acts: list[LegalAct]) -> dict:
        """A directive's next step, followed by what the directives that have since amended it still require. Which
        of an amending directive's deadlines covers the changes to this one is in its text (data/curated/
        transposition.yaml `amends`): Directive (EU) 2026/470, Art. 5(1), sets 19 March 2027 for its Articles 1 to 3
        and 26 July 2028 for Article 4, which amends the CSDDD. Without that, an amending directive's deadline is
        named only when it records a single one. An amending directive that also repeals this one names the repeal
        (Directive (EU) 2024/1640, Art. 77: "Directive (EU) 2015/849 is repealed with effect from 10 July 2027")."""
        ns = det["next_step"]
        a = next((x for x in acts if x.act_type == "directive"), None)
        if a is None or det.get("instrument") != "directive" or det["stage"] not in ("published", "in_force"):
            return ns
        if ns.get("basis") == "unknown":
            return ns
        notes = []
        for c in a.amended_by:
            m = self.act.get(c)
            pub = m.date_publication if m else None
            if not m or m.act_type != "directive" or m.in_force is False or not pub or pub > self.today:
                continue
            if any(x.celex == c for x in acts):
                continue
            label = act_label(m)
            if c in a.repealed_by or a.celex in m.repeals:
                end = _add_days(a.end_of_validity, 1) if a.end_of_validity else None  # the day after its last day
                if end and end > self.today:
                    notes.append((end, f"{label} repeals this directive with effect from {_long_date(end)}."))
                continue
            recorded = [x.date for x in classify_transposition(m) if x.kind in ("deadline", "further_deadline")]
            cur = next((x for x in self.transposition_checks.get(c, {}).get("amends") or [] if x["celex"] == a.celex),
                       None)  # fmt: skip
            if cur and {cur["deadline"], *(f["date"] for f in cur.get("further") or [])} <= set(m.transposition_deadlines):
                dated = [(cur["deadline"], None)] + [(f["date"], f["provisions"]) for f in cur.get("further") or []]
                ahead = [(d, what) for d, what in dated if d > self.today]
                if not ahead:
                    continue
                (first, what), rest = ahead[0], ahead[1:]
                text = f"{label} amends this directive ({cur['provision']}); " + (
                    f"{what} must be transposed by {_long_date(first)}" if what
                    else f"Member States must transpose the amendments by {_long_date(first)}"
                )  # fmt: skip
                extra = "; ".join(f"{w} by {_long_date(d)}" for d, w in rest)
                notes.append((first, text + (f" ({extra})" if extra else "") + "."))
            elif len(recorded) == 1 and recorded[0] > self.today:
                notes.append((recorded[0], f"{label}, which amends this directive, must be transposed by "
                                           f"{_long_date(recorded[0])}."))  # fmt: skip
            elif len(recorded) > 1 and any(d > self.today for d in recorded):
                # nothing establishes which of its deadlines concerns the changes to this directive
                notes.append((min(d for d in recorded if d > self.today), f"{label} also amends this directive; its "
                              "transposition deadlines differ by provision, as its text sets them."))  # fmt: skip
        if not notes:
            return ns
        return {**ns, "text": " ".join([ns["text"], *(n for _, n in sorted(notes))])}

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
        cur = next((self.act_dates[a.celex] for a in acts if a.celex in self.act_dates), None)
        return {
            "entry_into_force": eif[0] if eif else None,
            "entry_into_force_pending": pending,
            "application_dates": app,
            "partial_application_dates": sorted({d for a in acts for d in a.partial_application_dates}),
            # EUR-Lex also marks the entry-into-force date as one from which some provisions apply
            "partial_on_entry_into_force": bool(eif) and any(
                a.partial_on_entry_into_force for a in acts if a.entry_into_force == eif[0]
            ),
            # dates checked against the act's text (data/curated/act_dates.yaml), with the provisions
            "application_detail": [
                {"date": x["date"], "partial": bool(x.get("partial")), "provisions": _squash(x.get("provisions")) or None}
                for x in (cur or {}).get("application") or []
            ],
            "dates_note": {
                "reason": _squash(cur.get("reason")),
                "sources": [{"label": _squash(s.get("label")), "url": s.get("url")} for s in cur.get("sources") or []
                            if isinstance(s, dict) and s.get("url")],
                "reviewed": cur.get("reviewed"),
            } if cur else None,
            "transposition_deadlines": [x.date for x in tr_all if x.kind in ("deadline", "further_deadline")],
            "transposition": [
                {"date": x.date, "kind": x.kind, "articles": [article_label(r) for r in x.articles]} for x in tr_all
            ],
            "future": any(d > self.today for d in eif + app + [x.date for x in tr_all]),
        }

    def timeline(self, p: Procedure, acts: list[LegalAct], votes: list[EpVote]) -> list[dict]:
        votes_by_date: dict[str, list[EpVote]] = defaultdict(list)
        for v in votes:
            if v.id in self.indexed_vote_ids and vote_held(v):
                votes_by_date[v.date].append(v)
        listed = {v.id: v for vs in votes_by_date.values() for v in vs}
        # The Council's own voting results date its votes; the Legislative Observatory's Council steps are
        # aligned with them so the timeline and the Council vote cards cannot disagree.
        cvotes = [cv for cv in self.council_of.get(p.id, []) if cv["date"] <= self.today]
        position_dates = {cv["date"] for cv in cvotes if cv.get("vote_on") == "first_reading_position"}
        act_adopted = any(  # the Council's vote on the act, or on its consent to an act Parliament adopts
            cv["outcome"] == "adopted" and (cv.get("vote_on") == "act" or COUNCIL_CONSENT_RE.match(cv.get("stage") or ""))
            for cv in cvotes
        )
        # A Council act bears the date of its adoption; OEIL's Council step is shown on that date when they differ
        # (2024/0016(CNS): OEIL 17 July 2024, Council Regulation (EU) 2024/1732 of 17 June 2024, published 19 June)
        adopts = _lazy("pipeline.analysis.status", "parliament_adopts")
        council_acts = p.type not in ("COD", "SYN") and not (adopts and adopts(p, acts))
        act_dates = sorted({a.date_document for a in acts if a.date_document and a.date_document <= self.today})
        # An act of Parliament and the Council is signed by both Presidents (Art. 297(1) TFEU) on the day the act
        # bears: the act dates the signature, not the EP's record of it (2017/0329(COD): the EP and OEIL give 11
        # April 2018, the day before the Council adopted the act; Directive (EU) 2018/597 "of 18 April 2018"). Without
        # such an act in our data, the EP's record is shown on the EP's date ("Final act signed"), as the signature of
        # both Presidents in an ordinary legislative procedure.
        joint_acts = [a for a in acts if JOINT_ACT_RE.match(a.title or "") and (a.date_signature or a.date_document)]
        # The Official Journal dates an act's publication: the EP's (and OEIL's) record of it on another day is not
        # shown as a publication (2018/0069(COD): 25 July 2019 for Regulation (EU) 2019/982, OJ L 164, 20.6.2019; the
        # EP gives that day to 2016/0074(COD), whose Regulation (EU) 2019/1241 is in OJ L 198, 25.7.2019)
        act_pubs = {a.date_publication for a in acts if a.date_publication}
        ep_pubs: set[str] = set()
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        # (kind, date, title, detail) -> the day's steps so far: position in `out`, documents other than the sitting's
        # records. Two records of one step are shown once, with the documents of both: a debate continued later in the
        # sitting (2016/0131(COD), 7 Oct 2021, items 3 "(debate)" and 5 "(continuation of debate)"), or two
        # announcements of voting results; steps of different committees or documents stay apart (2025/0545(COD),
        # 14 Jul 2026: the opinions of AGRI and FEMM)
        seen_ev: dict[tuple[str, str, str, str | None], list[tuple[int, set[str]]]] = defaultdict(list)
        negotiation: list[int] = []  # positions in `out` of Parliament's decisions on negotiations
        from_vote: list[int] = []  # positions in `out` of steps built from a vote (with_recorded_events)
        urgency_at: dict[str, int] = {}  # day -> position in `out` of Parliament's vote on urgent procedure
        for e in p.events:
            if e.date > self.today:  # forecasts are not legally fixed dates
                continue
            kind = e.kind.value
            papers = {d.id for d in e.docs if not SITTING_RECORD_RE.match(d.id)}
            same = seen_ev[(kind, e.date, e.title, e.detail)]
            if (twin := next((i for i, ids in same if ids & papers or not (ids or papers)), None)) is not None:
                x = out[twin]
                x["docs"] += [d.model_dump(mode="json") for d in e.docs if d.id not in {y["id"] for y in x["docs"]}]
                continue
            # the announcement in plenary of a committee's decision to negotiate is a procedural step, not a decision
            title, key = e.title, kind in KEY_KINDS and not (e.raw_type or "").startswith(MANDATE_ANNOUNCED)
            if e.institution == "Council" and kind == "council_position" and title == OEIL_POSITION_PUBLISHED:
                # OEIL key event "Council position published": the date the position was published, which
                # is not the date of the Council's vote adopting it.
                if e.date in position_dates:
                    continue  # same day as the vote, which is listed from the Council's voting result
                title, key = "Council's first-reading position published", key and not position_dates
            elif e.institution == "Council" and kind == "council_adoption" and act_adopted:
                continue  # the Council's voting result on the act (added below) dates this step
            elif kind == "signature" and joint_acts:
                continue  # the act dates the signature (added below)
            elif kind == "publication" and act_pubs and e.date not in act_pubs:
                ep_pubs.add(e.date)  # noted on the act's publication (below)
                continue
            inst = e.institution
            when, detail = e.date, e.detail
            if kind == "signature" and p.type == "COD":
                # "Legislative acts adopted under the ordinary legislative procedure shall be signed by the President
                # of the European Parliament and by the President of the Council" (Art. 297(1) TFEU); the EP's date
                # is kept, as it records it (2025/0106(COD): 21 October 2026, no act in our EUR-Lex data yet)
                inst = "EP and Council"
                detail = detail or (
                    "Signed by the Presidents of Parliament and of the Council (Article 297(1) TFEU); date as the "
                    "European Parliament's procedure record gives it."
                )
            if e.institution == "Council" and kind == "council_adoption" and council_acts:
                near = [d for d in act_dates if abs(_days_between(d, e.date)) <= 92]  # the act this step adopted
                if len(near) == 1 and near[0] != e.date:
                    when = near[0]
                    detail = f"Date of the act (EUR-Lex); the Legislative Observatory gives {_long_date(e.date)}."
            vote_id = None
            if kind in VOTE_EVENT_KINDS and votes_by_date.get(e.date):
                docs = {d.id for d in e.docs}
                cands = votes_by_date[e.date]
                # a motion to reject the text that was rejected decided no step of the day: Parliament went on to
                # vote the text or amendments (2021/0206(COD), 8 Jun 2022: 144420 rejected, then amendments adopted);
                # at second reading such motions are linked below
                deciding = [v for v in cands if not (v.kind_detail in REJECTION_MOTIONS and v.outcome != "adopted")]
                by_doc = [v for v in deciding if docs & set(v.doc_ids)]
                # the final vote whose official result is known comes first (stable: newest id first), then the
                # vote on the amended text after which the file went back to committee (its negotiating mandate)
                finals = sorted(
                    (v for v in (by_doc or deciding) if v.kind == "final"),
                    key=lambda v: (v.outcome not in ("adopted", "rejected"), v.n_for is None),
                )
                mandates = [v for v in (by_doc or deciding) if v.kind == "mandate"]
                pick = finals or mandates or by_doc or (deciding if len(deciding) == 1 else [])
                vote_id = pick[0].id if pick else None
                if kind == "ep_position" and e.raw_type in PLENARY_DECISION_TYPES and finals and all(
                    v.outcome == "rejected" and v.outcome_basis in ("published", "minutes", "derived") for v in finals
                ):
                    # "Parliament took its decision": the decision of the day's final vote, officially a rejection
                    # (2025/0429(COD), 26 Mar 2026: 228-311-92, OEIL "rejected the proposal", T10-0095/2026)
                    title = rejection_title(p)
                amends_position = (e.raw_type or "").endswith("PLENARY_AMEND_COUNCIL_POSITION")
                if vote_id is None and SECOND_READING_DECISION_RE.search(e.raw_type or "") and not amends_position:
                    # second reading: the votes deciding it are the motions to reject the Council's position (not when
                    # Parliament amended it: then its amendments decided, which are not listed; 2025/0429(COD), 9 Jul
                    # 2026, motion 195775 rejected)
                    motions = sorted(
                        (v for v in cands if v.kind_detail == "reject_council_position"), key=lambda v: (len(v.id), v.id)
                    )
                    vote_id = motions[0].id if motions else None
                    if len(motions) > 1 and not detail and all(v.outcome == "rejected" for v in motions):
                        detail = (
                            f"Parliament voted on {len(motions)} motions to reject the Council's position and rejected "
                            "each of them; the vote link opens the first."
                        )
            elif kind in ("ep_position", "plenary_vote") and (near := decision_vote_near(e, votes_by_date)):
                # no vote held on the decision's date: the one deciding vote recorded within DECISION_VOTE_DAYS of it
                # (remote voting, 2020-22: results were recorded the next day)
                vote_id = near.id
                detail = detail or (
                    f"Parliament's vote records date this vote {_long_date(near.date)}; its procedure record dates "
                    f"the decision {_long_date(e.date)}."
                )
            elif kind == "negotiation_mandate" and e.raw_type == ENDORSE_NEGOTIATIONS_EVENT:
                negotiation.append(len(out))  # linked below, once every event of the day is linked
            if title == "Parliament voted on consent" and (consent := _lazy("pipeline.analysis.status", "_consent_outcome")):
                # the officially recorded outcome, as the status gives it (2025/0313(APP): vote 197472, adopted); of the
                # final vote linked to the step when there is one, also from another day (2018/0132(APP): decision of 25
                # March 2021, vote 129442 of 24 March, consent given in the minutes)
                lv = listed.get(vote_id or "")
                linked = lv.outcome if lv and lv.kind == "final" and lv.outcome_basis in ("published", "minutes") else None
                title = {"adopted": "Parliament gave its consent", "rejected": "Parliament did not give its consent"}.get(
                    (linked if lv else consent(votes, e.date)) or "", title)  # fmt: skip
            if (e.raw_type or "").endswith("PLENARY_AMEND_COUNCIL_POSITION"):
                # also on a day without a listed vote (2013/0072(COD), 21 Jan 2026: only amendment votes)
                detail = " ".join(x for x in (detail, second_reading_amendments(votes, e.date)) if x) or None
            if (m := _VOTE_EVENT_ID.match(e.id)) and (e.raw_type or "").startswith("ep_vote:") and m.group(1) in listed:
                vote_id = m.group(1)  # a step built from the vote itself (with_recorded_events: 199592, 2026/0325(COD))
            record = (e.raw_type or "").rsplit("/", 1)[-1] in EP_VOTE_RECORDS
            if kind == "plenary_vote" and not record and vote_id in listed and listed[vote_id].kind == "mandate":
                # the decision recording the vote on the amended text, Parliament's position for the negotiations (it
                # is shown with the referral back that followed: 2021/0106(COD), 14 Jun 2023, vote 156022)
                key = True
            if (e.raw_type or "").endswith("/PLENARY_REFER_COMMITTEE_RECONSIDERATION"):
                key = True  # the file went back to committee; a decision to negotiate taken before it lapsed (status)
            src = _event_src(e.source)
            if (urgent := urgency_vote(e, votes, self.indexed_vote_ids)) is not None:
                if e.date in urgency_at:  # the day's other record of the same vote: its documents only
                    x = out[urgency_at[e.date]]
                    x["docs"] += [d.model_dump(mode="json") for d in e.docs if d.id not in {y["id"] for y in x["docs"]}]
                    continue
                urgency_at[e.date] = len(out)
                title, detail, src, vote_id = urgent
            if vote_id and _VOTE_EVENT_ID.match(e.id) and (e.raw_type or "").startswith("ep_vote:"):
                from_vote.append(len(out))
            out.append({
                "id": e.id, "date": when, "kind": kind, "title": title, "detail": detail,
                "institution": inst, "state": "done", "key": key,
                "docs": [d.model_dump(mode="json") for d in e.docs], "source": src, "vote_id": vote_id,
            })  # fmt: skip
            same.append((len(out) - 1, papers))
            seen.add((kind, when))
        # Parliament's confirmation of the committee's decision to negotiate: the vote on that decision, unless another
        # event of the same day already links it. A referral back to committee for negotiations is a decision of its
        # own, voted after the text ("Parliament decides to refer the matter back", Rule 59(4) of the 9th-term Rules
        # of Procedure; 2025/0524(COD), 13 Nov 2025: 181375 on the text, then 181446 "Request for referral back (Rule
        # 60(4))"), and referral votes are not listed: its step links no vote, and the mandate vote stays on the step
        # recording the vote on the text
        for i in negotiation:
            day = out[i]["date"]
            linked = {x["vote_id"] for x in out if x["date"] == day and x["vote_id"]}
            pick = [
                v for v in votes_by_date.get(day, []) if v.kind_detail == "negotiation_decision" and v.id not in linked
            ]
            out[i]["vote_id"] = pick[0].id if len(pick) == 1 else None
            parent = self.vote_dossier_map.get(pick[0].id, []) if len(pick) == 1 else [p.id]
            if p.id not in parent and len(parent) == 1 and not out[i]["detail"]:
                # the vote of the file this part was split from (parent_negotiation_votes)
                out[i]["detail"] = (
                    f"Parliament's vote records file this vote under {self.proc[parent[0]].reference}, the procedure "
                    "this file was split from."
                )
        # A step built from a vote links it only when no other key step links it (2025/0393(COD), 6 Oct 2026: vote
        # 197467 stays on "Parliament voted amendments to the proposal" and the mandate step built from it links none,
        # as in 2021/0106(COD); 2026/0325(COD): 199592 is linked from that step alone)
        others = {x["vote_id"] for i, x in enumerate(out) if x["key"] and x["vote_id"] and i not in from_vote}
        for i in from_vote:
            if out[i]["vote_id"] in others:
                out[i]["vote_id"] = None
        # the rejection derived from the vote (with_recorded_events, used for the status) repeats Parliament's own
        # decision that day once that decision is titled as the rejection it was (2022/0196: 22 Nov 2023)
        decided = {x["date"] for x in out if x["kind"] == "ep_position" and "rejected" in x["title"]}
        out = [x for x in out if not (x["kind"] == "rejection" and x["id"].startswith("vote-") and x["date"] in decided)]
        out.extend(council_vote_event(cv) for cv in cvotes)
        for a in acts:
            src = _src(a.source)
            # the act by its number ("Directive (EU) 2019/884"), as its title gives it: tells a file's acts apart
            label = act_label(a)
            if label == a.celex:
                label = celex_act_label(a.celex) or f"{a.act_type.capitalize()} (CELEX {a.celex})"
            # (kind, date, title, title once the date has passed)
            synth: list[tuple[str, str, str, str | None]] = []
            # only an act of Parliament and the Council is signed by both Presidents; a Council act is signed
            # on the day the Council adopted it, which the Council's own step already records
            if a in joint_acts:
                synth.append(("signature", a.date_signature or a.date_document, JOINT_SIGNATURE, None))
            if a.date_publication:
                synth.append(
                    ("publication", a.date_publication, "Published in the Official Journal of the EU", None)
                )
            cur = self.act_dates.get(a.celex) or {}
            provisions = {x["date"]: _squash(x.get("provisions")) for x in cur.get("application") or []}
            if a.entry_into_force:
                # a checked date on the entry-into-force day is not a further application date (apply_act_dates):
                # name what starts to apply in the entry-into-force event
                on_eif = next((x for x in cur.get("application") or [] if x["date"] == a.entry_into_force), None)
                prov = provisions.get(a.entry_into_force)
                if on_eif and prov and on_eif.get("partial"):
                    synth.append(("entry_into_force", a.entry_into_force,
                                  f"Enters into force; some provisions start to apply: {prov}",
                                  f"Entered into force; some provisions started to apply: {prov}"))  # fmt: skip
                elif on_eif and prov:
                    synth.append(("entry_into_force", a.entry_into_force,
                                  f"Enters into force and starts to apply: {prov}",
                                  f"Entered into force and started to apply: {prov}"))  # fmt: skip
                else:
                    synth.append(("entry_into_force", a.entry_into_force, "Enters into force", None))
            for d in a.other_application_dates:
                # "Further" only after an earlier application date (PPWR, Regulation (EU) 2025/40, Art. 71: "It shall
                # apply from 12 August 2026", the first date from which any of it applies)
                earlier = (any(x < d for x in a.other_application_dates) or a.partial_on_entry_into_force
                           or bool(a.entry_into_force and provisions.get(a.entry_into_force)))  # fmt: skip
                if provisions.get(d):
                    synth.append(("application", d, f"Starts to apply: {provisions[d]}",
                                  f"Started to apply: {provisions[d]}"))  # fmt: skip
                elif d in a.partial_application_dates:
                    synth.append(("application", d, "Some provisions start to apply (date recorded by EUR-Lex)",
                                  "Some provisions started to apply (date recorded by EUR-Lex)"))  # fmt: skip
                elif earlier:
                    synth.append(("application", d, "Further provisions start to apply (date recorded by EUR-Lex)",
                                  "Further provisions started to apply (date recorded by EUR-Lex)"))  # fmt: skip
                else:
                    synth.append(("application", d, "Rules start to apply (date recorded by EUR-Lex)",
                                  "Rules started to apply (date recorded by EUR-Lex)"))  # fmt: skip
            # a date whose role the data do not establish ("other") is not a legal milestone: it stays off the
            # timeline (and so off "Latest verified development" and "Coming up")
            tr = classify_transposition(a)
            start = application_start(a, tr)
            for x in tr:
                arts = f" ({articles_text(x.articles)})" if x.articles else ""
                if x.kind == "deadline":
                    synth.append(("transposition_deadline", x.date,
                                  "Deadline for Member States to transpose the directive", None))  # fmt: skip
                elif x.kind == "further_deadline":  # earlier or later than the general deadline
                    t = f"Transposition deadline for specific provisions{arts}"
                    synth.append(("transposition_deadline", x.date, t, t + " (passed)"))
                elif x.kind == "application":
                    t = (f"Application date for specific provisions{arts}" if start and x.date > start
                         else f"Application date for national transposition measures{arts}")  # fmt: skip
                    synth.append(("transposition_application", x.date, t, t))
            for kind, d, title, past_title in synth:
                if (kind, d) in seen:
                    continue
                seen.add((kind, d))
                future = d > self.today
                if not future:
                    title = past_title or PAST_TITLES.get(kind, title)
                doc = {"id": a.celex, "label": a.oj_ref or a.celex, "kind": "act", "date": a.date_document,
                       "url": a.eurlex_url}  # fmt: skip
                source = src
                if kind in ("entry_into_force", "application", "transposition_deadline", "transposition_application"):
                    if cite := act_date_source(cur, d):  # corrected date: cite the text it was checked against
                        doc |= {"label": _squash(cite.get("label")), "url": cite.get("url")}
                        # the date is that text's, not EUR-Lex's record of the act (Regulation (EU) 2022/2065, Art.
                        # 93(2): 17 February 2024, where EUR-Lex records 17 February 2022)
                        checked = f" (checked {_long_date(cur['reviewed'])})" if cur.get("reviewed") else ""
                        source = {"institution": "EUR-Lex", "url": cite.get("url"),
                                  "label": f"{_squash(cite.get('label'))}{checked}",
                                  "identifier": cite.get("celex") or a.celex, "retrieved_at": None, "published": None}  # fmt: skip
                    elif a.amended_by:  # Cellar's current record, which may reflect later amendments
                        doc["label"] = f"EUR-Lex record, CELEX {a.celex}"
                detail, chk = label, a.transposition_checked
                if kind == "transposition_deadline" and chk and chk.exceptions and any(
                    x.date == d and x.kind == "deadline" for x in tr
                ):  # not every Member State had this deadline (Directive (EU) 2016/798, Art. 33(2), (2a) and (4))
                    detail = f"{label}. Exceptions in its text: {chk.exceptions}"
                elif kind == "transposition_application" and chk and chk.application_exceptions and d == chk.applies_from:
                    detail = f"{label}. {chk.application_exceptions}"  # a later date for some measures (CSDDD Art. 37(1))
                if kind == "publication" and ep_pubs and len(act_pubs) == 1:  # the EP's record gives another day
                    detail = (f"{label}. The European Parliament's procedure record gives "
                              f"{' and '.join(_long_date(x) for x in sorted(ep_pubs))} for its publication.")  # fmt: skip
                out.append({
                    "id": f"act-{a.celex}-{kind}-{d}", "date": d, "kind": kind, "title": title, "detail": detail,
                    "institution": "EP and Council" if kind == "signature" else "EUR-Lex",
                    "state": "scheduled" if future else "done",
                    "key": True, "docs": [doc], "source": source, "vote_id": None,
                })  # fmt: skip
            for c in a.amended_by:  # later legislative acts amending this one (when in the snapshot)
                m = self.act.get(c)
                pub = m.date_publication if m else None
                if not m or not pub or pub > self.today or (a.date_publication and pub <= a.date_publication):
                    continue
                if ("amended", c) in seen or any(x.celex == c for x in acts):
                    continue
                seen.add(("amended", c))
                out.append({
                    "id": f"act-{a.celex}-amended-{c}", "date": pub, "kind": "other",
                    "title": f"Amended by {act_label(m)}", "detail": "The amending act was published in the Official Journal.",
                    "institution": "EUR-Lex", "state": "done", "key": True,
                    "docs": [{"id": m.celex, "label": m.oj_ref or m.celex, "kind": "act", "date": m.date_document,
                              "url": m.eurlex_url}],
                    "source": _src(m.source), "vote_id": None,
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
        positions = {x["date"] for x in out if x["kind"] == "council_position"}
        out.sort(key=lambda x: (x["date"], x["state"] == "scheduled", *day_rank(x, positions), x["id"]))
        return out

    def index_file_documents(self) -> None:
        """Which files' own records list each EP document: among their documents or on a step other than a debate
        (a joint debate cites the documents of every file debated), the sitting's records left out."""
        self.files_of_doc: dict[str, set[str]] = defaultdict(set)
        self.docs_of_file: dict[str, set[str]] = {}
        for p in self.procedures:
            ids = {d.id for d in p.documents} | {
                d.id for e in p.events if not (e.raw_type or "").endswith("/PLENARY_DEBATE") for d in e.docs}  # fmt: skip
            self.docs_of_file[p.id] = {i for i in ids if not SITTING_RECORD_RE.match(i)}
            for i in self.docs_of_file[p.id]:
                self.files_of_doc[i].add(p.id)

    def joint_debates(self, p: Procedure, tl: list[dict]) -> list[dict]:
        """A debate whose item cites another file's documents, or a report no file in our data lists, was a joint
        debate (the EP's item 15 of 25 March 2026, "Deposit protection and early intervention measures (joint debate)",
        cites the reports of 2023/0111, 2023/0112 and 2023/0115(COD)). Its step keeps this file's documents and the
        sitting's records, and names the other files (`joint_with`): each file in our data with its report on the item,
        and each report of a file that is not, as OEIL's own procedure file shows the debate without them."""
        mine = self.docs_of_file.get(p.id, set())
        for x in tl:
            if x["kind"] != "plenary_debate":
                continue
            others = [d for d in x["docs"] if not SITTING_RECORD_RE.match(d["id"]) and d["id"] not in mine]
            files = sorted({f for d in others for f in self.files_of_doc.get(d["id"], ()) if f != p.id})
            unlisted = [d for d in others if not self.files_of_doc.get(d["id"]) and EP_REPORT_ID_RE.fullmatch(d["id"])]
            if not files and not unlisted:
                continue
            x["title"] = "Joint debate in Parliament"
            x["docs"] = [d for d in x["docs"] if SITTING_RECORD_RE.match(d["id"]) or d["id"] in mine]
            x["joint_with"] = [{
                "id": f, "ref": self.proc[f].reference, "title": _truncate(self.dossier_title(self.proc[f]), 160),
                "report": next((d for d in others if EP_REPORT_ID_RE.fullmatch(d["id"])
                                and f in self.files_of_doc.get(d["id"], ())), None),
            } for f in files] + [{"id": None, "ref": None, "title": None, "report": d} for d in unlisted]  # fmt: skip
        return tl

    def approval_without_vote(self, p: Procedure, tl: list[dict], votes: list[EpVote]) -> dict | None:
        """Parliament's latest approval of the Council's position at second reading (PLENARY_APPROVE_COUNCIL_POSITION)
        when the timeline links no vote to it: when Parliament approves the Council's position or takes no decision, the act
        is deemed adopted in the wording of that position (Art. 294(7)(a) TFEU); only a rejection or amendments need a vote,
        so no vote on the text as a whole is held. With Parliament's record of the approval, "Approval without vote"
        (EP API decisions from the 10th term: 176082, 2018/0198(COD), 6 May 2025), whether proposals to amend or reject
        the position were voted on the file within DECISION_VOTE_DAYS of it (2017/0237(COD), 29 Apr 2021: 10 amendments),
        and the date of the file's first-reading decision when it precedes the votes this site covers."""
        linked = {x["id"] for x in tl if x["vote_id"]}
        steps = [e for e in p.events if (e.raw_type or "").endswith("/PLENARY_APPROVE_COUNCIL_POSITION")
                 and self.votes_from <= e.date <= self.today and e.id not in linked]  # fmt: skip
        if not steps:
            return None
        e = max(steps, key=lambda x: (x.date, x.id))
        lo, hi = DECISION_VOTE_DAYS
        near = [v for v in votes if lo <= _days_between(e.date, v.date) <= hi and vote_held(v)]
        record = next((v for v in near if (v.reference_text or "").casefold() == "approval without vote"), None)
        first = min((x.date for x in p.events if x.kind == EventKind.ep_position and x.date < e.date), default=None)
        return {
            "date": e.date,
            "record": _src(record.source) if record else None,
            "amendments_voted": any(v.kind == "amendment" for v in near),
            "rejection_voted": any(v.kind_detail == "reject_council_position" for v in near),
            # split or separate votes on parts of the text, no outcome stated (2018/0190(COD), 19 May 2021: 17, adopted)
            "parts_voted": any(v.kind == "split_or_separate" for v in near),
            "first_reading": first if first and first < self.votes_from else None,
        }

    def act_summary(self, a: LegalAct) -> dict:
        return {
            "celex": a.celex, "eli": a.eli, "act_type": a.act_type, "title": a.title,
            "date_document": a.date_document, "date_publication": a.date_publication,
            "entry_into_force": a.entry_into_force, "other_application_dates": a.other_application_dates,
            "transposition_deadlines": a.transposition_deadlines if a.act_type == "directive" else [],
            "in_force": a.in_force, "end_of_validity": a.end_of_validity, "eurlex_url": a.eurlex_url,
            "amends": a.amends, "amended_by": a.amended_by, "repeals": a.repeals, "repealed_by": a.repealed_by,
            **({"partly_repeals": a.partly_repeals} if a.partly_repeals else {}),  # partial repeals, when recorded
            **({"partly_repealed_by": a.partly_repealed_by} if a.partly_repealed_by else {}),
            "court_rulings": [ruling_summary(r) for r in getattr(a, "court_rulings", [])],
        }  # fmt: skip

    def transposition_status(self, celex: str, country: str, deadline: str | None) -> str:
        if country in (((self.transposition_checks.get(celex) or {}).get("exemption") or {}).get("countries") or []):
            return "not_required"  # the directive itself does not require it (Directive (EU) 2016/798, Art. 33(4))
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

    def implementations(self, acts: list[LegalAct]) -> list[dict]:
        """One table per directive of the file, in the order of its acts: 2013/0400(CNS) adopted Council Directive
        2014/86/EU and Council Directive (EU) 2015/121, each with its own national measures."""
        return [self.implementation_table(a) for a in acts if a.act_type == "directive"]

    def implementation_table(self, a: LegalAct) -> dict:
        deadline = general_deadline(a)
        countries = []
        for c in sorted(MEMBER_STATES):
            ms = self.measures_by.get((a.celex, c), [])
            # date of notification to the Commission (the national journal date of a notified act may be
            # decades older than the directive, e.g. a civil code)
            dates = sorted(m.notified for m in ms if m.notified)
            oo = self.optouts.get(a.celex)
            status = self.transposition_status(a.celex, c, deadline)
            schengen = self.schengen_note(a.celex, c) if status == "not_participating" else None
            countries.append({
                "country": c, "measures": len(ms), "status": status,
                # Denmark and a directive building upon the Schengen acquis (Protocol No 22, Art. 4)
                **({"status_note": schengen[0], "status_note_url": schengen[1]} if schengen else {}),
                "latest_notification": dates[-1] if dates else None,
                "opted_in": oo.opted_in.get(c) if oo else None,
                "infringements": [self.infr_info(i, a.celex) for i in self.infr_by_celex.get(a.celex, [])
                                  if i.country == c],
            })  # fmt: skip
        note = "Counts are national measures notified to the Commission and listed by EUR-Lex."
        if a.celex not in self.measure_celexes:
            note = "National transposition data for this directive is not available in this release. " + note
        older = bool(deadline and deadline < INFRINGEMENTS_FROM)
        if older:  # cases can start only after the deadline: those closed before 2019 are not in the register data
            note += (f" Infringement cases: open cases and cases with a Commission decision since "
                     f"{_long_date(INFRINGEMENTS_FROM)}; cases closed before then are not included.")  # fmt: skip
        exemption = (self.transposition_checks.get(a.celex) or {}).get("exemption")
        return {
            "celex": a.celex, "act": act_label(a), "deadline": deadline, "countries": countries,
            "nim_url": f"https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:{a.celex}",
            "source": _src(a.source), "note": note,
            # Denmark/Ireland without measures where neither the recitals nor a Council vote say whether they are bound
            "participation_unknown": [c for c in ("DK", "IE") if not self.participation_recorded(a.celex, c)],
            **({"infringements_from": INFRINGEMENTS_FROM} if older else {}),
            # the directive's own exemption from transposition (data/curated/transposition.yaml), quoted; `named`: the
            # countries it exempts from some provisions only (Directive (EU) 2016/797, Art. 57(5)), rows unchanged
            **({"exemption": {k: exemption.get(k) for k in ("provision", "quote", "countries", "named")}}
               if exemption else {}),
        }  # fmt: skip

    def schengen_note(self, celex: str, country: str) -> tuple[str, str | None] | None:
        """For Denmark, not bound by a directive that builds upon the Schengen acquis: that it decides under Article 4
        of Protocol No 22 whether to implement it in its national law, or its decision, as notified to the Council
        (data/curated/denmark_schengen.yaml), with the notification's URL. Directive (EU) 2023/977, recital 40; Denmark
        notified on 9 November 2023 that it had decided to implement it (ST 15298/23)."""
        oo = self.optouts.get(celex)
        e = self.denmark_schengen.get(celex)
        if country != "DK" or not oo or "DK" not in oo.schengen_art4:
            return None
        if not e:
            return ("It builds upon the Schengen acquis: under Article 4 of Protocol No 22, Denmark decides whether to "
                    "implement it in its national law.", None)  # fmt: skip
        when = f"as it notified the Council on {_long_date(e['notified'])} ({e['document']})"
        if e["decision"] == "implement":
            return (f"Denmark decided to implement it in its national law under Article 4 of Protocol No 22, {when}: an "
                    "obligation under international law, not under EU law.", e["url"])  # fmt: skip
        return f"Denmark decided not to implement it in its national law under Article 4 of Protocol No 22, {when}.", e["url"]

    def not_required_note(self, celex: str) -> str | None:
        """What a country row marked not_required rests on: "Art. 33(4): for as long as no rail system is established
        within its territory (...)", "Art. 40: the directive is not addressed to it" (data/curated/transposition.yaml,
        exemption `country_note`)."""
        ex = (self.transposition_checks.get(celex) or {}).get("exemption") or {}
        if not ex.get("countries"):
            return None
        return f"{ex['provision']}: {_squash(ex['country_note'])}" if ex.get("country_note") else ex["provision"]

    def with_recorded_events(self, p: Procedure) -> Procedure:
        """The procedure with official facts that its EP/OEIL record lacks: a Commission withdrawal or
        replacement recorded by Cellar on the procedure (OEIL often never adds it), and Parliament's
        rejection when a final plenary vote on the file was officially recorded as rejected."""
        have = {e.kind for e in p.events}
        extra: list[Event] = []
        notices = sorted(self.notices_by_ref.get(norm_ref(p.reference), []), key=lambda n: n.date)
        # A notice does not end a procedure that went on to adopt the act: 2010/0095(COD) has a Cellar withdrawal
        # notice of 7 March 2015, then Directive (EU) 2015/1535 adopted by the Council on 13 July 2015
        if notices:
            acts = self.acts_of.get(p.id, [])
            relevant = _lazy("pipeline.analysis.status", "relevant_acts")
            if acts and relevant is not None:
                acts = relevant(p, acts, sorted(p.events, key=lambda e: e.date), date.fromisoformat(self.today))
            if (p.stage_raw or "").startswith("Procedure completed") or p.celex_refs or acts:
                notices = []
        notices = [n for n in notices if not any(e.date > n.date and (e.kind in ADOPTION_EVENT_KINDS or (
            e.raw_type or "").endswith("PLENARY_APPROVE_COUNCIL_POSITION")) for e in p.events)]  # fmt: skip
        withdrawn = [e for e in p.events if e.kind == EventKind.withdrawal]
        first_proposal = min((e.date for e in p.events if e.kind == EventKind.proposal), default=None)
        drop: set[str] = set()
        if notices and withdrawn and (notices[0].kind == "replaced" or any(
                first_proposal and e.date < first_proposal for e in withdrawn)):  # fmt: skip
            # Cellar's notice replaces OEIL's withdrawal when it records the new proposal (RPL_byCOM) or when
            # OEIL's date precedes the proposal itself (2018/0213(COD): OEIL 28 May 2018, proposal 31 May 2018,
            # Cellar RPL_byCOM 28 May 2020)
            drop = {e.id for e in withdrawn}
            have.discard(EventKind.withdrawal)
        if notices and EventKind.withdrawal not in have:
            n = notices[0]
            replaced = n.kind == "replaced"
            extra.append(Event(
                id=f"cellar-{n.id}", date=n.date, kind=EventKind.withdrawal,
                raw_type="cellar:RPL_byCOM" if replaced else "cellar:WDW_byCOM", institution="Commission",
                title="Commission withdrew the proposal and replaced it with a new one" if replaced
                else "Commission withdrew the proposal",
                detail=f"New proposal: {n.document}" if replaced and n.document else None,
                docs=[DocRef(id=n.document, label=n.document, kind="proposal")] if replaced and n.document else [],
                source=n.source,
            ))  # fmt: skip
        # OEIL stages after Parliament's first reading that a rejection would contradict. "Awaiting Council's 1st
        # reading position" does not: OEIL shows it after a first-reading rejection too (SIOFA 2022/0348(COD),
        # adopted text TA-9-2023-0265 "Rejects the Commission proposal").
        past_parliament = (p.stage_raw or "").startswith(("Awaiting Parliament 2nd", "Awaiting Council's 2nd",
                                                           "Awaiting signature", "Procedure completed"))  # fmt: skip
        if EventKind.rejection not in have and not past_parliament:
            for v in sorted(self.votes_of.get(p.id, []), key=lambda v: (v.date, v.id)):
                # a rejected final vote, or an adopted motion to reject the proposal (2023/0413(COD), vote 179804:
                # "Proposal for rejection" adopted 370-264-9; TA-10-2025-0240 "Rejects the Commission proposal")
                rejects = (v.kind == "final" and v.outcome == "rejected") or (
                    v.kind_detail == "reject_proposal" and v.outcome == "adopted")  # fmt: skip
                if rejects and getattr(v, "outcome_basis", None) in ("published", "minutes"):
                    extra.append(Event(
                        id=f"vote-{v.id}-rejected", date=v.date, kind=EventKind.rejection,
                        raw_type="ep_vote:final:rejected" if v.kind == "final" else "ep_vote:reject_proposal:adopted",
                        institution="EP",
                        title="Parliament rejected the proposal in a plenary vote", source=v.source,
                    ))  # fmt: skip
                    break
        # a plenary vote that OEIL does not record yet (it lags by days): Parliament's position / mandate
        official = [v for v in self.votes_of.get(p.id, []) if v.outcome == "adopted" and v.date <= self.today
                    and getattr(v, "outcome_basis", None) in ("published", "minutes")]  # fmt: skip
        adopts = _lazy("pipeline.analysis.status", "parliament_adopts")
        ep_act = bool(adopts and adopts(p, self.acts_of.get(p.id, [])))  # Parliament adopts, the Council consents
        events = [self.procedure_event(p, e, ep_act) for e in p.events if e.id not in drop]
        for vkind, ekind in (("final", EventKind.ep_position), ("mandate", EventKind.negotiation_mandate)):
            vs = sorted((v for v in official if v.kind == vkind), key=lambda v: (v.date, v.id))
            # (as titled for the procedure: a consultation's PLENARY_AMEND decision is its opinion)
            if vs and not past_parliament and not any(e.kind == ekind and e.date >= vs[-1].date for e in events):
                v = vs[-1]
                title = {
                    EventKind.negotiation_mandate: "Parliament voted to open negotiations with the Council",
                    EventKind.ep_position: {"CNS": "Parliament delivered its opinion in a plenary vote",
                                            "APP": "Parliament adopted a text in a plenary vote" if ep_act
                                            else "Parliament voted on consent"}.get(
                        p.type, "Parliament adopted its position in a plenary vote"),
                }[ekind]  # fmt: skip
                extra.append(Event(
                    id=f"vote-{v.id}-{ekind.value}", date=v.date, kind=ekind, raw_type=f"ep_vote:{vkind}:adopted",
                    institution="EP", title=title, source=v.source,
                ))  # fmt: skip
        # A final vote followed by a referral back to committee (a "mandate" vote): Parliament voted amendments
        # but did not adopt its first-reading position, even where the EP API already records one (2025/0393(COD),
        # 6 October 2026: PLENARY_AMEND_PROPOSAL, vote 197467, then the referral back in the same vote item); nor,
        # in consultation or consent, its opinion or decision
        referred = {v.date for v in official if v.kind == "mandate"} if p.type in ("COD", "CNS", "APP") else set()
        amended = ("/PLENARY_AMEND_PROPOSAL", "/PLENARY_ADOPT_POSITION") if p.type == "COD" else ("/PLENARY_AMEND",)
        events = [
            e.model_copy(update={"kind": EventKind.plenary_vote, "title": "Parliament voted amendments to the proposal"})
            if e.kind == EventKind.ep_position and e.date in referred and (e.raw_type or "").endswith(amended)
            else e
            for e in events
        ]  # fmt: skip
        if (cd := self.checked_council_date(p)) is not None:  # the Council's decision as the act's text dates it
            events = self.council_step_dated(events, cd)
        if not extra and events == p.events:
            return p
        return p.model_copy(update={"events": sorted([*events, *extra], key=lambda e: (e.date, e.id))})

    @staticmethod
    def procedure_event(p: Procedure, e: Event, parliament_adopts: bool = False) -> Event:
        """Titles that fit the procedure: readings exist only in the ordinary legislative procedure,
        consent is not consultation, and a Council text submitted to Parliament is not a Commission
        proposal. The documents say who acted (OEIL files a COM proposal of a consent file as a "Preparatory
        document" of the Council). Parliament's decision in an interim or accompanying report (R/M
        procedure), or an earlier decision in a consent file, is a resolution, not its consent. When
        Parliament adopts the act itself (`parliament_adopts`, Articles 223(2) and 228(4) TFEU), the
        Council gives its consent."""
        title, inst, kind = e.title, e.institution, e.kind
        ids = [d.id for d in e.docs]
        report = PARLIAMENT_REPORT_RE.fullmatch(p.id)
        if p.type == "APP" and _plenary_decision(e) and (
            report or any(_plenary_decision(x) and x.date > e.date for x in p.events)
        ):
            # 2017/0333R(APP) "Interim report under consent procedure", 2023/0201M(APP) "Motion for a resolution
            # under consent procedure" (OEIL); 2013/0255(APP): interim resolutions of 2014 and 2015, consent in 2017
            title, kind = "Parliament adopted an interim resolution", EventKind.ep_position  # its plenary decision
            if report and report.group(2) == "M":
                title = "Parliament adopted a resolution accompanying the consent procedure"
        elif p.type in ("CNS", "APP"):
            if _plenary_decision(e) and kind != EventKind.ep_position and "-DEC-" in e.id:
                # Parliament's decision at the sitting, recorded by the EP API as PLENARY_AMEND (OEIL: "Decision by
                # Parliament"): its opinion, 2018/0173(CNS) T8-0415/2018 "Approves the Commission proposal as
                # amended", or its decision on consent, 2011/0436(APP) T7-0462/2013 "Consents to the draft"
                title, kind = "Parliament took its decision (first reading)", EventKind.ep_position
            if title == "Parliament took its decision (first reading)" and p.type == "CNS":
                title = "Parliament delivered its opinion"
            elif title == "Parliament took its decision (first reading)" and not parliament_adopts:
                title = "Parliament voted on consent"
            elif title == "Parliament took its decision (first reading)":
                consented = any(x.kind == EventKind.council_adoption and x.date <= e.date for x in p.events)
                title = "Parliament adopted the act" if consented else "Parliament adopted its proposal for the act"
            title = SPECIAL_PROCEDURE_TITLES.get(title, title).replace(" (first reading)", "")
        if p.type == "APP" and title == "Council adopted the act after consulting Parliament":
            title = "Council gave its consent" if parliament_adopts else "Council adopted the act after Parliament's consent"
        codes = {(x.raw_type or "").rsplit("/", 1)[-1] for x in p.events}
        if title == "Council approved Parliament's second-reading position" and (
            "PLENARY_APPROVE_COUNCIL_POSITION" in codes and "PLENARY_AMEND_COUNCIL_POSITION" not in codes
        ):
            # Parliament approved the Council's position unamended, which adopted the act (Art. 294(7)(a) TFEU);
            # OEIL still lists "Act approved by Council, 2nd reading", dated on the signature day
            title = "Recorded by the Legislative Observatory: “Act approved by Council, 2nd reading”"
            inst, kind = "OEIL", EventKind.other
        detail = e.detail
        if p.type == "COD" and e.raw_type == "oeil:Act adopted by Council after Parliament's 1st reading" and (second := sorted(
            x.date for x in p.events if x.date > e.date and SECOND_READING_DECISION_RE.search(x.raw_type or "")
        )):  # fmt: skip
            # a second reading followed, on the Council's first-reading position (Art. 294(5) to (7) TFEU): the Council
            # did not adopt the act after Parliament's first reading (2018/0202(COD): OEIL 21 April 2021, the day of
            # "Council position published"; Regulation (EU) 2021/691: "position of the Council at first reading of
            # 19 April 2021 ... Position of the European Parliament of 27 April 2021")
            title = "Recorded by the Legislative Observatory: “Act adopted by Council after Parliament's 1st reading”"
            inst, kind = "OEIL", EventKind.other
            detail = (f"Not the adoption of the act: Parliament decided on the Council's first-reading position at "
                      f"second reading on {_long_date(second[0])} (Article 294(5) to (7) TFEU).")  # fmt: skip
        if e.kind == EventKind.proposal or e.raw_type == "oeil:Preparatory document":
            prop = e.kind == EventKind.proposal
            known = next((OEIL_PROPOSAL_AUTHORS[i] for i in ids if i in OEIL_PROPOSAL_AUTHORS), None)
            if any(i.startswith("COM(") for i in ids):
                if not prop:  # the Commission's proposal for the Council act (consent files)
                    title, inst, kind = "Commission published its proposal", "Commission", EventKind.proposal
            elif any(EP_TEXT_RE.fullmatch(i) for i in ids):  # a text adopted by Parliament
                if not prop and e.date == parliament_proposal_day(p):  # Parliament's own proposal for the act
                    prop, kind = True, EventKind.proposal
                title = "Parliament adopted its proposal for the act" if prop else "Parliament adopted a text in plenary"
                inst = "EP"
            elif prop and e.date == parliament_proposal_day(p):
                # OEIL's "Legislative proposal published" of the day of Parliament's proposal, under a Council number
                # (2022/0902(APP): 00129/2022, the number of Parliament's text T9-0129/2022). No Council text was
                # submitted to Parliament: the Council received Parliament's proposal (ST 9333/22, 19 May 2022)
                title = "Recorded by the Legislative Observatory: “Legislative proposal published”"
                inst, kind = "OEIL", EventKind.other
            elif known:
                title, inst = known
            elif prop and e.institution == "CJEU":
                pass  # the Court's request, as OEIL's documentation gateway names it (ep_procedures)
            elif prop and p.type == "COD" and any(re.fullmatch(r"\d{5}/\d{2,4}", i) for i in ids):
                # the Council does not initiate an ordinary procedure: a Council document there is the initiative
                # of Member States or the recommendation of the ECB (Art. 294(15) TFEU), which our record does not
                # name (2017/0810(COD)); Member States' initiative where OEIL's title names it (ep_procedures:
                # 2010/0817(COD), 09288/2010, "Initiative Belgium, Bulgaria, Estonia, Spain, Austria, Slovenia and
                # Sweden"; Directive 2014/41/EU "Having regard to the initiative of the Kingdom of Belgium, …")
                title, inst = "Legislative proposal published (as recorded by the Legislative Observatory)", "OEIL"
                if (e.detail or "").startswith("Initiative "):
                    title = "Member States' initiative published (as recorded by the Legislative Observatory)"
                    detail = f"The Legislative Observatory names it: “{e.detail}”."
            elif any(re.fullmatch(r"\d{5}/\d{2,4}", i) for i in ids):
                title = "Council text submitted to Parliament" if prop else "Council preparatory document published"
                inst = "Council"
                if prop and p.type == "CNS" and not p.com_refs:
                    # the Council consults Parliament on a text it need not have drafted: the ECB's recommendation
                    # (2025/0806(CNS), 09737/2025: ST 9737/25, cover note from the President of the ECB, "Recommendation
                    # for a Council Regulation … (ECB/2025/17)"; Art. 129(4) TFEU), the EIB's request (Art. 308 TFEU)
                    title = "Text submitted to Parliament by the Council"
                if prop and p.type == "NLE":
                    # the Council's request for Parliament's consent or opinion, not the proposal it acts on
                    # (2008/0027(NLE): 13395/2014; Council Decision (EU) 2016/1218, "Having regard to the proposal
                    # from the European Commission"), so it does not date the proposal
                    kind = EventKind.other
            elif any(re.match(r"N\d+-", i) for i in ids) or not prop:  # the author is not in our record
                what = "Legislative proposal" if prop else "Preparatory document"
                title, inst = f"{what} published (as recorded by the Legislative Observatory)", "OEIL"
        if (title, inst, kind, detail) == (e.title, e.institution, e.kind, e.detail):
            return e
        return e.model_copy(update={"title": title, "institution": inst, "kind": kind, "detail": detail})

    def adoption_dates(self, p: Procedure, acts: list[LegalAct]) -> tuple[str | None, str | None]:
        """(adopted, published), with the Council's steps dated as the timeline shows them. In the ordinary
        procedure the act is adopted when Parliament approves the Council's position at second reading (Art.
        294(7)(a) TFEU; OEIL's later "Act approved by Council, 2nd reading" is the signature day), else when
        the Council adopts it or approves Parliament's position: the date of the Council's adopted voting
        result on the act, else OEIL's Council step. A Council act (consultation, consent) is dated by that
        voting result, else by the act itself, which bears its adoption date (OEIL's Council date can
        contradict it). An act that Parliament adopts with the Council's consent is dated by Parliament's
        decision. Without such a step, the act's own date (EUR-Lex date of the document: its adoption or,
        for acts of Parliament and Council, signature date), then a recorded signature. Never the
        publication date, and never a date after publication."""
        t = self.today
        p = self.council_dated(p)
        approved = sorted(e.date for e in p.events if e.date <= t and (e.raw_type or "").endswith(
            "PLENARY_APPROVE_COUNCIL_POSITION"))  # fmt: skip
        votes = sorted(cv["date"] for cv in self.council_of.get(p.id, [])
                       if cv["date"] <= t and cv.get("vote_on") == "act" and cv["outcome"] == "adopted")  # fmt: skip
        council = sorted(e.date for e in p.events if e.kind == EventKind.council_adoption and e.date <= t)
        docs = sorted(a.date_document for a in acts if a.date_document and a.date_document <= t)
        sigs = sorted(e.date for e in p.events if e.kind == EventKind.signature and e.date <= t)
        pubs = sorted(a.date_publication for a in acts if a.date_publication and a.date_publication <= t)
        pubs = pubs or sorted(e.date for e in p.events if e.kind == EventKind.publication and e.date <= t)
        published = pubs[0] if pubs else None
        adopts = _lazy("pipeline.analysis.status", "parliament_adopts")
        if adopts and adopts(p, acts):  # Parliament's decision after the Council's consent
            ep = [e.date for e in p.events if e.kind == EventKind.ep_position and e.date <= t
                  and any(c <= e.date for c in votes + council)]  # fmt: skip
            cands = [ep[-1:], docs[:1]]
        elif p.type in ("COD", "SYN"):
            cands = [approved[-1:], votes[-1:], council[-1:], docs[:1], sigs[:1]]
        else:
            cands = [votes[-1:], docs[:1], council[-1:], sigs[:1]]
        adopted = next((c[0] for c in cands if c and (not published or c[0] <= published)), None)
        return adopted, published

    def checked_council_date(self, p: Procedure) -> dict | None:
        """The Council's adoption of the file's act as dated by the act's own text (load_council_dates), when that
        act is one of the file's."""
        e = self.council_dates.get(norm_ref(p.reference))
        if e and not any(a.celex == e["celex"] for a in self.acts_of.get(p.id, [])):
            log.warning("curated council_dates.yaml: %s is not an act of %s; ignored", e["celex"], p.reference)
            return None
        return e

    def council_step_dated(self, events: list[Event], cd: dict) -> list[Event]:
        """The Legislative Observatory's Council adoption step nearest to the date the act's text gives for the
        Council's decision (data/curated/council_dates.yaml), moved to that date and citing the act. The act records
        one decision of the Council: OEIL's other adoption steps of the file near that date are the same adoption and
        are merged into it (2014/0174(COD): OEIL 13 July and 6 October 2015, "decision of the Council of 18 September
        2015", Regulation (EU) 2015/1843)."""
        steps = [e for e in events if e.kind == EventKind.council_adoption and (e.raw_type or "").startswith("oeil:")
                 and abs(_days_between(e.date, cd["date"])) <= 92]  # fmt: skip
        step = min(steps, key=lambda e: abs(_days_between(e.date, cd["date"])), default=None)
        merged = [e for e in steps if e is not step]
        events = [e for e in events if not any(e is m for m in merged)]
        if step is None or all(e.date == cd["date"] for e in steps):
            return events
        a = self.act[cd["celex"]]
        doc = DocRef(id=a.celex, label=a.oj_ref or a.celex, kind="act", date=a.date_document, url=a.eurlex_url)
        oeil = [_long_date(d) for d in sorted({e.date for e in steps})]
        given = oeil[0] if len(oeil) == 1 else f"{', '.join(oeil[:-1])} and {oeil[-1]}"
        detail = (f"Date of the Council's decision in the text of {act_label(a)}: “{_squash(cd['quote'])}” "
                  f"The Legislative Observatory gives {given}.")  # fmt: skip
        docs = [*step.docs, *(d for m in merged for d in m.docs), doc]
        dated = step.model_copy(update={"date": cd["date"], "detail": detail, "docs": docs})
        return [dated if e is step else e for e in events]

    @staticmethod
    def proposal_date(p: Procedure) -> str | None:
        """Date of the proposal: the earliest recorded proposal (Commission, Council text submitted to
        Parliament, Parliament's own proposal) or COM document of the procedure, so that a Commission proposal
        recorded only as a document still dates a consent file whose Council draft came later. Not the first
        event of another kind (a referral or committee step is not the proposal)."""
        props = [e.date for e in p.events if e.kind == EventKind.proposal]
        coms = [d.date for d in p.documents if d.id.startswith("COM(") and d.date]
        return min(props + coms, default=None)

    def council_dated(self, p: Procedure) -> Procedure:
        """For the status: OEIL's Council steps dated by the Council's own voting results (OEIL dates the
        first-reading position by its publication, days after the vote), as the timeline shows them."""
        cvotes = [cv for cv in self.council_of.get(p.id, []) if cv["date"] <= self.today and cv["outcome"] == "adopted"]
        positions = sorted(cv["date"] for cv in cvotes if cv.get("vote_on") == "first_reading_position")
        acts = sorted(cv["date"] for cv in cvotes if cv.get("vote_on") == "act")
        events = []
        for e in p.events:
            dates = positions if e.kind == EventKind.council_position else acts if e.kind == EventKind.council_adoption else []
            earlier = [d for d in dates if d <= e.date and (date.fromisoformat(e.date) - date.fromisoformat(d)).days <= 31]
            events.append(e.model_copy(update={"date": earlier[-1]}) if earlier and e.institution == "Council" else e)
        return p if events == p.events else p.model_copy(update={"events": events})

    def build_dossiers(self) -> None:
        self.dossier_summary: dict[str, dict] = {}
        self.dossier_detail: dict[str, dict] = {}
        self.notices_by_ref: dict[str, list[ProcedureNotice]] = defaultdict(list)
        for n in self.s.notices:
            self.notices_by_ref[norm_ref(n.reference)].append(n)
        relevant = _lazy("pipeline.analysis.status", "relevant_acts")
        self.dossier_acts: dict[str, list[LegalAct]] = {}
        self.proposed_type: set[str] = set()  # files whose type of act is the one proposed (no typed act linked)
        self.index_file_documents()
        for pid in self.dossier_ids:
            p = self.proc[pid] = self.with_recorded_events(self.proc[pid])
            acts = self.acts_of.get(pid, [])
            if relevant is not None:  # an act EUR-Lex links to several procedures needs evidence it is this one's
                t = date.fromisoformat(self.today)
                acts = relevant(p, acts, sorted((e for e in p.events if e.date <= self.today), key=lambda e: e.date), t)
            self.dossier_acts[pid] = acts
            votes = sorted(
                self.votes_of.get(pid, []) + self.parent_negotiation_votes(p), key=lambda v: (v.date, v.id), reverse=True
            )
            st = self.classify(p)
            tl = mark_after_end_of_validity(self.joint_debates(p, self.timeline(p, acts, votes)), acts)
            cur = self.curated_of.get(pid)
            done = [e for e in tl if e["state"] == "done" and not e.get("after_end_of_validity")]
            instrument = None
            for a in acts:
                if a.act_type != "other":
                    instrument = a.act_type
                    break
            else:  # no adopted act of a known type: the type of act proposed
                instrument = proposed_instrument(p)
                if instrument:
                    self.proposed_type.add(pid)
            instrument = instrument or instrument_from_title(p.title)
            adopted, published = self.adoption_dates(p, acts)
            fut = sorted(
                d
                for a in acts
                for d in [
                    *a.other_application_dates,
                    *(x.date for x in classify_transposition(a) if x.kind != "other"),
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
                # a split parent known only from EUR-Lex has no title of its own in the sources (its name says
                # what it was split into): none is shown as its official title
                "official_title": None if pid in self.stub_ids and self.split_children.get(pid)
                else self.adopted_title(p) or p.title,
                "short": (cur or {}).get("what") or None,
                "topics": self.topics_for(p),
                "stage": st["status"].get("stage", "unknown"),
                "status_label": st["status"].get("label") or STAGE_LABELS.get(st["status"].get("stage"), ""),
                "started": self.proposal_date(p),
                "last_event": done[-1]["date"] if done else None,
                "adopted": adopted,
                "published": published,
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
            rapps = self.rapporteur_entries(p)
            # the procedure record: the human-readable OEIL file first, the API's JSON-LD labelled as data
            psrc = _src(p.source)
            sources = []
            oeil = self.oeil_link(pid)
            if psrc and oeil and pid not in self.stub_ids:
                sources.append({**psrc, "institution": "OEIL", "url": oeil,
                                "label": f"Legislative Observatory (OEIL) – procedure file {p.reference}"})  # fmt: skip
                if "data.europarl.europa.eu" in (psrc.get("url") or ""):
                    psrc = {**psrc, "label": f"Machine-readable data (EP Open Data API) – procedure {p.reference}"}
            if self.split_children.get(pid):
                # a proposal split into separate files: their procedure files, not the EUR-Lex record of one part's act
                # that a parent known only from EUR-Lex was built from (2016/0400(COD): Regulation (EU) 2019/1243, the
                # act of 2016/0400A(COD))
                if pid not in self.stub_ids:
                    sources.append(psrc)
                sources += [{**_src(self.proc[c].source), "institution": "OEIL", "url": url,
                             "label": f"Legislative Observatory (OEIL) – procedure file {self.proc[c].reference} "
                                      "(separate file)"}
                            for c in self.split_children[pid] if (url := self.oeil_link(c))]  # fmt: skip
            else:
                sources += [psrc] + [_src(a.source) for a in acts]
            sources += [_src(t.source) for t in self.train_of.get(pid, [])]
            sources = _dedupe_sources(sources)
            tables = self.implementations(acts)  # national implementation, one table per directive
            det = {
                **summ,
                "known_as": self.known_as(p, acts),
                "editorial": editorial,
                **{k: st[k] for k in ("status", "next_step", "stall", "application")},
                "timeline": tl,
                "acts": [self.act_summary(a) for a in acts],
                "ep_votes": [self.vote_summary[v.id] for v in votes if v.id in self.vote_summary],
                "ep_approval_without_vote": self.approval_without_vote(p, tl, votes),
                "council_votes": self.council_of.get(pid, []),
                **({"council_votes_in_parts": self.council_in_parts[pid]} if pid in self.council_in_parts else {}),
                "implementation": tables[0] if tables else None,
                **({"implementation_more": tables[1:]} if len(tables) > 1 else {}),
                "committees": [{"code": c.code, "name": c.name, "role": c.role, **({"former": True} if c.former else {})}
                               for c in p.committees],  # fmt: skip
                "rapporteurs": rapps,
                "documents": [d.model_dump(mode="json") for d in p.documents],
                "related": [],
                "oeil_url": oeil,
                # built from the EUR-Lex act alone: the procedure's own steps are not in our data
                "eurlex_only": pid in self.stub_ids and pid not in self.split_children,
                "sources": [x for x in sources if x],
                "changes": [],
            }
            if det["application"] is None:
                det["application"] = self.application_info(acts)
            elif any(a.celex in self.act_dates for a in acts):  # dates checked against the act's text
                info = self.application_info(acts) or {}
                det["application"] |= {k: info.get(k) for k in ("application_detail", "dates_note")}
            later = [a for a in acts if a.other_application_dates]
            if later and all((self.act_dates.get(a.celex) or {}).get("application") is not None for a in later):
                # the later dates are those of the act's text (data/curated/act_dates.yaml), not EUR-Lex's record
                det["status"]["explanation"] = det["status"]["explanation"].replace(
                    EURLEX_LATER_DATES, "the act's text sets later dates from which (parts of) the act apply."
                )
            det["next_step"] = self.derived_next_step(det)
            det["next_step"] = self.amending_deadlines(det, acts)
            self.dossier_detail[pid] = det
        # officially established relations between dossiers (act amends/repeals another dossier's act)
        # a partial repeal is EUR-Lex's classification of the link, which the repealing act's text need not state
        # (Decision (EU) 2024/867, Art. 6: Decision (EU) 2020/1531 "remains applicable to the extent referred to in
        # Article 5(2)")
        rels = (("amends", "Amends"), ("repeals", "Repeals"), ("repealed_by", "Repealed by"),
                ("partly_repeals", "Partly repeals (EUR-Lex)"),
                ("partly_repealed_by", "Partly repealed by (EUR-Lex)"))  # fmt: skip
        # the inverse of a recorded "amends"/"repeals" is the same official fact
        inv_amended: dict[str, set[str]] = defaultdict(set)
        inv_repealed: dict[str, set[str]] = defaultdict(set)
        inv_partly: dict[str, set[str]] = defaultdict(set)
        for a in self.s.acts:
            for c in a.amends:
                inv_amended[c].add(a.celex)
            for c in a.repeals:
                inv_repealed[c].add(a.celex)
            for c in a.partly_repeals:
                inv_partly[c].add(a.celex)
        # an act belongs to the dossiers whose own record supports it (see status.relevant_acts)
        self.act_dossiers = defaultdict(set)
        for pid, acts in self.dossier_acts.items():
            for a in acts:
                self.act_dossiers[a.celex].add(pid)
        # proposals the Commission replaced by a new one (Cellar RPL_byCOM) -> the new proposal's file
        by_proposal: dict[str, str] = {}
        for pid in self.dossier_ids:
            for d in self.proc[pid].documents:
                if d.kind == "proposal" and d.id.startswith("COM("):
                    by_proposal.setdefault(d.id, pid)
        replaced_by: dict[str, str] = {}
        for pid in self.dossier_ids:
            for e in self.proc[pid].events:
                if e.raw_type == "cellar:RPL_byCOM":
                    new = next((d.id for d in e.docs if d.id in by_proposal and by_proposal[d.id] != pid), None)
                    if new:
                        replaced_by[pid] = by_proposal[new]
        replaces: dict[str, list[str]] = defaultdict(list)
        for old, new in replaced_by.items():
            replaces[new].append(old)
        # dates an amending act set for another act: a date's own source in data/curated/act_dates.yaml
        dates_set_by: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
        for base, e in self.act_dates.items():
            for i, s in enumerate(e.get("sources") or []):
                c = s.get("celex") if isinstance(s, dict) else None
                ds = sorted(x["date"] for x in e.get("application") or [] if x.get("source", 0) == i)
                if c and c != base and ds:
                    dates_set_by[c].append((base, ds))
        for pid, det in self.dossier_detail.items():
            for ref in det["status"].get("named_acts") or []:  # an act the status names: its file, when we have one
                if not ref["celex"]:
                    continue  # a procedure (split parts, the main file of a report): linked to its own file
                files = sorted(o for o in self.act_dossiers.get(ref["celex"], ()) if o != pid)
                ref["dossier"] = files[0] if files else None
            related: dict[str, dict] = {}
            if pid in replaced_by:
                new = replaced_by[pid]
                related[f"replaced_by:{new}"] = {
                    "id": new, "title": _truncate(self.dossier_summary[new]["title"], 160), "relation": "Replaced by",
                }  # fmt: skip
            for old in sorted(replaces.get(pid, [])):
                related[f"replaces:{old}"] = {
                    "id": old, "title": _truncate(self.dossier_summary[old]["title"], 160), "relation": "Replaces",
                }  # fmt: skip
            for a in self.dossier_acts.get(pid, []):
                # one item per amending act: its dossier when known, else the act itself (id = CELEX)
                for c in sorted(set(a.amended_by) | inv_amended.get(a.celex, set())):
                    others = sorted(o for o in self.act_dossiers.get(c, ()) if o != pid)
                    if others:
                        for other in others:
                            related.setdefault(f"amended_by:{other}", {
                                "id": other, "title": self.related_act_title(c, other), "relation": "Amended by",
                            })  # fmt: skip
                    elif c not in self.act_dossiers:
                        related.setdefault(f"amended_by:{c}", {
                            "id": c, "title": self.related_act_title(c, None), "relation": "Amended by",
                        })  # fmt: skip
                for attr, label in rels:
                    extra = {"repealed_by": inv_repealed, "partly_repealed_by": inv_partly}.get(attr, {}).get(a.celex, set())
                    for c in sorted(set(getattr(a, attr)) | extra):
                        for other in sorted(self.act_dossiers.get(c, ())):
                            if other != pid:
                                related.setdefault(f"{attr}:{other}", {
                                    "id": other, "title": self.related_act_title(c, other, topic=True), "relation": label,
                                })  # fmt: skip
            for child in self.split_children.get(pid, []):
                related.setdefault(f"split:{child}", {
                    "id": child, "title": _truncate(self.dossier_summary[child]["title"], 160), "relation": "Split into",
                    "ref": self.dossier_summary[child]["ref"], "status_label": self.dossier_summary[child]["status_label"],
                })  # fmt: skip
            # a report and its main file have the same title: their links also give the procedure reference
            if (m := PARLIAMENT_REPORT_RE.fullmatch(pid)) and m.group(1) in self.dossier_summary:
                related.setdefault(f"report_on:{m.group(1)}", {
                    "id": m.group(1), "title": _truncate(self.dossier_summary[m.group(1)]["title"], 160),
                    "relation": "Report on", "ref": self.dossier_summary[m.group(1)]["ref"],
                })  # fmt: skip
            elif (m := re.fullmatch(r"(\d{4}-\d{4})[A-Z]", pid)) and m.group(1) in self.dossier_summary:
                related.setdefault(f"split_from:{m.group(1)}", {
                    "id": m.group(1), "title": _truncate(self.dossier_summary[m.group(1)]["title"], 160),
                    "relation": "Split from",
                })  # fmt: skip
            for rep, label in ((f"{pid}R", "Parliament's interim report"), (f"{pid}M", "Parliament's report")):
                if rep in self.dossier_summary:  # the R / M file of Parliament's report on this procedure
                    related.setdefault(f"report:{rep}", {
                        "id": rep, "title": _truncate(self.dossier_summary[rep]["title"], 160), "relation": label,
                        "ref": self.dossier_summary[rep]["ref"],
                    })  # fmt: skip
            order = {
                "Report on": 0,
                "Parliament's interim report": 0,
                "Parliament's report": 0,
                "Replaced by": 0,
                "Replaces": 0,
                "Split into": 0,
                "Split from": 0,
                "Amended by": 1,
                "Repealed by": 2,
                "Partly repealed by (EUR-Lex)": 2,
                "Amends": 3,
                "Repeals": 4,
                "Partly repeals (EUR-Lex)": 4,
            }
            det["related"] = sorted(related.values(), key=lambda r: (order.get(r["relation"], 9), r["id"]))
            dates_set = [
                {"id": other, "title": self.related_act_title(base, other), "dates": ds}
                for a in self.dossier_acts.get(pid, [])
                for base, ds in dates_set_by.get(a.celex, [])
                for other in sorted(self.act_dossiers.get(base, ()))
                if other != pid
            ]
            if dates_set:
                det["dates_set_for"] = dates_set
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
                                               "role": r.role, "committee": r.committee,
                                               **({"former": True} if r.former else {})})  # fmt: skip
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
            # EP open data has one record per party per parliamentary term: the terms this record covers
            terms = sorted({x.term for m, _s, _e in rows for x in m.memberships
                            if x.kind == "party" and x.org_id == oid and x.term})  # fmt: skip
            summ = {
                "id": oid, "label": o.label, "code": o.code, "country": o.country or "",
                "members_active": len(ongoing_ids), "members_total": len({m.id for m, _s, _e in rows}),
                "groups": sorted(gh), "terms": terms,
            }  # fmt: skip
            self.party_summary[oid] = summ
            if oid not in self.unnamed_parties:
                parties_out.append(summ)
            meps_rows: dict[str, dict] = {}
            for m, start, end in sorted(rows, key=lambda r: (r[0].id, r[1] or "")):
                r = meps_rows.setdefault(m.id, {"id": m.id, "name": m.name, "active": m.active and False,
                                                "from": start, "to": end})  # fmt: skip
                r["from"] = min(r["from"] or start or "", start or "") or None
                r["to"] = None if (end is None or r["to"] is None) else max(r["to"], end)
                r["active"] = m.id in ongoing_ids
                # `active`: still in this party record and sitting; the MEP's own status, and the party record a
                # sitting MEP is in now when it is another one (the same party's next-term record, or a new party)
                r["mep_active"] = m.active
                now = [other for _s, e, other in self.mep_parties.get(m.id, []) if e is None and other != oid]
                r["now_party"] = now[-1] if m.active and not r["active"] and now else None
            # memberships Parliament records in this party record outside the record's own period (corporate body
            # 5320 ends on 15 Jul 2024; Dan Nica's membership of it from 16 Jul 2024 has no end), said as such
            outside = [
                {"id": m.id, "name": m.name, "from": start, "to": end}
                for m, start, end in sorted(rows, key=lambda r: (r[1] or "", r[0].name, r[0].id))
                if (o.end and (end is None or end > o.end)) or (o.start and start and start < o.start)
            ]  # fmt: skip
            self.files[f"people/parties/{oid}.json"] = {
                **summ,
                "start": o.start, "end": o.end,
                **({"outside_period": outside} if outside else {}),
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
        # each party page links the records of the same name and country (the same party in other terms) and
        # the records its sitting MEPs are now in
        same_name: dict[tuple[str, str], list[str]] = defaultdict(list)
        for oid, summ in self.party_summary.items():
            if oid not in self.unnamed_parties:
                same_name[(_norm_key(summ["label"]), summ["country"])].append(oid)

        def ref(oid: str) -> dict:
            pt, o = self.party_summary[oid], self.org[oid]
            return {"id": oid, "label": pt["label"], "terms": pt["terms"], "start": o.start, "end": o.end,
                    "members_active": pt["members_active"]}  # fmt: skip

        for oid, summ in self.party_summary.items():
            f = self.files[f"people/parties/{oid}.json"]
            twins = [t for t in same_name.get((_norm_key(summ["label"]), summ["country"]), []) if t != oid]
            f["same_name"] = [ref(t) for t in sorted(twins, key=lambda t: (self.org[t].start or "", t))]
            now = Counter(r["now_party"] for r in f["meps"] if r["now_party"] in self.party_summary)
            f["now_parties"] = [ref(t) | {"meps": n} for t, n in sorted(now.items(), key=lambda kv: (-kv[1], kv[0]))]

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
        # each directive's own number as its official title cites it ("Directive (EU) 2022/2555", "Directive
        # 2014/35/EU") and the names its file is known by, so that a country page can be searched by them
        act_names: dict[str, tuple[str | None, list[str]]] = {}
        for a in directives:
            ds = sorted(self.act_dossiers.get(a.celex, ()))
            known = self.known_as(self.proc[ds[0]], self.acts_of.get(ds[0], [])) if len(ds) == 1 else None
            names = (known or {}).get("names") or ([n] if (n := act_short_name(a.title)) else [])
            act_names[a.celex] = (act_label(a) if act_label(a) != a.celex else celex_act_label(a.celex), names)
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
                    cvotes.append({"vote_id": cv["id"], "date": cv["date"], "title": cv["title"],
                                   "display_title": cv["display_title"], "pos": pos, "dossier_id": cv["dossier_id"],
                                   "vote_on": cv["vote_on"], "vote_on_label": cv["vote_on_label"], "stage": cv["stage"],
                                   "outcome": cv["outcome"]})  # fmt: skip
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
                title = self.dossier_summary[ds[0]]["title"] if len(ds) == 1 else a.title
                if len(ds) == 1 and sum(x.act_type == "directive" for x in self.dossier_acts.get(ds[0], [])) > 1:
                    title = f"{act_label(a)}: {title}"  # one of the file's directives (2013/0400(CNS) has two)
                status = self.transposition_status(a.celex, code, deadline)
                schengen = self.schengen_note(a.celex, code) if status == "not_participating" else None
                trans.append({
                    "celex": a.celex, "title": title,
                    "act": act_names[a.celex][0], "names": act_names[a.celex][1],
                    "dossier_id": ds[0] if len(ds) == 1 else None, "deadline": deadline,
                    "measures": len(self.measures_by.get((a.celex, code), [])),
                    "status": status,
                    # the exemption and its condition (Directive (EU) 2016/798, Art. 33(4)), not the bare label
                    **({"status_note": self.not_required_note(a.celex)} if status == "not_required" else {}),
                    # Denmark and a directive building upon the Schengen acquis (Protocol No 22, Art. 4)
                    **({"status_note": schengen[0], "status_note_url": schengen[1]} if schengen else {}),
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

        snapshot = activity.snapshot_entries(self)
        record = os.environ.get("EU_INTEL_RECORD_ACTIVITY") == "1"
        recorded = activity.update_state(self, self.state_dir, record=record)
        items = activity.merge(recorded, snapshot, today=self.today)
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
        """The latest recorded step, as the dossier page shows it ("Latest recorded step")."""
        done = [e for e in self.dossier_detail[pid]["timeline"] if e["state"] == "done" and e["date"] <= self.today
                and not e.get("after_end_of_validity")]  # fmt: skip
        return done[-1] if done else None

    def undated_amendments_note(self, pid: str) -> str | None:
        """The acts that EUR-Lex lists as amending the file's acts but that are not in our EUR-Lex data, so the
        timeline has no dated step for them (2021/0366(COD): Delegated Regulation (EU) 2026/2102). Said next to
        the latest step, which may be older than they are."""
        cs = sorted({c for a in self.dossier_acts.get(pid, []) for c in a.amended_by if c not in self.act})
        if not cs:
            return None
        names = [celex_act_label(c) or c for c in cs]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        one = len(cs) == 1
        return (f"EUR-Lex also lists {listed} as amending this act. {'That act is' if one else 'Those acts are'} not in "
                f"our data, so {'its' if one else 'their'} publication is not shown and the step above may not be the "
                "latest.")

    def home_rejection_note(self, v: dict) -> str:
        """What a rejection on the home "Rejected" list meant, in the words of the file's timeline where the vote
        is its decision, and what became of the file after it (2025/0429(COD): rejected at first reading on
        26 March 2026, adopted on 23 July 2026 after a second reading; 2025/0580(CNS): a negative opinion)."""
        d = self.dossier_summary.get(v["dossier_id"]) if v["dossier_id"] else None
        timeline = self.dossier_detail[d["id"]]["timeline"] if d else []
        decision = next((e["title"] for e in timeline if e.get("vote_id") == v["id"] and "rejected" in e["title"]), None)
        if v["outcome"] == "adopted":  # an adopted motion to reject
            note = v["outcome_note"] or v["kind_label"]
        else:
            note = f"{decision}." if decision else "Parliament rejected the text in this vote."
        if d is None:
            return v["outcome_note"] or note
        since = self.dossier_detail[d["id"]]["status"].get("since") or ""
        if d["stage"] in ADOPTED_STAGES and d["adopted"] and d["adopted"] > v["date"]:
            return f"{note} The procedure continued and the act was adopted on {_long_date(d['adopted'])}."
        if v["outcome_note"] and v["outcome"] == "rejected":
            return v["outcome_note"]  # a later act the file's dates do not show (later_act_note)
        if d["type"] == "CNS" and v["outcome"] == "rejected" and d["stage"] not in ADOPTED_STAGES:
            return (f"{note} Under the consultation procedure Parliament's opinion is not binding: the Council can "
                    "still adopt the act.")  # fmt: skip
        if since > v["date"] and d["stage"] != "rejected":
            return f"{note} Status now: {d['status_label']}."
        return note

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
                "latest_note": self.undated_amendments_note(pid),
                "next_step": det["next_step"], "source": _src(self.proc[pid].source),
                "oeil_url": self.oeil_link(pid),
            })  # fmt: skip
        today = self.today
        summ = self.dossier_summary
        # recently adopted, by the date of adoption (see adoption_dates: the Council's adoption or Parliament's
        # second-reading approval, otherwise the act's own date; never the publication date)
        adopted = sorted(
            (d for d in summ.values() if d["stage"] in ADOPTED_STAGES and d["adopted"] and d["type"] in LEGISLATIVE_TYPES),
            key=lambda d: (d["adopted"], d["id"]), reverse=True,
        )[:12]  # fmt: skip
        recently_adopted = [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                             "date": d["adopted"],  # the act's type; not the proposed one, which it can differ from
                             "badge": None if d["id"] in self.proposed_type else d["instrument"]} for d in adopted]  # fmt: skip
        debate = sorted(
            (d for d in summ.values() if d["stage"] in ACTIVE_STAGES and d["type"] in LEGISLATIVE_TYPES
             and d["last_event"] and _days_between(d["last_event"], today) <= 120),
            key=lambda d: (d["last_event"], d["featured"], d["id"]), reverse=True,
        )[:12]  # fmt: skip
        under_debate = [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                         "date": d["last_event"], "badge": HOME_PROCEDURE_BADGES.get(d["type"], d["type_label"])}
                        for d in debate]  # fmt: skip

        def badge(v: dict, text: str) -> str:
            # an outcome we calculated from the counts says so, as on the vote's page
            return f"{text} (calculated from the recorded counts)" if v.get("outcome_basis") == "derived" else text

        # A discharge decision grants, postpones or refuses discharge (Rules of Procedure, Annex V): its "adopted"
        # or "rejected" says nothing about the discharge without the proposal voted on, and it is not a law, so
        # it is in neither list of votes on texts below (vote 142787 rejected a proposal to postpone: discharge
        # was granted; 149084 adopted a refusal).
        from pipeline.analysis.activity import is_discharge_vote

        # close final votes as the /votes page defines them (CLOSE_RELATIVE), newest first; over all the votes
        # covered, as few final votes are that close (one in the 12 months to October 2026)
        close = [
            v for v in self.vote_summary.values()
            if v["kind"] == "final" and v.get("margin") and v["outcome"] in ("adopted", "rejected")
            and isinstance(v["margin"].get("relative"), (int, float)) and abs(v["margin"]["relative"]) <= CLOSE_RELATIVE
            and not is_discharge_vote(v)
        ]  # fmt: skip
        close.sort(key=lambda v: (v["date"], v["id"]), reverse=True)
        close_votes = [{"vote_id": v["id"], "dossier_id": v["dossier_id"], "title": v["display_title"],
                        "subtitle": v["margin"].get("label"), "date": v["date"], "badge": badge(v, v["outcome"])}
                       for v in close[:10]]  # fmt: skip
        # What Parliament rejected: final votes on a whole text that it rejected, and adopted motions to reject the
        # proposal or the Council's position (a rejected motion to reject is not a rejection by Parliament), each
        # leading to its file; then files recorded as rejected without such a vote. A rejected objection or motion
        # of censure leaves the Commission measure or the Commission in place, so neither is listed.
        rejecting = ("reject_proposal", "reject_council_position")
        rej_votes = [
            v
            for v in self.vote_summary.values()
            if ((v["kind_detail"] in rejecting and v["outcome"] == "adopted")
                or (v["kind"] == "final" and v["outcome"] == "rejected")) and not is_discharge_vote(v)
        ]
        rej_items = [{"vote_id": v["id"], "dossier_id": v["dossier_id"], "title": v["display_title"],
                      "subtitle": self.home_rejection_note(v), "date": v["date"], "badge": badge(v, "Rejected")}
                     for v in rej_votes]  # fmt: skip
        listed = {x["dossier_id"] for x in rej_items if x["dossier_id"]}
        rej_items += [{"dossier_id": d["id"], "title": d["title"], "subtitle": d["status_label"],
                       "date": self.dossier_detail[d["id"]]["status"].get("since") or d["last_event"], "badge": "Rejected"}
                      for d in summ.values() if d["stage"] == "rejected" and d["id"] not in listed]  # fmt: skip
        rej_items.sort(
            key=lambda x: (x["date"] or "", x.get("vote_id") or x.get("dossier_id") or ""), reverse=True
        )
        stalled_items = []
        for d in sorted(summ.values(), key=lambda d: d["id"]):
            if d["officially_blocked"]:
                stall = self.dossier_detail[d["id"]].get("stall") or {}
                label = stall.get("official_label")
                as_of = stall.get("official_label_date")
                sub = f"Legislative Train: {label}" if label else "Officially reported as blocked"
                stalled_items.append({"dossier_id": d["id"], "title": d["title"],
                                      "subtitle": sub + (f" (information updated as of {_long_date(as_of)})" if as_of else ""),
                                      "date": d["last_event"], "badge": "Officially blocked", "_o": 0,
                                      "_as_of": as_of or ""})  # fmt: skip
        # the most recently confirmed blockages first; of those, the longest without a recorded procedural step (the
        # date shown), as the inactive files below
        stalled_items.sort(key=lambda x: (x["date"] or "", x["dossier_id"]))
        stalled_items.sort(key=lambda x: x["_as_of"], reverse=True)
        n_blocked = len(stalled_items)
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
        # the home page shows six rows: both kinds, so that inactive files are visible too
        n_inactive = min(3, len(inactive))
        stalled_items = stalled_items[: 6 - n_inactive]
        n_blocked_shown = len(stalled_items)
        for n, d in inactive[:n_inactive]:
            stalled_items.append({"dossier_id": d["id"], "title": d["title"],
                                  "subtitle": f"No recorded procedural update in {n} days", "date": d["last_event"],
                                  "badge": d["status_label"], "_o": 1})  # fmt: skip
        for x in stalled_items:
            x.pop("_o", None)
            x.pop("_as_of", None)
        horizon = _add_days(today, 365)
        upcoming = []
        for pid in self.dossier_ids:
            for e in self.dossier_detail[pid]["timeline"]:
                if (
                    e["state"] == "scheduled"
                    and e["kind"] in ("application", "transposition_deadline", "transposition_application",
                                      "entry_into_force")
                    and today < e["date"] <= horizon
                    and not e.get("after_end_of_validity")
                ):
                    upcoming.append({"dossier_id": pid, "title": summ[pid]["title"], "subtitle": e["title"],
                                     "date": e["date"], "badge": "Deadline" if e["kind"] == "transposition_deadline"
                                     else "Applies"})  # fmt: skip
        upcoming.sort(key=lambda x: (x["date"], not summ[x["dossier_id"]]["featured"], x["dossier_id"]))
        lists = [
            {"id": "recently_adopted", "title": "Recently adopted",
             "description": "Laws formally adopted, newest first, by date of adoption (by the Council, or by "
                            "Parliament at second reading; otherwise the date of the act).",
             "items": recently_adopted},
            {"id": "under_debate", "title": "Under discussion",
             "description": "Legislative files with a recorded procedural step in the last 120 days that are not yet adopted.",
             "items": under_debate},
            {"id": "close_votes", "title": "Close votes",
             "description": "The most recent final votes on a whole text where the votes in favour were no more than "
                            f"{CLOSE_RELATIVE:.0%} of the votes cast above or below the majority needed. Budget discharge "
                            "decisions are not listed.",
             "items": close_votes},
            {"id": "rejected", "title": "Rejected",
             "description": "Final votes in which Parliament rejected a text, and motions it adopted to reject a proposal "
                            "or the Council's position, newest first, with what happened next. Amendments, objections, "
                            "motions of censure and budget discharge decisions are not listed.",
             "items": rej_items[:12]},
            {"id": "stalled", "title": "Stalled",
             "description": "Files Parliament's Legislative Train reports as blocked"
                            + (f" ({n_blocked_shown} of {n_blocked} shown, the latest reports first)"
                               if n_blocked_shown < n_blocked else "")
                            + ", then ordinary-procedure files with no recorded procedural update for a year or more. "
                            "Dates are each file's last recorded procedural step.",
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
            name = info["name"]
            if sid == "implementation" and s.indicators:  # named only in a release that has them (About page)
                name = name.replace(" and infringements", ", infringements and indicators")
            sources.append({
                "id": sid, "name": name, "institution": info["institution"], "url": info["url"],
                "licence": info["licence"], "status": st.status if st else "unavailable",
                "fetched_at": st.fetched_at if st else None, "records": dict(sorted(st.records.items())) if st else {},
                "note": st.note if st else "Not yet retrieved in this release.",
                "summary": self.source_summary(sid, st),
            })  # fmt: skip
        # only sources listed on the About page date "Data refreshed", so a reader can trace it to one of them
        fetched = [m[sid].fetched_at for sid in SOURCES if sid in m and m[sid].fetched_at]
        scope = self.coverage_scope()
        notes = self.coverage_notes(scope)
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
                # every Council vote listed (council/index.json): the voting results and the curated records
                "council_votes": len(getattr(self, "council_public", s.council)),
                "national_measures": len(s.measures),
                "infringements": len(s.infringements),
            },
            "coverage_notes": notes,
            "scope": scope,
        }

    def coverage_scope(self) -> dict[str, Any]:
        """The limits of the dataset as figures, so pages can state them next to lists and counts."""
        s = self.s
        vote_dates = sorted(v.date for v in self.indexed_votes)
        council_dates = sorted(c["date"] for c in getattr(self, "council_public", []))
        types = _lazy("pipeline.sources.ep_procedures", "PROCEDURE_TYPES")
        return {
            "procedure_types": list(types) if types else [],
            "procedures_from_year": _lazy("pipeline.sources.ep_procedures", "MIN_YEAR"),
            "acts_from": _lazy("pipeline.sources.eurlex", "MIN_DOCUMENT_DATE"),
            "ep_votes_from": vote_dates[0] if vote_dates else None,
            "ep_votes_to": vote_dates[-1] if vote_dates else None,
            # the first and last Council vote listed (council/index.json), for files that show none
            "council_votes_from": council_dates[0] if council_dates else None,
            "council_votes_to": council_dates[-1] if council_dates else None,
            "ep_roll_call_votes": sum(1 for v in s.votes if v.method == "VOTE_ELECTRONIC_ROLLCALL"),
            "dossiers_without_topic": sum(1 for d in self.dossier_summary.values() if not d["topics"]),
            # files Parliament classes as non-legislative (NLE) that EUR-Lex records as consultation or consent
            # procedures, e.g. 2006/0058(NLE), the EU-US Air Transport Agreement: shown, outside the stated types
            "other_type_dossiers": sum(1 for d in self.dossier_summary.values() if d["type"] not in (types or ())),
        }

    def source_summary(self, sid: str, st: SourceStatus | None) -> str:
        """A short plain-language note on what this release holds from one source and its known gaps.
        (`note` keeps the retrieval log, which is technical detail.)"""
        if not st or not st.fetched_at:
            return "Not retrieved for this release; information from this source is not shown."
        s, rec = self.s, st.records
        out: list[str] = []
        if sid == "ep_people":
            # the terms the source retrieves (an MEP's own `terms` also lists earlier terms they served)
            terms = [_ordinal(t) for t in sorted(_lazy("pipeline.sources.ep_people", "TERMS") or {})]
            span = (f"the {', '.join(terms[:-1])} or {terms[-1]} parliamentary term" if len(terms) > 1
                    else f"the {terms[0]} parliamentary term" if terms else "recent parliamentary terms")  # fmt: skip
            out.append(f"{len(s.meps):,} Members of the European Parliament who sat in {span} "
                       f"({sum(1 for x in s.meps if x.active):,} currently sitting), with their political group, "
                       "national party and committee memberships.")  # fmt: skip
        elif sid == "ep_procedures":
            out.append(f"{len(s.procedures):,} legislative procedures with "
                       f"{sum(len(p.events) for p in s.procedures):,} recorded procedural steps.")  # fmt: skip
            if rec.get("unavailable"):
                out.append(f"For {rec['unavailable']:,} further procedure references, Parliament's data had no "
                           "usable record in the latest retrieval.")  # fmt: skip
        elif sid == "ep_votes":
            # the votes listed (votes/index.json, meta counts), then the retrieved snapshot they are chosen from
            dates = sorted(v.date for v in s.votes)
            listed = sorted(v.date for v in self.indexed_votes)
            rc = sum(1 for v in s.votes if v.method == "VOTE_ELECTRONIC_ROLLCALL")
            with_b = sum(1 for v in self.indexed_votes if v.id in self.ballots and v.has_ballots)
            if listed:
                out.append(f"{len(listed):,} plenary votes from {_long_date(listed[0])} to {_long_date(listed[-1])} are "
                           f"listed, {with_b:,} of them with each MEP's recorded vote (votes on whole texts, "
                           "resolutions, motions and negotiating mandates). They are chosen from the "
                           f"{len(s.votes):,} plenary votes in the data retrieved (from {_long_date(dates[0])}, "
                           f"{rc:,} of them by roll call); the others, mostly votes on amendments and on parts of "
                           "texts, are not listed.")  # fmt: skip
        elif sid == "eurlex":
            out.append(f"{len(s.acts):,} adopted legal acts with their dates of signature, publication, entry into "
                       "force and application.")  # fmt: skip
        elif sid == "council":
            if s.council:
                # the votes listed and counted (council/index.json, meta counts): the voting results and the curated
                # records of adoptions that only a Council communication on a written procedure records
                listed = [*s.council, *self.council_extra]
                dates = sorted(c.date for c in listed)
                with_pos = sum(1 for c in listed if c.positions)
                unread = sum(1 for c in s.council if not c.positions)
                n = len(self.council_extra)
                extra = (f": {len(s.council):,} from the Council's voting-result documents and {n:,} "
                         f"{'adoption' if n == 1 else 'adoptions'} by written procedure from the Council's "
                         f"{'communication' if n == 1 else 'communications'} on its outcome "
                         f"({', '.join(c.source.identifier or c.id for c in self.council_extra)})") if n else ""  # fmt: skip
                out.append(f"{len(listed):,} votes of the Council of the EU ({dates[0][:4]}–{dates[-1][:4]}), "
                           f"{with_pos:,} of them with each Member State's position{extra}.")  # fmt: skip
                if unread:
                    out.append(f"{unread:,} voting-result {'document' if unread == 1 else 'documents'} could not be "
                               f"read and {'is' if unread == 1 else 'are'} shown without positions.")  # fmt: skip
                fixed = sum(1 for r in getattr(self, "council_public", []) if r.get("sheet_voting_rule"))
                if fixed:
                    out.append(f"For {fixed:,} votes the document prints “qualified majority” although the act's legal "
                               "basis requires unanimity: they are shown under unanimity, with a note.")  # fmt: skip
        elif sid == "implementation":
            with_m = len({x.directive_celex for x in s.measures})
            out.append(f"{len(s.measures):,} national transposition measures for {len(self.measure_celexes):,} "
                       f"directives ({with_m:,} with at least one measure) and {len(s.infringements):,} "
                       "infringement cases.")  # fmt: skip
            if not s.indicators:
                out.append("Country indicators (Single Market Scoreboard) could not be retrieved.")
        elif sid == "optouts":
            read = list(self.optouts.values())

            def bound_not(c: str) -> int:
                return sum(c in o.not_bound and c not in o.opted_in for o in read)

            later = sum("IE" in o.opted_in for o in read)
            # the directives that Protocols No 21 and 22 apply to make the statement; most directives say nothing on it
            stating = sum(1 for o in read if o.not_bound)
            out.append(f"The texts of {len(read):,} directives, read for the statement that Denmark or Ireland is not "
                       "taking part in a directive's adoption and is not bound by it (Protocols No 22 and 21). "
                       + (f"{stating:,} of them contain it: they declare Denmark not bound by {bound_not('DK'):,} and "
                          f"Ireland by {bound_not('IE'):,}"
                          + (f" (not counting {later:,} in which the Commission later confirmed Ireland's "
                             "participation)" if later else "") + "." if stating else "None of them contains it."))  # fmt: skip
        elif sid == "train":
            blocked = sum(1 for t in s.train if t.status.strip().lower() == "blocked")
            out.append(f"{len(s.train):,} files on Parliament's Legislative Train Schedule, {blocked:,} of them "
                       "labelled as blocked.")  # fmt: skip
        if st.status == "partial" and not (sid == "implementation" and not s.indicators):
            out.append("The latest retrieval did not complete; records from earlier retrievals are kept, and the "
                       "rest is added at the next update.")  # fmt: skip
        elif st.status == "failed":
            out.append(
                "The latest retrieval failed; this release uses the records from the last successful one."
            )
        return " ".join(out)

    def coverage_notes(self, scope: dict[str, Any] | None = None) -> list[str]:
        s = self.s
        m = s.manifest
        notes: list[str] = []
        scope = scope or {}

        def avail(sid: str) -> bool:
            # a source whose latest fetch failed still serves its previous records (kept in the snapshot)
            st = m.get(sid)
            return bool(st and st.fetched_at)

        if avail("ep_people"):
            notes.append("MEPs: everyone who sat in the 9th (2019–2024) or 10th (from 2024) Parliament, with their "
                         "political group and national party memberships as recorded by the European Parliament.")  # fmt: skip
        else:
            notes.append("MEPs: not available in this release.")
        n_ep = len(self.dossier_summary) - len(self.stub_ids)
        eurlex_only = [i for i in self.stub_ids if not self.split_children.get(i)]  # split parents have no act
        split_parents = [i for i in self.stub_ids if self.split_children.get(i)]
        if avail("ep_procedures") and n_ep:
            note = (f"Legislation: {n_ep:,} procedures recorded by the European Parliament. Status is derived "
                    "from the recorded procedural steps and EUR-Lex dates.")  # fmt: skip
            if eurlex_only or split_parents:  # the files counted beside these (meta counts.dossiers)
                also = ["these procedures"]
                if split_parents:
                    also.append(f"{len(split_parents):,} original {'proposal' if len(split_parents) == 1 else 'proposals'} "
                                "that Parliament split into separate procedures (each has a page of its own, with no "
                                "usable Parliament record, that links its parts)")  # fmt: skip
                if eurlex_only:
                    also.append(f"the {len(eurlex_only):,} adopted {'law' if len(eurlex_only) == 1 else 'laws'} noted next")
                note += (f" The {len(self.dossier_summary):,} legislative files in the table below are "
                         f"{', '.join(also[:-1])} and {also[-1]}.")  # fmt: skip
            notes.append(note)
        else:
            notes.append(
                "Legislation: the European Parliament procedure data was not available for this release."
            )
        if eurlex_only:
            notes.append(f"{len(eurlex_only):,} adopted laws are shown from their EUR-Lex record only (procedure "
                         "reference, title and legal dates), because the European Parliament procedure record is "
                         "not in this release; their Parliament steps are not shown.")  # fmt: skip
        if avail("ep_votes"):
            period = ""
            if scope.get("ep_votes_from") and scope.get("ep_votes_to"):
                period = f" from {_long_date(scope['ep_votes_from'])} to {_long_date(scope['ep_votes_to'])}"
            with_b = sum(1 for v in self.indexed_votes if v.id in self.ballots and v.has_ballots)
            rc = scope.get("ep_roll_call_votes")
            ballots = (f"How each MEP voted is shown for {with_b:,} of the {rc:,} roll-call votes in the source data; "
                       "votes on amendments and split or separate votes are not included. ") if rc else ""  # fmt: skip
            notes.append(f"Parliament votes: {len(self.indexed_votes):,} plenary votes{period} are listed (votes on "
                         "whole texts, resolutions and motions with roll-call results, all final and negotiating-mandate "
                         "votes linked to a procedure, and votes on a committee's decision to enter into "
                         "negotiations); earlier votes are not included. " + ballots +
                         "Group and country breakdowns use each MEP's membership on the day of the vote. "
                         "MEPs who did not vote are not counted as abstentions.")  # fmt: skip
        else:
            notes.append("Parliament votes: not available in this release.")
        if avail("eurlex"):
            notes.append(f"Adopted acts: {len(s.acts):,} legal acts from EUR-Lex/Cellar, linked to procedures only "
                         "through the procedure reference recorded by the Publications Office or Parliament.")  # fmt: skip
        else:
            notes.append("Adopted acts (EUR-Lex): not available in this release, so adoption, entry-into-force "
                         "and application dates may be missing.")  # fmt: skip
        if avail("council") and s.council:
            listed = [*s.council, *self.council_extra]  # as counted (meta counts.council_votes)
            dates = sorted(c.date for c in listed)
            unread = sum(1 for c in s.council if not c.positions)
            n = len(self.council_extra)
            extra = (f" and, for {n} {'adoption' if n == 1 else 'adoptions'} by written procedure, from the Council's "
                     f"{'communication' if n == 1 else 'communications'} on its outcome "
                     f"({', '.join(c.source.identifier or c.id for c in self.council_extra)})") if n else ""  # fmt: skip
            note = (f"Council votes: {len(listed):,} votes of the Council of the EU "
                    f"({dates[0][:4]}–{dates[-1][:4]}), with each Member State government's position read from the "
                    f"official Council voting-result documents{extra}. These are positions of national governments in "
                    "the Council, not of MEPs. Only a vote under unanimity can be blocked by a single country.")  # fmt: skip
            if unread:
                note += (
                    f" {unread:,} voting-result {'document' if unread == 1 else 'documents'} could not be read and "
                    f"{'is' if unread == 1 else 'are'} shown without positions."
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
                         "decisions register, shown separately from transposition data: all open cases and all cases "
                         f"with a Commission decision since {_long_date(INFRINGEMENTS_FROM)}; cases closed before then "
                         "are not included. A case is linked to a directive only when the register names it as the "
                         "legal basis.")  # fmt: skip
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


_DOTTED_ACRONYM = re.compile(r"(?:[^\W\d_]{1,3}\.){2,}")


def undotted_acronym(code: str) -> str | None:
    """A party code that EP open data writes with dots, as it is usually typed: 'N.D.' -> 'ND', 'DI.KO.' ->
    'DIKO', 'K.S. EDEK' -> 'KS EDEK'. Only words made entirely of dotted capitals change: 'SP.A' and 'E.Verde'
    stay as they are ('SPA' would rank a party above Spain for 'Spa')."""
    words = code.split()
    out = [w.replace(".", "") if _DOTTED_ACRONYM.fullmatch(w) and w.isupper() else w for w in words]
    return " ".join(out) if out != words else None


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
        if (m := re.fullmatch(r"(\d{4}-\d{4})[A-Z]", pid)) and pid in b.split_children.get(m.group(1), []):
            # a part of a split procedure: the Legislative Train names the file under the parent reference
            # ("Revision of the EU emission trading system (ETS)"), unless the name gives another part's
            # reference ("… - 2016/0400B(COD)")
            alts += [
                n
                for n in train_names(b.train_of.get(m.group(1), []))
                if p.reference in n or not re.search(r"\d{4}/\d{4}[A-Z]\([A-Z]{3}\)", n)
            ]
        if cur.get("short_title"):
            alts.append(clean_title(p.title))
        ids = [p.reference, ref_number(p.reference) or "", *d["celex"]]
        title_of = {a.celex: a.title for a in acts}
        ids += [n for c in d["celex"] if (n := act_number(c, title_of.get(c, "")))]
        for c in p.com_refs:
            ids += _com_variants(c)
        # the types of the file's acts, from their EUR-Lex records ("whistleblower directive": Directive (EU) 2019/1937)
        ids += sorted({a.act_type for a in acts if a.act_type in ("regulation", "directive", "decision")})
        doc = {
            "id": pid, "k": "dossier", "t": d["title"], "s": f"{d['ref']} · {d['status_label']}",
            "a": _join_alts(alts, d["title"]), "x": " ".join(dict.fromkeys(i for i in ids if i)),
            "u": f"/legislation/{pid}",
            # a split procedure's parent holds no act: its parts rank above it
            "w": 0.4 if pid in b.split_children else 3.0 if d["featured"] else (1.2 if d["type"] in LEGISLATIVE_TYPES else 0.8),
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
            if doc["k"] == "dossier" and doc["id"] in b.split_children:
                continue  # the parent of a split procedure: its parts carry the keywords
            if any(t in idk or any(f" {t} " in f" {n} " for n in names) for t in targets):
                hits.append(doc)
        if 0 < len(hits) <= ALIAS_RULE_MAX_DOCS:
            for doc in hits:
                have = set((doc.get("x") or "").split())
                add = [w for t in terms for w in [re.sub(r"\s+", "-", t.strip())] if w and w not in have]
                doc["x"] = " ".join([*(doc.get("x") or "").split(), *add]).strip() or None
        elif hits:
            log.warning("alias rule %s matches %d documents; not embedded", terms[:1], len(hits))
    # country names as on the MEP and party pages, the former member state included ("United Kingdom")
    country_name = {**MEMBER_STATES, **FORMER_MEMBER_STATES}
    for m in sorted(b.mep_summary.values(), key=lambda m: m["id"]):
        sub = ["MEP" if m["active"] else "Former MEP", country_name.get(m["country"], m["country"])]
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
    unnamed = getattr(b, "unnamed_parties", set())
    for pid in sorted(b.party_summary):
        if pid in unnamed:
            continue  # no name recorded: nothing to search for
        pt = b.party_summary[pid]
        sub = f"National party · {country_name.get(pt['country'], pt['country'] or 'unknown country')}"
        w = 1.3 if pt["members_active"] else 0.8
        twins = same_party[(_norm_key(pt["label"]), pt["country"])]
        if len(twins) > 1 and party_terms.get(pid):
            sub += f" · {ep_term_label(party_terms[pid])}"
            # records of the same name within the same term (Azione 6103 and 6478): the period each covers
            o = getattr(b, "org", {}).get(pid)
            if o and o.start and any(t != pid and party_terms.get(t) == party_terms[pid] for t in twins):
                sub += f" · {_long_date(o.start)} – {_long_date(o.end)}" if o.end else f" · from {_long_date(o.start)}"
            if max(party_terms[pid]) < max(max(party_terms.get(t) or {0}) for t in twins):
                w = 0.5
        doc = {"id": pid, "k": "party", "t": pt["label"], "s": sub, "u": f"/people/parties/{pid}", "w": w}
        if pt.get("code") and _norm_key(pt["code"]) != _norm_key(pt["label"]):
            undotted = undotted_acronym(pt["code"])
            doc["a"] = f"{pt['code']} | {undotted}" if undotted else pt["code"]
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
