"""Legally careful lifecycle status of a procedure ("dossier").

`classify(proc, acts, train, today)` is pure (no network, no clock): it reads the recorded
events of a Procedure (EP Open Data API + OEIL key events), the linked EUR-Lex legal acts and
Legislative Train files, and returns a `DossierStatus`.

Principles (each one is covered by tests/test_status.py):
- Parliament approving a text is not final adoption; a provisional (trilogue) agreement is not
  adoption; adoption/signature is not publication; entry into force can differ from the date
  of application.
- Only directives get a national-transposition next step; regulations apply directly.
- A Commission withdrawal is not a rejection by Parliament; under the consultation procedure
  (CNS) a negative Parliament opinion does not end the procedure. A recorded adoption after a
  withdrawal notice (e.g. of an earlier text) outranks the withdrawal.
- In a consent file the Council adopts the act after Parliament's consent, except for the acts that
  Parliament adopts itself with the Council's consent (PARLIAMENT_ADOPTS).
- Inactivity is reported as a number of days without a recorded update. A file is only
  described as blocked with the Legislative Train's "Blocked" label (verbatim, with its URL and
  update date), and only while the procedure's own stage is still active. Train statuses never
  override recorded EP / EUR-Lex facts (adoption, publication, withdrawal).
- Dates are only taken from the inputs; nothing in the future is invented.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.analysis.transposition import Dated, application_start, article_label
from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.models.entities import (
    EpVote,
    Event,
    EventKind,
    Institution,
    LegalAct,
    Procedure,
    TrainFile,
    UnrecordedApplication,
)

Stage = Literal[
    "proposed",
    "parliament_position",
    "negotiations",
    "provisional_agreement",
    "adopted",
    "published",
    "in_force",
    # a decision addressed to specific recipients: takes effect on notification to them, a date EUR-Lex does
    # not record (Cellar date of effect 1001-01-01, DATNOT), so EUR-Lex does not record it as in force
    "takes_effect_on_notification",
    "no_longer_in_force",  # repealed, expired or otherwise no longer in force according to EUR-Lex
    "withdrawn",
    "rejected",
    "lapsed",
    "unknown",
]
Basis = Literal["source", "derived"]
StepBasis = Literal["source", "derived", "unknown"]

TERMINAL: set[str] = {"published", "in_force", "takes_effect_on_notification", "no_longer_in_force", "withdrawn",
                      "rejected", "lapsed"}  # fmt: skip
# Stages in which the co-legislators still have to act (Train "Blocked" may be shown).
ACTIVE_STAGES: set[str] = {"proposed", "parliament_position", "negotiations", "provisional_agreement"}

# Rank of the "positive" lifecycle stages, used to reconcile event-derived stages with the
# official OEIL status label. Negative terminal stages are handled before ranking.
RANK: dict[str, int] = {
    "unknown": 0,
    "proposed": 1,
    "negotiations": 2,
    "provisional_agreement": 3,
    "parliament_position": 4,
    "adopted": 5,
    "published": 6,
    "in_force": 7,
    "no_longer_in_force": 8,
}

# OEIL "Stage reached in procedure" labels -> stages compatible with that label. The first
# entry is used when the recorded events point to an earlier stage than the label.
OEIL_STAGE: dict[str, tuple[str, ...]] = {
    "Preparatory phase in Parliament": ("proposed", "negotiations", "provisional_agreement"),
    "Awaiting committee decision": ("proposed", "negotiations", "provisional_agreement"),
    "Awaiting Parliament's position in 1st reading": ("proposed", "negotiations", "provisional_agreement"),
    "Awaiting Parliament's vote": ("proposed", "negotiations", "provisional_agreement"),
    "Awaiting Council's 1st reading position": ("parliament_position",),
    "Awaiting final decision": ("parliament_position",),
    "Awaiting Parliament 2nd reading": ("negotiations",),
    "Procedure completed, awaiting publication in Official Journal": ("adopted",),
    "Procedure completed": ("adopted", "published", "in_force", "no_longer_in_force"),
}
LAPSED_OR_WITHDRAWN = "Procedure lapsed or withdrawn"
# Legislative Train statuses that are an official "stalled" assessment. The Train glossary
# defines "Blocked" as no progress over at least the previous nine months.
TRAIN_STALL_STATUSES = ("blocked",)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NextStep(_M):
    text: str
    institution: Institution | None = None
    basis: StepBasis


class Stall(_M):
    days_since_last_event: int
    last_event_date: str
    text: str  # neutral description, e.g. "No recorded procedural update in 412 days"
    official_label: str | None = None  # Legislative Train "Blocked", verbatim (active stages only)
    official_source_url: str | None = None
    official_label_date: str | None = None  # the Train file's "Information updated as of" date
    official_text: str | None = None  # e.g. "Classified as “Blocked” by the EP Legislative Train ..."


class TranspositionDateInfo(_M):
    date: str
    # deadline: general transposition deadline; further_deadline: a deadline for specific provisions (earlier
    # or later); application: a date from which national measures (must or may) apply; other: a date EUR-Lex
    # records whose role the data do not establish (e.g. an optional "may apply" date)
    kind: Literal["deadline", "further_deadline", "application", "other"]
    articles: list[str] = Field(default_factory=list)  # article setting the date, e.g. "Art. 48(1)"
    # the general application date's exceptions in the directive's text, checked (transposition.yaml)
    exceptions: str | None = None


class Application(_M):
    entry_into_force: str | None = None
    entry_into_force_pending: bool = False  # EUR-Lex: enters into force on a condition not yet recorded as met
    entry_into_force_condition: str | None = None  # that condition, when the Treaty or EUR-Lex states it
    effect_on_notification: bool = False  # takes effect on notification to its addressee (date not recorded)
    application_dates: list[str] = Field(default_factory=list)
    partial_application_dates: list[str] = Field(default_factory=list)  # only some provisions apply from
    partial_on_entry_into_force: bool = False  # EUR-Lex marks the entry-into-force date as such a date too
    # EUR-Lex gives the date from which the act in general, or some provisions, apply as not recorded (1001-01-01),
    # with the article(s) it refers to ("Art. 96"): at most one of each kind, from the first act that has it
    application_unrecorded: list[UnrecordedApplication] = Field(default_factory=list)
    transposition_deadlines: list[str] = Field(default_factory=list)  # directives: deadlines only
    transposition: list[TranspositionDateInfo] = Field(default_factory=list)  # directives: every date
    future: bool = False  # any of the above dates is after `today`
    # dates above that EUR-Lex records for an act after the end of that act's validity
    after_end_of_validity: list[str] = Field(default_factory=list)


class ActRef(_M):
    """An act named in a status explanation (e.g. the repealing act), so that the site can link it."""

    celex: str
    label: str  # "Directive (EU) 2021/555" (official title), "Regulation 2017/1430" (CELEX id), else the CELEX id
    url: str  # EUR-Lex


class DossierStatus(_M):
    stage: Stage
    label: str
    explanation: str
    since: str | None = None  # date of the event/record that established the stage
    basis: Basis
    next_step: NextStep
    stall: Stall | None = None
    application: Application | None = None
    named_acts: list[ActRef] = Field(default_factory=list)  # acts named in `explanation`


# ====================================================================== helpers
def _code(e: Event) -> str:
    raw = e.raw_type or ""
    if raw.startswith("oeil:"):
        return raw
    return raw.rstrip("/").rsplit("/", 1)[-1]


def _last(events: list[Event], *kinds: EventKind) -> Event | None:
    found = [e for e in events if e.kind in kinds]
    return found[-1] if found else None


def _fmt(d: str) -> str:
    """'2024-08-01' -> '1 August 2024' (English, deterministic)."""
    y, m, dd = (int(x) for x in d.split("-"))
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    return f"{dd} {months[m - 1]} {y}"


def _join_celex(cs: list[str]) -> str:
    return cs[0] if len(cs) == 1 else ", ".join(cs[:-1]) + " and " + cs[-1]


def _join_dates(ds: list[str]) -> str:
    f = [_fmt(d) for d in ds]
    return f[0] if len(f) == 1 else ", ".join(f[:-1]) + " and " + f[-1]


ADOPTION_KINDS = (EventKind.signature, EventKind.publication, EventKind.council_adoption)

# Consent files in which Parliament adopts the act and the Council gives its consent: the roles of the usual
# consent procedure are reversed. Article 228(4) TFEU (Statute of the European Ombudsman: Regulation 2021/1163
# "of the European Parliament ... Having regard to the consent of the Council"); Article 223(2) TFEU ("The
# European Parliament, acting by means of regulations on its own initiative ... with the consent of the
# Council", Statute for Members). Acts titled "... of the European Parliament of <date>" are detected as well.
PARLIAMENT_ADOPTS: dict[str, str] = {"2019-0900": "Article 228(4) TFEU", "2026-0900": "Article 223(2) TFEU"}
_PARLIAMENT_ACT = re.compile(r"(?:Regulation|Decision)\b[^/]*/\d{1,4} of the European Parliament of \d")


def parliament_adopts(proc: Procedure, acts: list[LegalAct]) -> bool:
    """A consent file whose act Parliament adopts with the Council's consent (see PARLIAMENT_ADOPTS)."""
    return proc.type == "APP" and (proc.id in PARLIAMENT_ADOPTS or any(_PARLIAMENT_ACT.match(a.title) for a in acts))


