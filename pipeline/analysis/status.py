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
  described as stalled/blocked with an official label (Legislative Train) and its URL.
- Dates are only taken from the inputs; nothing in the future is invented.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.models.entities import Event, EventKind, Institution, LegalAct, Procedure, TrainFile

Stage = Literal[
    "proposed",
    "parliament_position",
    "negotiations",
    "provisional_agreement",
    "adopted",
    "published",
    "in_force",
    "withdrawn",
    "rejected",
    "lapsed",
    "unknown",
]
Basis = Literal["source", "derived"]
StepBasis = Literal["source", "derived", "unknown"]

LEGISLATIVE_TYPES = {"COD", "CNS", "APP", "SYN", "AVC"}
TERMINAL: set[str] = {"published", "in_force", "withdrawn", "rejected", "lapsed"}

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
    "Procedure completed": ("adopted", "published", "in_force"),
}
LAPSED_OR_WITHDRAWN = "Procedure lapsed or withdrawn"
# Legislative Train statuses that are an official "stalled" assessment. The Train glossary
# defines "Blocked" as no progress over at least the previous nine months.
TRAIN_STALL_STATUSES = ("blocked",)

FIRST_READING_POSITION_CODES = {"PLENARY_ADOPT_POSITION", "PLENARY_AMEND_PROPOSAL", "PLENARY_DECISION"}


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
    official_label: str | None = None  # only an official assessment (Legislative Train)
    official_source_url: str | None = None


class Application(_M):
    entry_into_force: str | None = None
    application_dates: list[str] = Field(default_factory=list)
    transposition_deadlines: list[str] = Field(default_factory=list)  # directives only
    future: bool = False  # any of the above dates is after `today`


class DossierStatus(_M):
    stage: Stage
    label: str
    explanation: str
    since: str | None = None  # date of the event/record that established the stage
    basis: Basis
    next_step: NextStep
    stall: Stall | None = None
    application: Application | None = None


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


def _join_dates(ds: list[str]) -> str:
    f = [_fmt(d) for d in ds]
    return f[0] if len(f) == 1 else ", ".join(f[:-1]) + " and " + f[-1]


ADOPTION_KINDS = (EventKind.signature, EventKind.publication, EventKind.council_adoption)


def relevant_acts(proc: Procedure, acts: list[LegalAct], events: list[Event], today: date) -> list[LegalAct]:
    """Acts that can establish this procedure's status. An act linked by EUR-Lex to several
    procedures (e.g. a new proposal that replaced an older one) only counts when this procedure
    itself shows the act was adopted under it: its final act (OEIL) or a recorded adoption,
    signature or publication. Acts dated after `today` are ignored."""
    t = today.isoformat()
    out = []
    adopted_here = any(e.kind in ADOPTION_KINDS for e in events) or (proc.stage_raw or "").startswith(
        "Procedure completed"
    )
    for a in acts:
        dated = a.date_publication or a.date_signature or a.date_document
        if dated and dated > t:
            continue
        if a.celex in proc.celex_refs or len(a.procedure_refs) <= 1 or adopted_here:
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
    tr = sorted({d for a in acts if a.act_type == "directive" for d in a.transposition_deadlines if d})
    future = any(d > t for d in ([eif] if eif else []) + app + tr)
    return Application(entry_into_force=eif, application_dates=app, transposition_deadlines=tr, future=future)


def _stall(stage: str, events: list[Event], train: list[TrainFile], today: date) -> Stall | None:
    if stage in TERMINAL:
        return None
    past = [e for e in events if e.date <= today.isoformat()]
    if not past:
        return None
    last = max(e.date for e in past)
    days = (today - date.fromisoformat(last)).days
    label = url = None
    for tf in train:
        if tf.status.strip().lower() in TRAIN_STALL_STATUSES:
            label, url = tf.status, tf.url
            break
    unit = "day" if days == 1 else "days"
    return Stall(
        days_since_last_event=days,
        last_event_date=last,
        text=f"No recorded procedural update in {days} {unit} (last recorded: {_fmt(last)}).",
        official_label=label,
        official_source_url=url,
    )


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


