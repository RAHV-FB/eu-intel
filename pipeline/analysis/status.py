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
  (CNS) a negative Parliament opinion does not end the procedure.
- Inactivity is reported as a number of days without a recorded update. A file is only
  described as blocked with the Legislative Train's "Blocked" label (verbatim, with its URL and
  update date), and only while the procedure's own stage is still active. Train statuses never
  override recorded EP / EUR-Lex facts (adoption, publication, withdrawal).
- Dates are only taken from the inputs; nothing in the future is invented.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.analysis.transposition import article_label
from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.models.entities import Event, EventKind, Institution, LegalAct, Procedure, TrainFile

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
    # deadline: general transposition deadline; further_deadline: a later deadline for specific
    # provisions; application: a date from which national measures (must or may) apply
    kind: Literal["deadline", "further_deadline", "application"]
    articles: list[str] = Field(default_factory=list)  # article setting the date, e.g. "Art. 48(1)"


class Application(_M):
    entry_into_force: str | None = None
    entry_into_force_pending: bool = False  # EUR-Lex: enters into force on a condition not yet recorded as met
    entry_into_force_condition: str | None = None  # that condition, when the Treaty or EUR-Lex states it
    effect_on_notification: bool = False  # takes effect on notification to its addressee (date not recorded)
    application_dates: list[str] = Field(default_factory=list)
    partial_application_dates: list[str] = Field(default_factory=list)  # only some provisions apply from
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
        transposition_deadlines=[x.date for x in tr if x.kind != "application"],
        transposition=tr,
        future=future,
        after_end_of_validity=sorted(d for d in ended if d in app or d in {x.date for x in tr}),
    )