def relevant_acts(proc: Procedure, acts: list[LegalAct], events: list[Event], today: date) -> list[LegalAct]:
    """Acts that can establish this procedure's status. An act linked by EUR-Lex to several
    procedures (e.g. a new proposal that replaced an older one) only counts when this procedure
    itself shows the act was adopted under it: its final act (OEIL) or a recorded adoption,
    signature or publication - and, when OEIL lists the procedure's final acts, is one of them. Acts
    dated after `today` are ignored, and so are acts of the Commission (implementing or delegated acts
    adopted under the law, which OEIL may list as a "Corrigendum to final act", e.g. 32025R1328 on
    2021/0426(COD)): the procedures here are legislative and the Commission does not adopt their acts."""
    t = today.isoformat()
    out = []
    adopted_here = any(e.kind in ADOPTION_KINDS for e in events) or (proc.stage_raw or "").startswith(
        "Procedure completed"
    )
    for a in acts:
        dated = a.date_publication or a.date_signature or a.date_document
        if dated and dated > t:
            continue
        if a.title.startswith("Commission "):
            continue
        # OEIL's final-act list, when there is one, decides between procedures sharing an act
        if a.celex in proc.celex_refs or len(a.procedure_refs) <= 1 or (adopted_here and not proc.celex_refs):
            out.append(a)
    return out


def _main_act(proc: Procedure, acts: list[LegalAct]) -> LegalAct | None:
    if not acts:
        return None
    linked = [a for a in acts if a.celex in proc.celex_refs] or acts
    pref = {"regulation": 0, "directive": 1, "decision": 2, "recommendation": 3, "other": 4}
    return sorted(linked, key=lambda a: (pref[a.act_type], a.celex))[0]


def application_of(acts: list[LegalAct], today: date) -> Application | None:
    if not acts:
        return None
    t = today.isoformat()
    eifs = sorted(a.entry_into_force for a in acts if a.entry_into_force)
    eif = eifs[0] if eifs else None
    app = sorted({d for a in acts for d in a.other_application_dates if d and d != eif})
    tr = transposition_info(acts)
    future = any(d > t for d in ([eif] if eif else []) + app + [x.date for x in tr])
    pending = not eif and any(a.entry_into_force_pending for a in acts)
    # dates an act records for after its own end of validity (not when that end is retroactive: then every
    # date of the act is later)
    ended = {
        d
        for a in acts
        if a.end_of_validity and not _retroactive_end(a)
        for d in [*a.other_application_dates, *a.transposition_deadlines]
        if d > a.end_of_validity
    }
    return Application(
        entry_into_force=eif,
        entry_into_force_pending=pending,
        entry_into_force_condition=next((c for a in acts if (c := entry_into_force_condition(a))), None)
        if pending
        else None,
        effect_on_notification=not eif and not pending and any(a.effect_on_notification for a in acts),
        application_dates=app,
        partial_application_dates=sorted({d for a in acts for d in a.partial_application_dates if d in app}),
        partial_on_entry_into_force=any(a.partial_on_entry_into_force for a in acts if eif and a.entry_into_force == eif),
        application_unrecorded=unrecorded_of(acts),
        transposition_deadlines=[x.date for x in tr if x.kind in ("deadline", "further_deadline")],
        transposition=tr,
        future=future,
        after_end_of_validity=sorted(d for d in ended if d in app or d in {x.date for x in tr}),
    )


def unrecorded_of(acts: list[LegalAct]) -> list[UnrecordedApplication]:
    """The application dates EUR-Lex gives as not recorded (1001-01-01), for the act in general and for some
    provisions: of each kind, the first act's, with its articles labelled ("96" -> "Art. 96")."""
    out = []
    for partial in (False, True):
        x = next((u for a in acts for u in a.application_unrecorded if u.partial == partial), None)
        if x:
            out.append(UnrecordedApplication(partial=partial, articles=[article_label(r) for r in x.articles]))
    return out


def application_exceptions(acts: list[LegalAct], x: Dated) -> str | None:
    """What the text of the first directive among the acts provides beside its general application date x (a
    classified transposition date), checked against the text (data/curated/transposition.yaml)."""
    dr = next((a for a in acts if a.act_type == "directive" and a.transposition_deadlines), None)
    chk = dr.transposition_checked if dr else None
    ok = chk and x.kind == "application" and x.date == chk.applies_from
    return chk.application_exceptions if ok else None


def transposition_info(acts: list[LegalAct]) -> list[TranspositionDateInfo]:
    """Classified transposition dates of the first directive among the acts (see transposition.py)."""
    for a in acts:
        if a.act_type == "directive" and a.transposition_deadlines:
            return [
                TranspositionDateInfo(date=x.date, kind=x.kind, articles=[article_label(r) for r in x.articles],
                                      exceptions=application_exceptions(acts, x))  # fmt: skip
                for x in classify_transposition(a)
            ]
    return []


def _stall(stage: str, events: list[Event], train: list[TrainFile], today: date) -> Stall | None:
    if stage in TERMINAL:
        return None
    t = today.isoformat()
    past = [e for e in events if e.date <= t]
    if not past:
        return None
    last = max(e.date for e in past)
    days = (today - date.fromisoformat(last)).days
    unit = "day" if days == 1 else "days"
    stall = Stall(
        days_since_last_event=days,
        last_event_date=last,
        text=f"No recorded procedural update in {days} {unit} (last recorded: {_fmt(last)}).",
    )
    # The Train lags (monthly updates) and never overrides recorded EP/EUR-Lex facts: its
    # "Blocked" label is shown only while the procedure's own stage is still active, and only
    # if the Train file was updated on or before `today`.
    if stage not in ACTIVE_STAGES:
        return stall
    for tf in sorted(train, key=lambda f: (f.last_updated or "", f.url), reverse=True):
        if tf.status.strip().lower() not in TRAIN_STALL_STATUSES:
            continue
        if tf.last_updated and tf.last_updated > t:
            continue
        text = f"Classified as \u201c{tf.status}\u201d by the EP Legislative Train"
        if tf.blocking_institution:
            text += f" (blocking institution named by the Train: {tf.blocking_institution})"
        if tf.last_updated:
            text += f", information updated as of {_fmt(tf.last_updated)}"
        text += ". The Train uses this label when no progress has been recorded for at least nine months."
        stall.official_label = tf.status
        stall.official_source_url = tf.url
        stall.official_label_date = tf.last_updated
        stall.official_text = text
        break
    return stall


# ====================================================================== stage derivation
class _S:
    """Mutable result under construction."""

    def __init__(self, stage: str, label: str, explanation: str, since: str | None, basis: Basis):
        self.stage, self.label, self.explanation, self.since, self.basis = (
            stage,
            label,
            explanation,
            since,
            basis,
        )
        self.next_step: NextStep | None = None
        self.named_acts: list[ActRef] = []


# ====================================================================== acts named in the status
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:"
# The Act concerning the election of the members of the European Parliament by direct universal suffrage
# (annexed to Decision 76/787/ECSC, EEC, Euratom), as Cellar identifies it in the acts that amend it
ELECTORAL_ACT = "41976X1008(01)"
# the act's number as its official title gives it (same pattern as build.act_label)
ACT_NAME_RE = re.compile(
    r"^((?:Council |Commission )?(?:Implementing |Delegated )?(?:Regulation|Directive|Decision)"
    r"(?: \([A-Z][A-Za-z, ]*\))?(?: No)? \d{1,4}/\d{1,4}(?:/[A-Z]+)*)"
)
# Cellar comments on an end-of-validity date (authority table fd_330) that name the act which ended it
ENDED_BY = {"A/PAR": "repealed", "AR/PAR": "repealed and replaced", "AI/PAR": "implicitly repealed", "R/PAR": "replaced"}
CELEX_NUMBER_RE = re.compile(r"^3(\d{4})([RLD])(\d{4})$")
CELEX_KIND = {"R": "Regulation", "L": "Directive", "D": "Decision"}


def _ref(celex: str, others: Mapping[str, LegalAct]) -> ActRef:
    a = others.get(celex)
    m = ACT_NAME_RE.match(a.title) if a else None
    label = m.group(1) if m else celex
    # an act not in our data: from 2015 its CELEX id gives its number ("32020R0687" -> "Regulation 2020/687")
    if a is None and (n := CELEX_NUMBER_RE.match(celex)) and n[1] >= "2015":
        label = f"{CELEX_KIND[n[2]]} {n[1]}/{int(n[3])}"
    return ActRef(celex=celex, label=label, url=a.eurlex_url if a else EURLEX_URL + celex)


def _labels(refs: list[ActRef]) -> str:
    return _join_celex([r.label for r in refs])


def _retroactive_end(a: LegalAct) -> bool:
    """Cellar's end of validity is earlier than the act itself (a repeal with retroactive effect)."""
    dated = a.date_document or a.date_publication
    return bool(a.end_of_validity and dated and a.end_of_validity < dated)


def _ended_by(act: LegalAct, others: Mapping[str, LegalAct]) -> tuple[str, list[ActRef]]:
    """How EUR-Lex records the end of the act: its whole-act repeal links, else the act that Cellar's comment
    on the end-of-validity date names (e.g. 32015R2424: "Implicitly repealed by 32017R1001 and 32017R1430")."""
    how, celexes = "repealed", list(act.repealed_by)
    if not celexes:
        for n in act.validity_notes:
            code = next((c for c in n.codes if c in ENDED_BY), None)
            if code and not n.partial and n.date == act.end_of_validity:
                how, celexes = ENDED_BY[code], [c for c in n.acts if c != act.celex]
                break
    return how, [_ref(c, others) for c in celexes]