def _acts_stage(proc: Procedure, acts: list[LegalAct], events: list[Event], today: date) -> _S | None:
    """Published / in force, from EUR-Lex acts and the recorded publication."""
    t = today.isoformat()
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
            return _S(
                "published",
                "No longer in force",
                f"The act was adopted and published, but its validity ended on {_fmt(act.end_of_validity)}.",
                act.end_of_validity,
                "source",
            )
        if act.in_force is False and not act.end_of_validity:
            return _S(
                "published",
                "No longer in force",
                "The act was adopted and published, but EUR-Lex records it as no longer in force.",
                None,
                "source",
            )
        if act.in_force is True or (eif and eif <= t):
            basis: Basis = "source" if act.in_force is True else "derived"
            text = f"The act has been in force since {_fmt(eif)}." if eif else "The act is in force."
            later = [d for a in acts for d in a.other_application_dates if d and eif and d > eif]
            if later:
                text += (
                    " Entry into force is not the same as application: some provisions apply only from "
                    "later dates."
                )
            return _S("in_force", "In force", text, eif or pub_date, basis)
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
        trilogues = [
            e for e in events if "INTERINSTITUTIONAL_NEGOTIATION" in _code(e) and e.date >= mandate.date
        ]
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
        if act.act_type == "directive":
            future = [d for d in (app.transposition_deadlines if app else []) if d > t]
            past = [d for d in (app.transposition_deadlines if app else []) if d <= t]
            if future:
                parts.append(
                    f"EU countries must transpose the directive into national law by {_fmt(future[0])}"
                    + (" (further deadlines: " + _join_dates(future[1:]) + ")." if len(future) > 1 else ".")
                )
                basis = "source"
            elif past:
                parts.append(
                    f"The transposition deadline ({_fmt(past[-1])}) has passed: EU countries were required "
                    "to adopt national measures by then."
                )
                basis = "source"
            else:
                parts.append(
                    "EU countries must transpose the directive into national law; the deadline is not "
                    "recorded in our data."
                )
            return NextStep(text=" ".join(parts), institution=None, basis=basis)
        if act.act_type == "regulation":
            parts.append(
                "The regulation applies directly in all EU countries; no national transposition is needed."
            )
            pending = [d for d in (app.application_dates if app else []) if d > t]
            if pending:
                parts.append(f"Further dates recorded for its provisions: {_join_dates(pending)}.")
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
        if stage == "proposed":
            return NextStep(
                text="Parliament decides whether to give its consent.", institution="EP", basis="derived"
            )
    return NextStep(text="Not determined from the recorded events.", basis="unknown")


# ====================================================================== entry point
def classify(proc: Procedure, acts: list[LegalAct], train: list[TrainFile], today: date) -> DossierStatus:
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
        s = _S(
            "withdrawn",
            "Withdrawn by the Commission",
            "The Commission withdrew its proposal, so it will not become law. "
            "This is not a rejection by Parliament.",
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
        s = _acts_stage(proc, acts, events, today)
    if s is None:
        if ptype in ("COD", "SYN"):
            s = _cod_stage(events)
        elif ptype in ("CNS", "APP", "AVC"):
            s = _cns_app_stage("APP" if ptype == "AVC" else ptype, events)
        else:
            s = _generic_stage(ptype, events)
        s = _reconcile_with_oeil(proc, s, events)

    app = application_of(acts, today)
    return DossierStatus(
        stage=s.stage,  # type: ignore[arg-type]
        label=s.label,
        explanation=s.explanation,
        since=s.since,
        basis=s.basis,
        next_step=_next_step(proc, s, events, acts, today),
        stall=_stall(s.stage, events, train, today),
        application=app,
    )


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