def transposition_info(acts: list[LegalAct]) -> list[TranspositionDateInfo]:
    """Classified transposition dates of the first directive among the acts (see transposition.py)."""
    for a in acts:
        if a.act_type == "directive" and a.transposition_deadlines:
            return [
                TranspositionDateInfo(date=x.date, kind=x.kind, articles=[article_label(r) for r in x.articles])
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


def _no_longer_in_force(act: LegalAct, others: Mapping[str, LegalAct]) -> _S:
    eov = act.end_of_validity
    how, refs = _ended_by(act, others)
    by = f" EUR-Lex records it as {how} by {_labels(refs)}" if refs else ""
    if eov and _retroactive_end(act):
        which = (
            f"which is dated {_fmt(act.date_document)}"
            if act.date_document
            else f"published on {_fmt(act.date_publication or '')}"
        )
        text = (
            f"The act was adopted and published, but EUR-Lex gives {_fmt(eov)} as the end of its validity, a date "
            f"earlier than the act itself, {which}."
        )
        text += f"{by}, with effect from that earlier date." if refs else " EUR-Lex records no reason for the earlier date."
    elif eov:
        text = f"The act was adopted and published, but its validity ended on {_fmt(eov)}." + (by + "." if by else "")
    else:
        text = "The act was adopted and published, but EUR-Lex records it as no longer in force." + (
            by + "." if by else ""
        )
    s = _S("no_longer_in_force", "No longer in force", text + _rules_continue(act, refs, others), eov, "source")
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
        if act.end_of_validity and act.end_of_validity <= t:
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
            later = [d for a in acts for d in a.other_application_dates if d and eif and d > eif]
            if later:
                text += (
                    " Entry into force is not the same as application: EUR-Lex records later dates from "
                    "which (parts of) the act apply."
                )
            # an end of validity still ahead, and the act that repeals it (32015L0849: validity ends on
            # 9 July 2027, repealed by Directive (EU) 2024/1640)
            refs = [_ref(c, others) for c in act.repealed_by]
            if act.end_of_validity:
                text += f" EUR-Lex records that its validity ends on {_fmt(act.end_of_validity)}" + (
                    f" and that {_labels(refs)} repeals it." if refs else "."
                )
            elif refs:
                text += f" EUR-Lex also records it as repealed by {_labels(refs)}."
            s = _S("in_force", "In force", text, eif or pub_date, basis)
            s.named_acts = refs
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


def _cod_stage(events: list[Event]) -> _S:
    """Ordinary legislative procedure (Art. 294 TFEU), from recorded events only."""
    sig = _last(events, EventKind.signature)
    if sig:
        return _S(
            "adopted",
            "Signed, awaiting publication",
            "Parliament and the Council have adopted the act and it has been signed. "
            "It becomes applicable law only after publication in the Official Journal.",
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
    mandate = _last(events, EventKind.negotiation_mandate)
    if mandate:
        # a recorded trilogue (EP activity INTERINSTITUTIONAL_NEGOTIATION) after the mandate; the
        # mandate decisions themselves (PLENARY_ENDORSE/REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS)
        # also contain the words but are not negotiations
        trilogues = [e for e in events if _code(e) == "INTERINSTITUTIONAL_NEGOTIATION" and e.date >= mandate.date]
        return _S(
            "negotiations",
            "Negotiations with the Council" if trilogues else "Mandate to negotiate with the Council",
            (
                "Parliament's negotiators and the Council are negotiating the text. "
                if trilogues
                else "Parliament has a mandate to negotiate the text with the Council. "
            )
            + "Any agreement must then be approved by Parliament and by the Council.",
            mandate.date,
            "derived",
        )
    report = _last(events, EventKind.committee_report)
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


def _cns_app_stage(ptype: str, events: list[Event]) -> _S:
    """Special legislative procedures: consultation (CNS) and consent (APP)."""
    adopt = _last(events, EventKind.council_adoption, EventKind.signature)
    if adopt:
        return _S(
            "adopted",
            "Adopted by the Council",
            "The Council has adopted the act. It becomes applicable law only after publication "
            "in the Official Journal.",
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
    start = report or _last(events, EventKind.referral) or _last(events, EventKind.proposal)
    if ptype == "CNS":
        expl = (
            "Parliament is preparing its opinion. Under the consultation procedure the Council "
            "decides, but only after receiving Parliament's opinion."
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
        label, expl = (
            "Procedure completed",
            "The procedure is completed. Signature and publication details are not linked in our data.",
        )
    else:
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
            tr = app.transposition if app else []
            general = next((x.date for x in tr if x.kind == "deadline"), None)
            further = [x.date for x in tr if x.kind == "further_deadline" and x.date > t]
            applies = [x.date for x in tr if x.kind == "application" and x.date > t and general and x.date > general]
            if general and general > t:
                parts.append(f"EU countries must transpose the directive into national law by {_fmt(general)}.")
                basis = "source"
            elif general:
                parts.append(
                    f"The transposition deadline ({_fmt(general)}) has passed: EU countries were required "
                    "to adopt national measures by then."
                )
                basis = "source"
            else:
                parts.append(
                    "EU countries must transpose the directive into national law; the deadline is not "
                    "recorded in our data."
                )
            if further:
                parts.append(
                    f"EUR-Lex records {'later transposition deadlines' if len(further) > 1 else 'a later transposition deadline'}"
                    f" for specific provisions: {_join_dates(further)}."
                )
            if applies:
                later = len(applies) - 1
                parts.append(
                    f"The national measures are to apply from {_fmt(applies[0])}"
                    + (
                        f"; EUR-Lex records {later} later application date{'s' if later > 1 else ''} for "
                        "specific provisions."
                        if later
                        else "."
                    )
                )
            return NextStep(text=" ".join(parts), institution=None, basis=basis)
        if act.act_type == "regulation":
            parts.append(
                "The regulation applies directly in all EU countries; no national transposition is needed."
            )
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
        if s.label == "Procedure completed":
            return NextStep(
                text="Not determined: signature and publication of the final act are not linked in our data.",
                basis="unknown",
            )
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
        if stage == "proposed":
            return NextStep(
                text="Parliament decides whether to give its consent.", institution="EP", basis="derived"
            )
    return NextStep(text="Not determined from the recorded events.", basis="unknown")


# ====================================================================== entry point
def classify(
    proc: Procedure,
    acts: list[LegalAct],
    train: list[TrainFile],
    today: date,
    others: Mapping[str, LegalAct] | None = None,
) -> DossierStatus:
    """`others`: all known acts by CELEX, used only to name acts the procedure's acts refer to (the act that
    repealed one, for example) in the explanation."""
    t = today.isoformat()
    events = sorted((e for e in proc.events if e.date <= t), key=lambda e: e.date)
    ptype = proc.type
    if proc.stage_raw and proc.source.retrieved_at[:10] > t:
        # The OEIL label describes the file as of retrieval, i.e. after `today`: not usable.
        proc = proc.model_copy(update={"stage_raw": None})
    acts = relevant_acts(proc, acts, events, today)

    s: _S | None = None
    withdrawal = _last(events, EventKind.withdrawal)
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
        elif ptype in ("CNS", "APP", "AVC"):
            s = _cns_app_stage("APP" if ptype == "AVC" else ptype, events)
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
            s.explanation += (
                f" The EP Legislative Train reports this file as “{reported.status}” (information updated as of "
                f"{_fmt(reported.last_updated)}), but no final act is linked in our data."
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
    return DossierStatus(
        stage=s.stage,  # type: ignore[arg-type]
        label=s.label,
        explanation=s.explanation,
        since=s.since,
        basis=s.basis,
        next_step=next_step,
        stall=_stall(s.stage, events, train, today),
        application=app,
        named_acts=s.named_acts,
    )


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