def _rules_continue(act: LegalAct, refs: list[ActRef], others: Mapping[str, LegalAct]) -> str:
    """A later successor whose official title marks it as a codification or a recast takes over the rules. (An
    earlier one cannot: Regulation 1377/2014 amended an act that the recast 609/2014, adopted before it, repealed
    with retroactive effect.)"""
    out = ""
    for r in refs:
        later = r.celex in others and (others[r.celex].date_document or "") > (act.date_document or "9999")
        title = others[r.celex].title.lower() if later else ""
        in_force = ", and it is in force" if r.celex in others and others[r.celex].in_force else ""
        if "(codification)" in title:
            out += f" {r.label} is a codification: the rules continue in it, unchanged in substance{in_force}."
        elif "(recast)" in title:
            out += f" {r.label} is a recast: the rules continue in it, with the amendments it makes{in_force}."
    return out


def _day_after(d: str) -> str:
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def _repeal_dates(act: LegalAct, refs: list[ActRef], partial: bool) -> list[str]:
    """The dates from which Cellar records the repeals by these acts as taking effect (start_of_validity on the
    repeal links): of the whole act, or (partial) of some provisions only."""
    named = {r.celex for r in refs}
    return sorted({d.date for d in act.repeal_dates if d.celex in named and d.partial == partial})


def _with_effect(act: LegalAct, refs: list[ActRef], partial: bool) -> str:
    """The acts' labels, each with the date from which Cellar records its repeal as taking effect, where it does."""
    dated = [(r.label, _repeal_dates(act, [r], partial)) for r in refs]
    if len(dated) == 1:
        return dated[0][0] + (f" with effect from {_join_dates(dated[0][1])}" if dated[0][1] else "")
    return _join_celex([label + (f" (with effect from {_join_dates(ds)})" if ds else "") for label, ds in dated])


def _no_longer_in_force(act: LegalAct, others: Mapping[str, LegalAct]) -> _S:
    """Cellar's end of validity is usually the act's last day of validity (Directive 95/46/EC: 24 May 2018, repealed
    by the GDPR with effect from 25 May 2018); the act is no longer in force from the day after. Where Cellar records
    the date from which the repeal takes effect (start_of_validity on the repeal link), that date counts: it can be the
    end of validity itself (32014R0543: both 1 July 2016; Regulation (EU) 2015/2219, Art. 40(1), "with effect from
    1 July 2016"). A repeal in stages, with later dates for some provisions, gets no single date: the texts do not
    settle the day (32014L0061: repealed by Regulation (EU) 2024/1309 with effect from 12 November 2025; its Art. 18(2)
    keeps some provisions "in force until" the dates from which its replacing provisions apply, the last 12 May 2026,
    which Cellar gives as the end of validity, with 13 May 2026 for the repeal of those provisions)."""
    eov = act.end_of_validity
    how, refs = _ended_by(act, others)
    by = f" EUR-Lex records it as {how} by {_labels(refs)}" if refs else ""
    start = next(reversed(_repeal_dates(act, refs, False)), None)
    since = _day_after(eov) if eov else None
    if eov and start and any(d > start for d in _repeal_dates(act, refs, True)):
        text = (
            f"The act was adopted and published. EUR-Lex records it as {how} by {_labels(refs)} with effect from "
            f"{_fmt(start)}, except for some provisions, whose repeal it records with effect from later dates. EUR-Lex "
            f"gives {_fmt(eov)} as the end of the act's validity."
        )
        start = since = None
    elif eov and _retroactive_end(act):
        which = (
            f"which is dated {_fmt(act.date_document)}"
            if act.date_document
            else f"published on {_fmt(act.date_publication or '')}"
        )
        text = (
            f"The act was adopted and published, but EUR-Lex gives {_fmt(eov)} as the end of its validity, a date "
            f"earlier than the act itself, {which}."
        )
        text += (
            f"{by}, with effect from {_fmt(start or _day_after(eov))}." if refs
            else " EUR-Lex records no reason for the earlier date."
        )
    elif eov and start and start != since:
        text = (
            f"The act was adopted and published. EUR-Lex gives {_fmt(eov)} as the end of its validity and records it "
            f"as {how} by {_labels(refs)} with effect from {_fmt(start)}."
        )
    elif eov:
        text = f"The act was adopted and published, but its validity ended on {_fmt(eov)}." + (by + "." if by else "")
    else:
        text = "The act was adopted and published, but EUR-Lex records it as no longer in force." + (
            by + "." if by else ""
        )
    if start:  # the repeal's own date, unless the validity ended before it
        since = min(start, since) if since else start
    s = _S("no_longer_in_force", "No longer in force", text + _rules_continue(act, refs, others), since, "source")
    s.named_acts = refs
    return s


def entry_into_force_condition(act: LegalAct) -> str | None:
    """The condition on which a pending act enters into force, as far as the Treaty or EUR-Lex states it."""
    if not act.entry_into_force_pending:
        return None
    arts = ", ".join(article_label(a) for a in act.entry_into_force_articles)
    if ELECTORAL_ACT in act.amends:
        # Art. 223(1) TFEU: these provisions "shall enter into force following their approval by the Member
        # States in accordance with their respective constitutional requirements" (as Art. 2 of 2018/994 says)
        return (
            "It enters into force only after every Member State has approved it in accordance with its "
            "constitutional requirements (Article 223(1) TFEU)"
            + (f"; EUR-Lex refers to {arts} of the decision for the date." if arts else ".")
        )
    return "It enters into force only once a condition set in the act is met" + (
        f" (EUR-Lex refers to {arts})." if arts else "."
    )


ENHANCED_COOPERATION_RE = re.compile(r"\bimplementing enhanced cooperation\b", re.I)


def regulation_applies(act: LegalAct) -> str:
    """How a regulation applies, as far as its title says where: one "implementing enhanced cooperation" binds only
    the participating Member States (Art. 20(4) TEU: "Acts adopted in the framework of enhanced cooperation shall bind
    only participating Member States"; Regulation (EU) 2026/467, recital 43: "This Regulation does not apply to
    Member States which do not participate in the enhanced cooperation"). Which Member States another regulation
    binds is in its recitals (Protocols 21 and 22), which our data do not read for regulations."""
    if ENHANCED_COOPERATION_RE.search(act.title or ""):
        return (
            "applies directly only in the Member States taking part in the enhanced cooperation it implements "
            "(Article 20(4) TEU)"
        )
    return "applies directly"


def unrecorded_application_text(act: LegalAct) -> str:
    """What EUR-Lex records of an act whose application date it gives as not recorded (1001-01-01): never that it
    applies from its entry into force. ETIAS, Regulation (EU) 2018/1240, Art. 96: "This Regulation shall apply from
    the date determined by the Commission in accordance with Article 88"; Cellar refers to that article."""
    refers = {
        x.partial: f" (it refers to {', '.join(article_label(r) for r in x.articles)})" if x.articles else ""
        for x in act.application_unrecorded
    }
    if False in refers and True in refers:
        return (
            f"EUR-Lex records no date from which the act in general applies{refers[False]}, nor one from which "
            f"some of its provisions apply{refers[True]}."
        )
    if False in refers:
        return f"EUR-Lex records no date from which the act in general applies{refers[False]}."
    if True in refers:
        return f"EUR-Lex records no date from which some of its provisions apply{refers[True]}."
    return ""


def _acts_stage(
    proc: Procedure,
    acts: list[LegalAct],
    events: list[Event],
    today: date,
    others: Mapping[str, LegalAct] | None = None,
) -> _S | None:
    """Published / in force, from EUR-Lex acts and the recorded publication. `others`: acts by CELEX, to
    name the acts that this one's record refers to (e.g. the repealing act)."""
    t = today.isoformat()
    others = others or {}
    act = _main_act(proc, acts)
    pub_ev = _last(events, EventKind.publication)
    pub_date = (act.date_publication if act else None) or (pub_ev.date if pub_ev else None)
    if act:
        eif = act.entry_into_force
        if eif and eif > t:
            text = (
                f"The act was published in the Official Journal{' on ' + _fmt(pub_date) if pub_date else ''}. "
                f"It enters into force on {_fmt(eif)}."
            )
            return _S("published", "Published, not yet in force", text, pub_date, "source")
        if act.end_of_validity and act.end_of_validity < t:  # still valid on its last day of validity
            return _no_longer_in_force(act, others)
        published = f"published in the Official Journal{' on ' + _fmt(pub_date) if pub_date else ''}."
        if act.effect_on_notification and not act.end_of_validity and not act.repealed_by and not act.in_force:
            # Cellar: date of effect (PE) = date of notification (DATNOT), not recorded. Without the date EUR-Lex
            # does not record the decision as in force, but nothing makes it "not yet in force" either. (No Treaty
            # rule is cited: Art. 297(2) TFEU, notification of addressed decisions, is about non-legislative acts,
            # and these decisions are legislative acts.)
            s = _S(
                "takes_effect_on_notification",
                "Takes effect on notification",
                f"The decision was {published} It is addressed to specific recipients, and EUR-Lex gives its date "
                "of effect as the date of notification to them, without recording that date.",
                pub_date,
                "source",
            )
            for n in [n for n in act.validity_notes if n.partial and n.date <= t][-1:]:
                refs = [_ref(c, others) for c in n.acts if c != act.celex]
                s.explanation += f" EUR-Lex records a partial end of its validity on {_fmt(n.date)}" + (
                    f" and refers to {_labels(refs)}." if refs else "."
                )
                s.named_acts += refs
            return s
        if act.in_force is False and not act.end_of_validity and not act.repealed_by and (not eif or eif > t):
            # EUR-Lex "not in force" with no end date: the act has not yet taken effect (Cellar gives
            # its entry into force as unknown, e.g. pending approval by every Member State)
            text = f"The act was {published} EUR-Lex records it as not yet in force and gives no date of entry into force."
            cond = entry_into_force_condition(act)
            return _S("published", "Published, not yet in force", text + (" " + cond if cond else ""), pub_date, "source")
        if act.in_force is False:
            return _no_longer_in_force(act, others)
        if act.in_force is True or (eif and eif <= t):
            basis: Basis = "source" if act.in_force is True else "derived"
            text = f"The act has been in force since {_fmt(eif)}." if eif else "The act is in force."
            if eif and act.partial_on_entry_into_force:  # Cellar marks that date MA/PART too (DMA, Art. 54)
                text += " EUR-Lex records that some provisions apply from that date" + (
                    "." if any(a.other_application_dates for a in acts) or act.application_unrecorded
                    # and no date for the others
                    else ", and no date from which the other provisions apply."
                )
            later = [d for a in acts for d in a.other_application_dates if d and eif and d > eif]
            if later:
                text += (
                    " Entry into force is not the same as application: EUR-Lex records later dates from "
                    "which (parts of) the act apply."
                )
            # a date the act leaves to a later decision, notice or event, which EUR-Lex does not record (Regulation
            # (EU) 2025/12, Art. 46: from "the date two years from the date on which the router starts operations,
            # as determined by the Commission")
            if unrecorded := unrecorded_application_text(act):
                text += " " + unrecorded
            # an end of validity still ahead, and the act that repeals it (32015L0849: validity ends on
            # 9 July 2027, repealed by Directive (EU) 2024/1640)
            refs = [_ref(c, others) for c in act.repealed_by]
            if act.end_of_validity:
                text += f" EUR-Lex records that its validity ends on {_fmt(act.end_of_validity)}" + (
                    f" and that {_labels(refs)} repeals it" if refs else ""
                ) + (f" with effect from {_join_dates(ds)}." if (ds := _repeal_dates(act, refs, False)) else ".")
            elif refs:
                text += f" EUR-Lex also records it as repealed by {_labels(refs)}."
            # repeals that Cellar limits to some provisions or marks as partial (32014D0335: Decision (EU, Euratom)
            # 2020/2053, Art. 11(1), "Subject to paragraph 2, Decision 2014/335/EU, Euratom is repealed"; Cellar
            # records the repeal from 1 January 2021, the date from which that decision applies, Art. 12)
            partly = [_ref(c, others) for c in act.partly_repealed_by]
            if partly:
                text += f" EUR-Lex records it as partly repealed by {_with_effect(act, partly, True)}."
            s = _S("in_force", "In force", text, eif or pub_date, basis)
            s.named_acts = refs + partly
            return s
        if pub_date:
            return _S(
                "published",
                "Published in the Official Journal",
                f"The act was published in the Official Journal on {_fmt(pub_date)}. "
                "Its entry-into-force date is not recorded in our data.",
                pub_date,
                "source",
            )
    if pub_ev:
        return _S(
            "published",
            "Published in the Official Journal",
            f"The final act was published in the Official Journal on {_fmt(pub_ev.date)}. "
            "Entry into force and application dates come from the act itself.",
            pub_ev.date,
            "source",
        )
    return None


# OEIL's record of a committee's decision to enter into negotiations before Parliament's first reading: Parliament
# holds a mandate only once the decision is announced in plenary (OEIL "... announced in plenary (Rule 72)") or
# Parliament confirms it (EP PLENARY_ENDORSE_...), or after Parliament's own vote referring the file back
COMMITTEE_MANDATE_DECISION = (
    "oeil:Committee decision to open interinstitutional negotiations with report adopted in committee"
)
# Parliament's own decisions giving the mandate, and its rejection of a committee's decision (sic: the EP data spell
# some records INTERINSTUTIONAL)
PLENARY_MANDATE = {
    "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
    "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
    "ep_vote:mandate:adopted",  # a plenary vote OEIL does not record yet (build.with_recorded_events)
}
MANDATE_REFUSED = {
    "PLENARY_REJECT_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
    "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS",
}
# Parliament's referral of a file back to the committee responsible for reconsideration (OEIL "Matter referred back
# to the committee responsible for reconsideration")
REFERRED_BACK = {"PLENARY_REFER_COMMITTEE_RECONSIDERATION"}


def _cod_stage(events: list[Event]) -> _S:
    """Ordinary legislative procedure (Art. 294 TFEU), from recorded events only."""
    sig = _last(events, EventKind.signature)
    if sig:
        return _S(
            "adopted",
            "Signed, awaiting publication",
            # Art. 297(1) TFEU: legislative acts "shall enter into force on the date specified in them or, in the
            # absence thereof, on the twentieth day following that of their publication"
            "Parliament and the Council have adopted the act and it has been signed. It is not recorded as published "
            "in the Official Journal yet; once published, it enters into force on the date it sets or, if it sets "
            "none, on the twentieth day after publication (Article 297(1) TFEU). Its rules can apply from later "
            "dates.",
            sig.date,
            "source",
        )
    adopt = _last(events, EventKind.council_adoption)
    if adopt:
        return _S(
            "adopted",
            "Adopted by Parliament and Council",
            "Both Parliament and the Council have adopted the act. "
            "It still has to be signed and published in the Official Journal.",
            adopt.date,
            "source",
        )
    second_ok = [e for e in events if _code(e) == "PLENARY_APPROVE_COUNCIL_POSITION"]
    if second_ok:
        return _S(
            "adopted",
            "Adopted at second reading",
            "Parliament approved the Council's position at second reading, so the act is adopted "
            "(Article 294(7) TFEU). It still has to be signed and published in the Official Journal.",
            second_ok[-1].date,
            "derived",
        )
    council_pos = _last(events, EventKind.council_position)
    ep_pos = _last(events, EventKind.ep_position)
    if council_pos and (not ep_pos or ep_pos.date <= council_pos.date):
        return _S(
            "negotiations",
            "Second reading in Parliament",
            "The Council has adopted its first-reading position. Parliament can approve, amend or "
            "reject it at second reading; EU law cannot be adopted without both institutions agreeing.",
            council_pos.date,
            "derived",
        )
    if ep_pos and _code(ep_pos) == "PLENARY_ADOPT_JOINT_TEXT":
        return _S(
            "parliament_position",
            "Parliament approved the conciliation text",
            "Parliament approved the joint text agreed in the Conciliation Committee. The act is adopted "
            "only if the Council also approves it (Article 294(13) TFEU).",
            ep_pos.date,
            "derived",
        )
    if ep_pos and _code(ep_pos) == "PLENARY_AMEND_COUNCIL_POSITION":
        return _S(
            "parliament_position",
            "Parliament amended the Council's position",
            "At second reading Parliament amended the Council's position. "
            "The act is adopted only if the Council approves all of Parliament's amendments.",
            ep_pos.date,
            "derived",
        )
    if ep_pos:
        agreed = _last(events, EventKind.provisional_agreement)
        if agreed and agreed.date <= ep_pos.date:
            return _S(
                "parliament_position",
                "Approved by Parliament",
                "Parliament adopted its first-reading position on the text agreed with the Council. "
                "It is not law yet: the Council must still formally approve it.",
                ep_pos.date,
                "derived",
            )
        # Negotiations after Parliament's first reading, before the Council's first-reading position, towards an
        # agreement that the Council adopts as its position for Parliament to approve at second reading (Article
        # 294(5) and (7)(a) TFEU): 2023/0210(COD), first reading 23 April 2024, OEIL 5 May 2026 "Approval in
        # committee of the text agreed at early 2nd reading interinstitutional negotiations"
        talks = [e for e in events if e.date > ep_pos.date and (
            e.kind == EventKind.negotiation_mandate or _code(e) == "INTERINSTITUTIONAL_NEGOTIATION")]  # fmt: skip
        trilogues = [e for e in talks if _code(e) == "INTERINSTITUTIONAL_NEGOTIATION"]
        first = f"Parliament adopted its first-reading position on {_fmt(ep_pos.date)}."
        aim = (
            "an agreement that the Council would adopt as its first-reading position, for Parliament to approve at "
            "second reading (an early second-reading agreement)"
        )
        s = None
        if not council_pos and agreed:
            s = _S(
                "parliament_position",
                "Early second-reading agreement reached",
                f"{first} Parliament's committee approved, on {_fmt(agreed.date)}, the text agreed with the Council in "
                "the negotiations that followed. It is not law yet: the Council adopts its first-reading position on "
                "the agreed text, which Parliament then approves at second reading.",
                agreed.date,
                "derived",
            )
            s.next_step = NextStep(
                text="The Council adopts its first-reading position on the agreed text; if Parliament approves that "
                "position at second reading, the act is adopted (Article 294(7)(a) TFEU).",
                institution="Council",
                basis="derived",
            )
        elif not council_pos and talks:
            s = _S(
                "parliament_position",
                "Negotiations with the Council after Parliament's first reading"
                if trilogues
                else "Committee decided to negotiate with the Council after Parliament's first reading",
                f"{first} "
                + (
                    f"Parliament's negotiators and the Council have since negotiated (first recorded meeting: "
                    f"{_fmt(trilogues[0].date)}), seeking {aim}."
                    if trilogues
                    else f"On {_fmt(talks[0].date)} the decision of Parliament's committee to negotiate with the "
                    f"Council was recorded, with a view to {aim}."
                )
                + " It is not law yet.",
                (trilogues or talks)[0].date,
                "derived",
            )
            s.next_step = NextStep(
                text="Parliament and Council negotiators seek an agreement, which the Council would then adopt as its "
                "first-reading position for Parliament to approve at second reading.",
                basis="derived",
            )
        if s is not None:
            return s
        return _S(
            "parliament_position",
            "Parliament adopted its first-reading position",
            "Parliament has adopted its position. The Council (EU governments) must also agree "
            "before the proposal can become law.",
            ep_pos.date,
            "derived",
        )
    agreed = _last(events, EventKind.provisional_agreement)
    if agreed:
        return _S(
            "provisional_agreement",
            "Provisional agreement reached",
            "Parliament and Council negotiators reached a provisional agreement, approved by "
            "Parliament's committee. This is not adoption: Parliament as a whole and the Council "
            "must still formally approve the text.",
            agreed.date,
            "source",
        )
    # Parliament's referral of the file back to the committee responsible for reconsideration (Rule 198 of its Rules of
    # Procedure): a decision to negotiate taken before it, or announced the same day, gives no mandate (2022/0135(COD),
    # 12 Dec 2022: the committee's decision on report A9-0288/2022 announced, then "the referral back to committee
    # under Rule 198 of the report ... The House agreed to the proposal", minutes PV-9-2022-12-12, item 5)
    back = next((e for e in reversed(events) if _code(e) in REFERRED_BACK), None)
    lapsed_mandate = False
    if back:
        kept = [e for e in events if e.kind != EventKind.negotiation_mandate or e.date > back.date or (
            e.date == back.date and _code(e) in PLENARY_MANDATE)]  # fmt: skip
        lapsed_mandate, events = len(kept) < len(events), kept
    mandate = _last(events, EventKind.negotiation_mandate)
    refused = [e for e in events if _code(e) in MANDATE_REFUSED]
    if mandate and refused and not [e for e in events if e.kind == EventKind.negotiation_mandate and (
        e.date > refused[-1].date or (e.date == refused[-1].date and _code(e) in PLENARY_MANDATE)
    )]:  # fmt: skip
        s = _S(
            "proposed",
            "Parliament rejected the committee's decision to negotiate",
            "Parliament rejected its committee's decision to enter into negotiations with the Council, so it holds "
            "no mandate to negotiate. The committee report goes to a vote in plenary.",
            refused[-1].date,
            "derived",
        )
        s.next_step = NextStep(
            text="Parliament votes on the committee report and amendments in plenary.", institution="EP", basis="derived"
        )
        return s
    if mandate and all(
        _code(e) == COMMITTEE_MANDATE_DECISION
        for e in events
        if e.kind == EventKind.negotiation_mandate and e.date == mandate.date
    ):
        # not yet announced in plenary, nor confirmed by it (2025/0255(COD): committee decision of 19 October 2026,
        # OEIL "Awaiting committee decision")
        s = _S(
            "proposed",
            "Committee decided to negotiate with the Council",
            "Parliament's responsible committee has adopted its report and decided to enter into negotiations with "
            "the Council. Parliament does not hold a mandate yet: the decision is first announced in plenary, where "
            "Members can ask for a vote on it (Rule 72 of Parliament's Rules of Procedure).",
            mandate.date,
            "derived",
        )
        s.next_step = NextStep(
            text="The committee's decision is announced in plenary. If no vote is requested, or Parliament approves the "
            "decision, negotiations with the Council can start; if Parliament rejects it, Parliament votes on the "
            "committee report in plenary.",
            institution="EP",
            basis="derived",
        )
        return s
    if mandate:
        # a recorded trilogue (EP activity INTERINSTITUTIONAL_NEGOTIATION) after the mandate; the
        # mandate decisions themselves (PLENARY_ENDORSE/REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS)
        # also contain the words but are not negotiations
        trilogues = [e for e in events if _code(e) == "INTERINSTITUTIONAL_NEGOTIATION" and e.date >= mandate.date]
        # negotiating since the first recorded trilogue; holding a mandate since the mandate decision
        return _S(
            "negotiations",
            "Negotiations with the Council" if trilogues else "Mandate to negotiate with the Council",
            (
                "Parliament's negotiators and the Council are negotiating the text. "
                if trilogues
                else "Parliament has a mandate to negotiate the text with the Council. "
            )
            + "Any agreement must then be approved by Parliament and by the Council.",
            trilogues[0].date if trilogues else mandate.date,
            "derived",
        )
    report = _last(events, EventKind.committee_report)
    if back and not (report and report.date > back.date):
        s = _S(
            "proposed",
            "Referred back to committee",
            f"On {_fmt(back.date)} Parliament referred the file back to the committee responsible for reconsideration"
            + (", so it holds no mandate to negotiate with the Council." if lapsed_mandate else "."),
            back.date,
            "derived",
        )
        s.next_step = NextStep(
            text="The committee reconsiders the file and reports again to Parliament; negotiations with the Council can "
            "start only after a new committee decision to negotiate or a plenary vote.",
            institution="EP",
            basis="derived",
        )
        return s
    if report:
        return _S(
            "proposed",
            "Committee report adopted",
            "Parliament's responsible committee has adopted its report on the proposal. "
            "Parliament as a whole has not yet taken its position, and the Council must also agree.",
            report.date,
            "derived",
        )
    start = _last(events, EventKind.referral) or _last(events, EventKind.proposal)
    return _S(
        "proposed",
        "Proposal under examination",
        "Parliament is examining the proposal. EU governments in the Council must also agree "
        "before it can become law.",
        start.date if start else None,
        "derived",
    )


_COUNCIL_DOC = re.compile(r"\d{5}/\d{2,4}")  # a numbered Council document, e.g. 06190/2026


def _commission_proposal_only(events: list[Event]) -> bool:
    """No Council text submitted to Parliament (a proposal event citing a Council document and no COM
    document), and no referral, committee report or decision of Parliament: only the Commission's proposal
    (which OEIL may list as a "Preparatory document")."""
    com = False
    for e in events:
        if e.kind in (EventKind.referral, EventKind.committee_report, EventKind.ep_position):
            return False
        ids = [d.id for d in e.docs]
        if e.kind == EventKind.proposal and (
            e.institution == "Council"
            or (any(_COUNCIL_DOC.fullmatch(i) for i in ids) and not any(i.startswith("COM(") for i in ids))
        ):
            return False
        com = com or (
            (e.kind == EventKind.proposal or e.raw_type == "oeil:Preparatory document")
            and any(i.startswith("COM(") for i in ids)
        )
    return com


def _cns_app_stage(ptype: str, events: list[Event]) -> _S:
    """Special legislative procedures: consultation (CNS) and consent (APP)."""
    adopt = _last(events, EventKind.council_adoption, EventKind.signature)
    if adopt:
        return _S(
            "adopted",
            "Adopted by the Council",
            # not "once published, it enters into force": the date an act sets can be that of its adoption (Council
            # Decision 2014/161/EU, 2013/0446(CNS): in force on 11 March 2014, published on 25 March 2014, as EUR-Lex
            # records), and a decision addressed to specific recipients takes effect on notification (Art. 297(2) TFEU)
            "The Council has adopted the act. It is not recorded as published in the Official Journal yet. It enters "
            "into force on the date it sets, which can be the day of its adoption, or, if it sets none, on the "
            "twentieth day after publication; a decision addressed to specific recipients takes effect on "
            "notification to them (Article 297 TFEU).",
            adopt.date,
            "source",
        )
    rej = _last(events, EventKind.rejection)
    ep_pos = _last(events, EventKind.ep_position)
    # In CNS/APP files the EP API often records Parliament's vote only as PLENARY_AMEND
    # ("Amending a text in plenary"); OEIL lists the same sitting as "Decision by Parliament".
    amend = [e for e in events if _code(e) == "PLENARY_AMEND"]
    if amend and (not ep_pos or amend[-1].date > ep_pos.date):
        ep_pos = amend[-1]
    if ptype == "APP" and rej and (not ep_pos or rej.date >= ep_pos.date):
        return _S(
            "rejected",
            "Consent refused by Parliament",
            "Parliament refused its consent. Under the consent procedure the Council cannot adopt "
            "the act without it.",
            rej.date,
            "source",
        )
    if ptype == "CNS" and rej and (not ep_pos or rej.date >= ep_pos.date):
        return _S(
            "parliament_position",
            "Parliament delivered a negative opinion",
            "Parliament voted to reject the proposal. Under the consultation procedure Parliament's "
            "opinion is not binding: the Council can still adopt the act.",
            rej.date,
            "derived",
        )
    if ep_pos:
        if ptype == "CNS":
            return _S(
                "parliament_position",
                "Parliament gave its opinion",
                "Parliament has delivered its opinion. Under the consultation procedure the Council "
                "takes the final decision; Parliament's opinion is not binding.",
                ep_pos.date,
                "derived",
            )
        return _S(
            "parliament_position",
            "Parliament voted on consent",
            "Parliament has taken its decision on consent. The Council can adopt the act only if "
            "Parliament has given its consent.",
            ep_pos.date,
            "derived",
        )
    report = _last(events, EventKind.committee_report)
    drafted = _last(events, EventKind.proposal)
    if ptype == "APP" and drafted and drafted.institution == "EP" and not any(
        e.kind in (EventKind.referral, EventKind.committee_report) and e.date >= drafted.date for e in events
    ):
        # Parliament's own proposal, with no Council draft submitted to Parliament since (Article 223(1) TFEU:
        # 2022/0902(APP), T9-0129/2022 of 3 May 2022, "Adopts the annexed proposal and submits it to the Council")
        s = _S(
            "proposed",
            "Parliament adopted its proposal",
            f"Parliament adopted its proposal for the act on {_fmt(drafted.date)}. Under this special legislative "
            "procedure the Council adopts the act on Parliament's proposal, after obtaining Parliament's consent; no "
            "Council draft submitted to Parliament for its consent is recorded in our data.",
            drafted.date,
            "derived",
        )
        s.next_step = NextStep(
            text="The Council agrees on the text of the act and asks for Parliament's consent; Parliament then decides "
            "whether to give it.",
            institution="Council",
            basis="derived",
        )
        return s
    start = report or _last(events, EventKind.referral) or _last(events, EventKind.proposal)
    if ptype == "CNS":
        expl = (
            "Parliament is preparing its opinion. Under the consultation procedure the Council "
            "decides, but only after receiving Parliament's opinion."
        )
    elif _commission_proposal_only(events):
        # Parliament consents to the Council's draft, which comes later (2025/0571(APP), MFF 2028-2034: only
        # COM(2025)0571 is recorded; Article 312(2) TFEU)
        expl = (
            "The Commission has made its proposal. Under the consent procedure the Council adopts the act only "
            "after Parliament has given its consent to the Council's draft; no Council draft submitted to "
            "Parliament is recorded in our data."
        )
    else:
        expl = (
            "Parliament is examining the file. Under the consent procedure the Council can adopt "
            "the act only if Parliament gives its consent."
        )
    return _S(
        "proposed",
        "Committee report adopted" if report else "Under examination in Parliament",
        expl,
        start.date if start else None,
        "derived",
    )


def _ep_act_stage(proc: Procedure, events: list[Event]) -> _S:
    """Acts that Parliament adopts with the Council's consent (PARLIAMENT_ADOPTS). OEIL records the Council's
    consent as "Act adopted by Council after consultation of Parliament"."""
    art = PARLIAMENT_ADOPTS.get(proc.id)
    under = f"Under this special legislative procedure{f' ({art})' if art else ''}"
    consent = _last(events, EventKind.council_adoption)
    ep_pos = _last(events, EventKind.ep_position)
    drafted = _last(events, EventKind.ep_position, EventKind.proposal)
    if consent and ep_pos and ep_pos.date >= consent.date:
        s = _S(
            "adopted",
            "Adopted by Parliament",
            f"Parliament adopted the act after the Council gave its consent{f' ({art})' if art else ''}. It still "
            "has to be published in the Official Journal.",
            ep_pos.date,
            "derived",
        )
        s.next_step = NextStep(text="Publication in the Official Journal of the EU.", institution="EUR-Lex", basis="derived")
    elif consent:
        s = _S(
            "parliament_position",
            "Council gave its consent",
            f"The Council gave its consent. {under} Parliament adopts the act, with the Council's consent.",
            consent.date,
            "source",
        )
        s.next_step = NextStep(text="Parliament adopts the act.", institution="EP", basis="derived")
    elif drafted and drafted.institution == "EP":
        s = _S(
            "parliament_position",
            "Parliament adopted its proposal",
            f"Parliament adopted its proposal for the act. {under} Parliament adopts the act only with the "
            "Council's consent.",
            drafted.date,
            "derived",
        )
        s.next_step = NextStep(
            text="The Council decides whether to give its consent; Parliament then adopts the act.",
            institution="Council",
            basis="derived",
        )
    else:
        start = _last(events, EventKind.committee_report, EventKind.referral)
        s = _S(
            "proposed",
            "Under examination in Parliament",
            f"{under} Parliament adopts the act itself, on its own initiative, with the Council's consent.",
            start.date if start else None,
            "derived",
        )
        s.next_step = NextStep(
            text="Parliament adopts its proposal for the act; the Council then decides whether to give its consent.",
            institution="EP",
            basis="derived",
        )
    return s


def _reconcile_with_oeil(proc: Procedure, s: _S, events: list[Event]) -> _S:
    """Use the official OEIL status label: confirms the derived stage (basis -> source) or,
    if it points to a later stage, takes precedence."""
    allowed = OEIL_STAGE.get(proc.stage_raw or "")
    if not allowed or s.stage not in RANK:
        return s
    if s.stage in allowed:
        if len(allowed) == 1:
            s.basis = "source"
        return s
    target = allowed[0]
    if RANK[target] <= RANK[s.stage]:
        return s  # label lags behind dated events; keep the recorded events
    if s.since and any((e.raw_type or "").startswith("ep_vote:") and e.date == s.since for e in events):
        return s  # a plenary vote that OEIL does not record yet (e.g. a referral back for negotiations)
    position = {
        "CNS": "Parliament has given its opinion; the Council takes the final decision.",
        "APP": "Parliament has decided on its consent; the Council takes the final decision.",
    }.get(proc.type, "Parliament has adopted its position; the Council has not yet acted on it.")
    labels = {
        "parliament_position": ("Awaiting Council action", position),
        "adopted": (
            "Adopted, awaiting publication",
            "The act has been adopted but not yet published in the Official Journal.",
        ),
        "negotiations": (
            "Second reading in Parliament",
            "The Council has adopted its position; Parliament has not yet concluded its second reading.",
        ),
        "proposed": ("Under examination in Parliament", "Parliament is examining the proposal."),
        "provisional_agreement": (
            "Provisional agreement reached",
            "A provisional agreement has been reached; it is not yet adopted.",
        ),
    }
    if proc.stage_raw == "Procedure completed":
        # no adoption, signature or act is recorded: OEIL's label alone does not say what was adopted, or
        # whether it was published (2021/0415(CNS) ended as a Council recommendation that our data lacks)
        return _S(
            "unknown",
            "Procedure completed",
            "Parliament's Legislative Observatory records the procedure as completed. No adoption, signature or "
            "publication of a final act is recorded in our data, so this page cannot say what the procedure "
            "produced. (Legislative Observatory status: “Procedure completed”.)",
            None,
            "source",
        )
    label, expl = labels.get(target, (proc.stage_raw or "", ""))
    return _S(
        target,
        label,
        f"{expl} (Legislative Observatory status: “{proc.stage_raw}”.)",
        None,
        "source",
    )


# ====================================================================== next steps
def _next_step(proc: Procedure, s: _S, events: list[Event], acts: list[LegalAct], today: date) -> NextStep:
    t = today.isoformat()
    ptype = proc.type
    stage = s.stage
    if s.next_step is not None:  # set with the stage (acts that Parliament adopts)
        return s.next_step
    if stage == "unknown" and s.label == "Procedure completed":
        return NextStep(text="Not determined: the procedure's final act is not linked in our data.", basis="unknown")
    if stage == "withdrawn" and s.label == "Replaced by a new Commission proposal":
        return NextStep(
            text="None: the procedure has ended. The Commission's new proposal is a separate legislative file.",
            basis="source",
        )
    if stage == "withdrawn":
        return NextStep(
            text="None: the procedure has ended. The proposal could only return as a new Commission proposal.",
            basis="derived",
        )
    if stage == "rejected":
        return NextStep(
            text="No further step is recorded. A rejection normally ends the procedure; the Commission "
            "may withdraw the proposal or present a new one.",
            basis="derived",
        )
    if stage == "lapsed":
        return NextStep(text="None: the procedure is closed.", basis="derived")
    if stage == "no_longer_in_force":
        return NextStep(text="None: the act is no longer in force.", basis="source")
    if stage == "takes_effect_on_notification":
        return NextStep(text="None: no further legislative step is required.", basis="derived")
    if stage in ("published", "in_force"):
        act = _main_act(proc, acts)
        app = application_of(acts, today)
        if act is None:
            return NextStep(
                text="Not determined: the final act's entry-into-force and application dates are not "
                "linked in our data.",
                basis="unknown",
            )
        if s.label == "No longer in force":
            return NextStep(text="None: the act is no longer in force.", basis="source")
        parts: list[str] = []
        basis: StepBasis = "derived"
        if app and app.entry_into_force and app.entry_into_force > t:
            parts.append(f"The act enters into force on {_fmt(app.entry_into_force)}.")
            basis = "source"
        elif app and app.entry_into_force_pending and act.in_force is False:
            return NextStep(
                text="Entry into force once every Member State has approved the decision in accordance with its "
                "constitutional requirements (Article 223(1) TFEU); EUR-Lex records no date yet."
                if ELECTORAL_ACT in act.amends
                else "Entry into force once the condition set in the act is met; EUR-Lex records no date yet.",
                basis="source",
            )
        if act.act_type == "directive":
            # the same directive as application.transposition (see transposition.py for the date kinds)
            dr = next((a for a in acts if a.act_type == "directive" and a.transposition_deadlines), None)
            tr = classify_transposition(dr) if dr else []
            general = next((x.date for x in tr if x.kind == "deadline"), None)
            specific = [x.date for x in tr if x.kind == "further_deadline"]
            earlier = [x for x in specific if general and x < general]
            # a deadline ("by" that date) has passed only once its day is over
            further = [x for x in specific if general and x > general and x >= t]
            start = application_start(dr, tr) if dr else None
            applies = [x.date for x in tr if x.kind == "application" and x.date > t and (not start or x.date > start)]
            # a directive binds the Member States to which it is addressed (Art. 288 TFEU): not those it is not
            # addressed to (Directive (EU) 2016/1629, Art. 40), nor Denmark or Ireland where a Treaty opt-out applies
            # (Protocols 21 and 22). Its own text can still give some of them more time or exempt them from
            # transposing it (Directive (EU) 2016/798, Art. 33(2), (2a) and (4)): stated as checked against the text
            exceptions = dr.transposition_checked.exceptions if dr and dr.transposition_checked else None
            unless = ", except as its text provides" if exceptions else ""
            if general and general >= t:
                parts.append(
                    f"The Member States bound by the directive must transpose it into national law by "
                    f"{_fmt(general)}{unless}."
                )
                parts += [exceptions] if exceptions else []
                basis = "source"
            elif general:
                parts.append(
                    f"The transposition deadline ({_fmt(general)}) has passed: the Member States bound by the "
                    f"directive were required to adopt national measures by then{unless}."
                )
                parts += [exceptions] if exceptions else []
                basis = "source"
            elif "(codification)" in act.title.lower():
                parts.append(
                    "This directive is a codification of earlier directives. EUR-Lex records no transposition "
                    "deadline for it."
                )
            else:
                parts.append(
                    "EUR-Lex records no transposition deadline for this directive; its text says whether, and by "
                    "when, national measures are needed."
                )
            if start and (start > t or applies):  # a past one only to set later dates apart from it
                sx = next(x for x in tr if x.date == start)
                latest = " at the latest" if "AU+TARD" in sx.labels and "ADOPTION" not in sx.labels else ""
                parts.append(
                    f"The national measures {'are' if start > t else 'were'} to apply from {_fmt(start)}{latest}."
                )
                # a later date for some measures (Directive (EU) 2024/1760, Art. 37(1), as replaced by Directive (EU)
                # 2026/470: the measures for Article 16 apply for financial years starting on or after 1 January 2030)
                chk = dr.transposition_checked if dr else None
                if chk and chk.application_exceptions and chk.applies_from == start:
                    parts.append(chk.application_exceptions)
            if earlier and general and general >= t:
                past = [x for x in earlier if x < t]
                plural = len(earlier) > 1
                what = "earlier transposition deadlines" if plural else "an earlier transposition deadline"
                if len(past) == len(earlier):
                    tail = f", which {'have' if plural else 'has'} passed: {_join_dates(earlier)}"
                else:
                    marked = [_fmt(x) + (" (passed)" if x < t else "") for x in earlier]
                    tail = ": " + (marked[0] if len(marked) == 1 else ", ".join(marked[:-1]) + " and " + marked[-1])
                parts.append(f"EUR-Lex records {what} for specific provisions{tail}.")
            if further:
                parts.append(
                    f"EUR-Lex records {'later transposition deadlines' if len(further) > 1 else 'a later transposition deadline'}"
                    f" for specific provisions: {_join_dates(further)}."
                )
            if applies:
                # never "the measures apply from": a later date may be optional ("may decide to apply ... at
                # the latest from", European Accessibility Act, Art. 31(3))
                plural = len(applies) > 1
                parts.append(
                    f"EUR-Lex records {'later application dates' if plural else 'a later application date'} for "
                    f"specific provisions: {_join_dates(applies)}."
                    if start
                    else f"EUR-Lex records {'dates' if plural else 'a date'} from which national measures are to "
                    f"apply: {_join_dates(applies)}."
                )
            return NextStep(text=" ".join(parts), institution=None, basis=basis)
        if act.act_type == "regulation":
            # never "in all EU countries": a regulation binds the Member States the Treaties make it bind, not those
            # with an opt-out (Regulation (EU) 2024/1348, recital 107: "Denmark is not taking part in the adoption of
            # this Regulation and is not bound by it") nor those outside an enhanced cooperation (Art. 20(4) TEU)
            applies = regulation_applies(act)
            if any(not x.partial for x in act.application_unrecorded):  # no date from which it applies in general
                parts.append(
                    f"A regulation {applies}; no national transposition is needed. "
                    + unrecorded_application_text(act).replace("the act in general", "this regulation in general")
                )
            else:
                parts.append(f"The regulation {applies}; no national transposition is needed.")
            pending = [d for d in (app.application_dates if app else []) if d > t]
            if pending:
                parts.append(
                    f"Later date{'s' if len(pending) > 1 else ''} from which (parts of) the act apply: "
                    f"{_join_dates(pending)}."
                )
                basis = "source"
            return NextStep(text=" ".join(parts), basis=basis)
        if act.act_type == "decision":
            parts.append("No further legislative step is required.")
            return NextStep(text=" ".join(parts), basis=basis)
        return NextStep(
            text=" ".join(parts) or "Not determined for this type of act.",
            basis=basis if parts else "unknown",
        )
    if stage == "adopted":
        if _last(events, EventKind.signature):
            return NextStep(
                text="Publication in the Official Journal of the EU.", institution="EUR-Lex", basis="derived"
            )
        if ptype == "COD":
            return NextStep(
                text="Signature by the Presidents of Parliament and the Council, then publication in "
                "the Official Journal.",
                basis="derived",
            )
        return NextStep(
            text="Publication in the Official Journal of the EU.", institution="EUR-Lex", basis="derived"
        )

    if ptype == "COD":
        if stage == "provisional_agreement":
            return NextStep(
                text="Parliament votes on the agreed text in plenary; the Council must then formally adopt it.",
                institution="EP",
                basis="derived",
            )
        if stage == "parliament_position":
            if s.label == "Parliament amended the Council's position":
                return NextStep(
                    text="The Council approves all of Parliament's amendments (the act is then adopted) or a "
                    "Conciliation Committee is convened.",
                    institution="Council",
                    basis="derived",
                )
            if s.label == "Parliament approved the conciliation text":
                return NextStep(
                    text="The Council must approve the joint text within six weeks (extendable by two) for the "
                    "act to be adopted.",
                    institution="Council",
                    basis="derived",
                )
            if s.label == "Approved by Parliament":
                return NextStep(
                    text="The Council formally approves Parliament's position; the act is then adopted.",
                    institution="Council",
                    basis="derived",
                )
            return NextStep(
                text="The Council either approves Parliament's position (the act is then adopted) or adopts "
                "its own first-reading position, which returns to Parliament for a second reading.",
                institution="Council",
                basis="derived",
            )
        if stage == "negotiations":
            if s.label == "Second reading in Parliament":
                return NextStep(
                    text="Parliament approves, amends or rejects the Council's position at second reading "
                    "(within three months, extendable by one; if Parliament does not act, the act is "
                    "deemed adopted).",
                    institution="EP",
                    basis="derived",
                )
            return NextStep(
                text="Parliament and Council negotiators seek a provisional agreement, which would then need "
                "approval by Parliament and the Council.",
                basis="derived",
            )
        if stage == "proposed":
            if _last(events, EventKind.committee_report):
                return NextStep(
                    text="Parliament votes on the committee report in plenary, or the committee negotiates "
                    "with the Council first.",
                    institution="EP",
                    basis="derived",
                )
            return NextStep(
                text="Parliament's responsible committee prepares and votes on its report.",
                institution="EP",
                basis="derived",
            )
    if ptype == "CNS":
        if stage == "parliament_position":
            return NextStep(
                text="The Council decides whether to adopt the act.", institution="Council", basis="derived"
            )
        if stage == "proposed":
            return NextStep(
                text="Parliament delivers its opinion; the Council then decides.",
                institution="EP",
                basis="derived",
            )
    if ptype == "APP":
        if stage == "parliament_position":
            return NextStep(
                text="If Parliament gave its consent, the Council can adopt the act.",
                institution="Council",
                basis="derived",
            )
        if stage == "proposed" and _commission_proposal_only(events):
            return NextStep(
                text="The Council agrees on its draft of the act and asks for Parliament's consent; Parliament "
                "then decides whether to give it.",
                institution="Council",
                basis="derived",
            )
        if stage == "proposed":
            return NextStep(
                text="Parliament decides whether to give its consent.", institution="EP", basis="derived"
            )
    return NextStep(text="Not determined from the recorded events.", basis="unknown")


# ====================================================================== entry point
def _consent_outcome(votes: Sequence[EpVote], day: str | None) -> str | None:
    """"adopted" or "rejected": the officially recorded outcome (decision or minutes) of the final votes linked to a
    consent file on the day of Parliament's decision, when they agree."""
    outcomes = {
        v.outcome
        for v in votes
        if v.date == day and v.kind == "final" and v.outcome_basis in ("published", "minutes")
    }
    return next(iter(outcomes)) if len(outcomes) == 1 and outcomes <= {"adopted", "rejected"} else None


def classify(
    proc: Procedure,
    acts: list[LegalAct],
    train: list[TrainFile],
    today: date,
    others: Mapping[str, LegalAct] | None = None,
    votes: Sequence[EpVote] = (),
) -> DossierStatus:
    """`others`: all known acts by CELEX, used only to name acts the procedure's acts refer to (the act that
    repealed one, for example) in the explanation. `votes`: Parliament's plenary votes linked to the file, used only
    for the outcome of its vote on consent."""
    t = today.isoformat()
    events = sorted((e for e in proc.events if e.date <= t), key=lambda e: e.date)
    ptype = proc.type
    if proc.stage_raw and proc.source.retrieved_at[:10] > t:
        # The OEIL label describes the file as of retrieval, i.e. after `today`: not usable.
        proc = proc.model_copy(update={"stage_raw": None})
    acts = relevant_acts(proc, acts, events, today)

    s: _S | None = None
    withdrawal = _last(events, EventKind.withdrawal)
    if withdrawal and (
        any(e.kind in ADOPTION_KINDS and e.date > withdrawal.date for e in events)
        or any((a.date_publication or a.date_document or "") > withdrawal.date for a in acts)
    ):
        withdrawal = None  # a recorded adoption after the withdrawal (e.g. of an earlier text) outranks it
    lapsed = _last(events, EventKind.lapsed)
    rejection = _last(events, EventKind.rejection)
    if withdrawal:
        replaced = withdrawal.raw_type == "cellar:RPL_byCOM"
        new = next((d.id for d in withdrawal.docs if d.kind == "proposal"), None)
        text = (
            "The Commission withdrew its proposal and replaced it with a new one"
            + (f" ({new})" if new else "")
            + ", so it will not become law in this form."
            if replaced
            else "The Commission withdrew its proposal, so it will not become law."
        )
        if rejection and rejection.date <= withdrawal.date:
            text += f" Parliament had rejected the proposal on {_fmt(rejection.date)}."
        else:
            text += " A withdrawal is a decision of the Commission, not a vote of Parliament."
        s = _S(
            "withdrawn",
            "Replaced by a new Commission proposal" if replaced else "Withdrawn by the Commission",
            text,
            withdrawal.date,
            "source",
        )
    elif lapsed:
        s = _S(
            "lapsed", "Lapsed", "The procedure lapsed without the act being adopted.", lapsed.date, "source"
        )
    elif proc.stage_raw == LAPSED_OR_WITHDRAWN:
        s = _S(
            "lapsed",
            "Lapsed or withdrawn",
            "Parliament's Legislative Observatory records this procedure as lapsed or withdrawn; "
            "the specific closing step is not recorded in our data. It will not become law.",
            None,
            "source",
        )
    elif rejection and ptype in ("COD", "SYN") and not _acts_stage(proc, acts, events, today):
        later_ok = [
            e
            for e in events
            if e.date > rejection.date
            and e.kind in (EventKind.ep_position, EventKind.council_adoption, EventKind.signature)
        ]
        if not later_ok:
            what = {
                "PLENARY_REJECT_COUNCIL_POSITION": "Parliament rejected the Council's position at second reading, "
                "so the act is not adopted (Article 294(7)(b) TFEU).",
                "PLENARY_REJECT_JOINT_TEXT": "Parliament rejected the text agreed in conciliation, so the act "
                "is not adopted.",
            }.get(
                _code(rejection),
                "Parliament voted to reject the proposal. This is different from a withdrawal by the Commission.",
            )
            s = _S("rejected", "Rejected by Parliament", what, rejection.date, "source")

    if s is None:
        s = _acts_stage(proc, acts, events, today, others)
    if s is None:
        if ptype in ("COD", "SYN"):
            s = _cod_stage(events)
        elif parliament_adopts(proc, acts):
            s = _ep_act_stage(proc, events)
        elif ptype in ("CNS", "APP", "AVC"):
            s = _cns_app_stage("APP" if ptype == "AVC" else ptype, events)
            outcome = _consent_outcome(votes, s.since) if s.label == "Parliament voted on consent" else None
            if outcome == "adopted":  # 2025/0313(APP): vote 197472 of 6 October 2026, adopted 462-121-75
                s = _S(
                    "parliament_position",
                    "Parliament gave its consent",
                    f"Parliament gave its consent on {_fmt(s.since or '')}. Under the consent procedure the Council "
                    "can now adopt the act.",
                    s.since,
                    "source",
                )
                s.next_step = NextStep(
                    text="The Council decides whether to adopt the act.", institution="Council", basis="derived"
                )
            elif outcome == "rejected":
                s = _S(
                    "rejected",
                    "Consent refused by Parliament",
                    "Parliament refused its consent. Under the consent procedure the Council cannot adopt the act "
                    "without it.",
                    s.since,
                    "source",
                )
        else:
            s = _generic_stage(ptype, events)
        s = _reconcile_with_oeil(proc, s, events)

    app = application_of(acts, today)
    next_step = _next_step(proc, s, events, acts, today)
    if s.stage in ACTIVE_STAGES and not acts:
        reported = _train_adopted(train, t)
        if reported:
            # The Train is not a record of adoption (it lags or leads OEIL); it only stops us from
            # asserting that a decision is still pending.
            unrecorded = s.label in UNRECORDED_COUNCIL_DECISION and ptype in ("CNS", "APP")
            if unrecorded:
                # 2025/0806(CNS): the Council's decision is not in the official records we hold, not pending
                s.explanation = f"{UNRECORDED_COUNCIL_DECISION[s.label]} {_no_final_act(proc)}"
            s.explanation += (
                f" The EP Legislative Train reports this file as “{reported.status}” (information updated as of "
                f"{_fmt(reported.last_updated)})" + ("." if unrecorded else ", but no final act is linked in our data.")
            )
            next_step = NextStep(
                text="Not determined: the EP Legislative Train reports the file as adopted, but the official "
                "records in our data do not yet show the final act.",
                basis="unknown",
            )
    if (
        s.stage == "parliament_position"
        and ptype in ("CNS", "APP")
        and events
        and (today - date.fromisoformat(events[-1].date)).days > STALE_DECISION_DAYS
    ):
        next_step = NextStep(
            text=f"Not determined: no final decision has been recorded in the official sources since "
            f"{_fmt(events[-1].date)}. The Council's public register may show whether it acted.",
            basis="unknown",
        )
    if (
        s.stage == "adopted"
        and s.since
        and not acts
        and not _last(events, EventKind.publication)
        and (today - date.fromisoformat(s.since)).days > STALE_DECISION_DAYS
    ):
        # adopted years ago and never recorded as published (2016/0810(CNS): Council 23 January 2017, OEIL still
        # "awaiting publication"): publication is no longer a safe next step
        if s.label == "Adopted by the Council":
            s.explanation = "The Council has adopted the act. No publication in the Official Journal is recorded in our sources."
        next_step = NextStep(
            text=f"Not determined: no publication in the Official Journal has been recorded in the official sources "
            f"since {_fmt(s.since)}.",
            basis="unknown",
        )
    return DossierStatus(
        stage=s.stage,  # type: ignore[arg-type]
        label=s.label,
        explanation=s.explanation,
        since=s.since,
        basis=s.basis,
        next_step=next_step,
        stall=None if s.label == "Procedure completed" else _stall(s.stage, events, train, today),
        application=app,
        named_acts=s.named_acts,
    )


# A consultation or consent file whose Council decision the Legislative Train reports but no official record we hold
# shows (no act linked): the stage's explanation without the suggestion that the decision is still to come
UNRECORDED_COUNCIL_DECISION = {
    "Parliament gave its opinion": "Parliament has delivered its opinion. Under the consultation procedure the Council "
    "takes the final decision; the official sources in our data do not record it.",
    "Parliament gave its consent": "Parliament has given its consent. Under the consent procedure the Council then adopts "
    "the act; the official sources in our data do not record its decision.",
    "Parliament voted on consent": "Parliament has taken its decision on consent. The Council can adopt the act only if "
    "Parliament has given its consent; the official sources in our data do not record the Council's decision.",
}


def _no_final_act(proc: Procedure) -> str:
    """What the official records we hold say of a file's final act when none is linked. 2025/0806(CNS): Council
    Regulation (EU) 2026/415 cites the documents of this file (ECB Recommendation ECB/2025/17, Commission Opinion
    C(2025)7526, "Opinion of 26 November 2025" of Parliament), but no official record links the two: Cellar records
    no procedure for the act, OEIL still gives "Awaiting final decision" and lists no final act, and the EP's
    procedure record lists none. The site does not link them either: the build names the regulation and what it cites
    in the file's status instead (data/curated/unlinked_acts.yaml, build.Builder.unlinked_act_status)."""
    oeil = (
        f"The Legislative Observatory gives the file's stage as “{proc.stage_raw}” and lists no final act, and no"
        if proc.stage_raw and not proc.celex_refs
        else "No"
    )
    return f"{oeil} act in our EUR-Lex data is recorded as adopted under this procedure."


# A consultation or consent file with no recorded step for this long: a pending Council decision is no
# longer a safe assumption (e.g. agreements whose legal basis has since been replaced).
STALE_DECISION_DAYS = 3 * 365


def _train_adopted(train: list[TrainFile], t: str) -> TrainFile | None:
    for tf in train:
        if (tf.status or "").lower().startswith("adopted") and tf.last_updated and tf.last_updated <= t:
            return tf
    return None


def _generic_stage(ptype: str, events: list[Event]) -> _S:
    """Non-legislative procedure types: only report what is recorded."""
    sig = _last(events, EventKind.signature, EventKind.council_adoption)
    if sig:
        return _S("adopted", "Adopted", "The act has been adopted.", sig.date, "source")
    ep_pos = _last(events, EventKind.ep_position)
    if ep_pos:
        return _S(
            "parliament_position",
            "Parliament took its decision",
            f"Parliament has voted. This is a {ptype or 'non-legislative'} procedure, which does not follow "
            "the legislative steps.",
            ep_pos.date,
            "derived",
        )
    return _S(
        "unknown",
        "Status not determined",
        f"The lifecycle of this {ptype or ''} procedure cannot be determined from the recorded events.".replace(
            "  ", " "
        ),
        None,
        "derived",
    )
