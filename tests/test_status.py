"""Legal-correctness invariants of pipeline.analysis.status.classify, on real procedures.

Procedures are built from the real captures in tests/fixtures/ep_procedures/ (EP Open Data API
+ OEIL); acts are the real EUR-Lex records of the eurlex snapshot (eurlex_acts.json). To look at
a procedure at an earlier date, events after that date are dropped and classify() ignores the
OEIL status label (which describes the file at retrieval time).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline.analysis.status import DossierStatus, classify, parliament_adopts
from pipeline.models.entities import LegalAct, Procedure, TrainFile
from pipeline.sources import ep_procedures as src

FIX = Path(__file__).parent / "fixtures" / "ep_procedures"
TODAY = date(2026, 10, 22)
RETRIEVED = "2026-10-22T12:00:00Z"

ACTS = [
    LegalAct.model_validate(a) for a in json.loads((FIX / "eurlex_acts.json").read_text(encoding="utf-8"))
]
# Real Legislative Train records (train snapshot) linked to the fixture procedures
TRAIN = [
    TrainFile.model_validate(t) for t in json.loads((FIX / "train_files.json").read_text(encoding="utf-8"))
]


def proc(pid: str) -> Procedure:
    data = json.loads((FIX / f"ep_{pid}.json").read_text(encoding="utf-8"))["data"][0]
    info = src.parse_oeil((FIX / f"oeil_{pid}.html").read_bytes())
    return src.build_procedure(data, RETRIEVED, info, lambda _id: None)


def acts_for(p: Procedure) -> list[LegalAct]:
    return [a for a in ACTS if p.reference in a.procedure_refs]


def status(pid: str, today: date = TODAY, train: list[TrainFile] | None = None) -> DossierStatus:
    p = proc(pid)
    return classify(p, acts_for(p), train or [], today)


def all_text(s: DossierStatus) -> str:
    parts = [s.label, s.explanation, s.next_step.text]
    if s.stall:
        parts.append(s.stall.text)
    return " ".join(parts)


# ============================================================ AI Act along its timeline
def test_ai_act_in_force_regulation_with_later_application_dates():
    s = status("2021-0106")
    assert (s.stage, s.basis, s.since) == ("in_force", "source", "2024-08-01")
    assert s.application is not None
    assert s.application.entry_into_force == "2024-08-01"
    # entry into force differs from application: later dates come from EUR-Lex only
    assert "2027-08-02" in s.application.application_dates
    assert s.application.future is True
    assert s.application.transposition_deadlines == []
    assert "applies directly" in s.next_step.text
    assert "transpos" not in s.next_step.text.replace("no national transposition", "")
    assert "2 August 2027" in s.next_step.text
    assert s.stall is None


def test_provisional_agreement_is_not_adoption():
    s = status("2021-0106", date(2024, 2, 20))  # committee approved the trilogue text on 13 Feb 2024
    assert s.stage == "provisional_agreement"
    assert s.since == "2024-02-13"
    assert "not adoption" in s.explanation
    assert s.next_step.institution == "EP"
    assert s.application is None


def test_parliament_approval_is_not_final_adoption():
    s = status("2021-0106", date(2024, 3, 20))  # plenary adopted its position on 13 Mar 2024
    assert s.stage == "parliament_position"
    assert s.label == "Approved by Parliament"
    assert "not law yet" in s.explanation
    assert s.next_step.institution == "Council"


def test_council_adoption_then_signature_is_not_publication():
    s = status("2021-0106", date(2024, 6, 1))  # Council adopted on 21 May 2024
    assert (s.stage, s.since, s.basis) == ("adopted", "2024-05-21", "source")
    assert "signed and published" in s.explanation
    s = status("2021-0106", date(2024, 6, 20))  # signed on 13 June 2024
    assert (s.stage, s.label, s.since) == ("adopted", "Signed, awaiting publication", "2024-06-13")
    assert s.next_step.institution == "EUR-Lex"
    assert s.stage != "published"
    # publication does not make the act "applicable law": it enters into force on the date it sets or the twentieth
    # day after publication (Art. 297(1) TFEU), and its rules can apply later (AI Act: from 2 August 2026)
    assert "applicable law" not in s.explanation
    assert s.explanation.endswith(
        "It is not recorded as published in the Official Journal yet; once published, it enters into force on the date "
        "it sets or, if it sets none, on the twentieth day after publication (Article 297(1) TFEU). Its rules can apply "
        "from later dates."
    )


def test_published_but_not_yet_in_force():
    s = status("2021-0106", date(2024, 7, 20))  # published 12 July, in force 1 August 2024
    assert (s.stage, s.label, s.since) == ("published", "Published, not yet in force", "2024-07-12")
    assert "1 August 2024" in s.explanation


def test_negotiation_mandate_after_partial_vote():
    s = status("2021-0106", date(2023, 7, 1))  # amendments voted + referred back on 14 June 2023
    assert s.stage == "negotiations"
    assert s.since == "2023-06-14"
    assert s.next_step.institution is None  # both co-legislators


# ============================================================ directives vs regulations
def test_directive_gets_transposition_next_step():
    s = status("2021-0104")  # CSRD, Directive (EU) 2022/2464
    assert s.stage == "in_force"
    assert s.application.transposition_deadlines == ["2024-07-06"]
    assert "transposition deadline (6 July 2024) has passed" in s.next_step.text
    early = status("2021-0104", date(2023, 3, 1))
    assert early.stage == "in_force"
    assert "must transpose it into national law by 6 July 2024" in early.next_step.text
    assert early.application.future is True


def test_regulations_never_get_transposition_steps():
    for pid in ("2021-0106", "2012-0011"):
        s = status(pid)
        assert s.stage == "in_force"
        assert "must transpose" not in s.next_step.text
        assert s.application.transposition_deadlines == []


# ============================================================ withdrawn / rejected / lapsed
def test_withdrawn_is_not_rejected_by_parliament():
    s = status("2017-0003")  # ePrivacy Regulation proposal, withdrawn 6 Oct 2025
    assert (s.stage, s.since, s.basis) == ("withdrawn", "2025-10-06", "source")
    assert "not a vote of Parliament" in s.explanation
    assert s.stall is None


def test_withdrawal_after_parliament_vote_is_still_withdrawal():
    # Sustainable use of pesticides: Parliament voted on 22 Nov 2023, Commission withdrew 6 May 2024
    s = status("2022-0196")
    assert (s.stage, s.since) == ("withdrawn", "2024-05-06")
    assert s.stage != "rejected"
    before = status("2022-0196", date(2024, 1, 15))
    assert before.stage == "parliament_position"


# ============================================================ pending files
def test_pending_first_reading_awaiting_council():
    s = status("2023-0126")  # EP first-reading position 28 Feb 2024; Council has not acted
    assert s.stage == "parliament_position"
    assert s.basis == "source"  # confirmed by OEIL "Awaiting Council's 1st reading position"
    assert s.next_step.institution == "Council"
    assert "Parliament's position" in s.next_step.text
    assert s.stall is not None and s.stall.official_label is None


def test_provisional_agreement_pending_plenary():
    s = status("2025-0134")
    assert s.stage == "provisional_agreement"
    assert s.next_step.institution == "EP"


def test_signed_not_yet_published():
    s = status("2024-0098")  # signed 21 Oct 2026
    assert (s.stage, s.label) == ("adopted", "Signed, awaiting publication")
    assert s.application is None


def test_trilogues_under_way():
    s = status("2024-0068")
    assert (s.stage, s.label) == ("negotiations", "Negotiations with the Council")


def test_consultation_opinion_is_not_binding():
    s = status("2023-0320")  # CNS: Parliament gave its opinion on 10 April 2024
    assert s.stage == "parliament_position"
    assert "not binding" in s.explanation
    assert s.next_step.institution == "Council"


def test_consent_procedure():
    s = status("2025-0313")  # APP
    assert s.stage == "parliament_position"
    assert "consent" in s.explanation
    assert s.next_step.institution == "Council"


# ============================================================ inactivity vs officially blocked
def train_for(p: Procedure) -> list[TrainFile]:
    return [t for t in TRAIN if p.reference in t.procedure_refs]


def test_inactivity_is_not_blocked():
    p = proc("2023-0448")  # animal transport: long without recorded steps; Train says "Tabled"
    assert [t.status for t in train_for(p)] == ["Tabled"]
    s = classify(p, acts_for(p), train_for(p), TODAY)
    assert s.stage == "proposed"
    last = max(e.date for e in p.events)
    assert s.stall.last_event_date == last
    assert s.stall.days_since_last_event == (TODAY - date.fromisoformat(last)).days
    assert s.stall.days_since_last_event > 270  # long inactivity ...
    assert s.stall.official_label is None  # ... but no official "Blocked" assessment
    assert s.stall.official_source_url is None and s.stall.official_text is None
    assert s.stall.text.startswith("No recorded procedural update in")
    assert "block" not in all_text(s).lower()


def test_blocked_only_with_official_train_label():
    p = proc("2023-0320")  # HOT (CNS): the Train classifies it "Blocked", naming the Council
    train = train_for(p)
    assert [(t.status, t.blocking_institution) for t in train] == [("Blocked", "COUNCIL")]
    s = classify(p, acts_for(p), train, TODAY)
    assert s.stage == "parliament_position"  # a Train label never changes the procedural stage
    assert s.stall.official_label == "Blocked"  # verbatim
    assert s.stall.official_source_url == train[0].url
    assert s.stall.official_label_date == train[0].last_updated
    assert s.stall.official_text.startswith("Classified as \u201cBlocked\u201d by the EP Legislative Train")
    assert "COUNCIL" in s.stall.official_text  # named only because the Train names it
    assert s.stall.text.startswith("No recorded procedural update in")  # own text stays neutral
    without = classify(p, acts_for(p), [], TODAY)
    assert without.stall.official_label is None
    assert "block" not in all_text(without).lower()


def test_train_label_not_used_before_its_update_date():
    p = proc("2023-0320")
    train = train_for(p)
    s = classify(p, acts_for(p), train, date.fromisoformat(train[0].last_updated) - timedelta(days=1))
    assert s.stall.official_label is None


def test_blocked_label_never_overrides_recorded_adoption():
    # A Train "Blocked" record passed for a dossier whose own recorded stage is no longer active
    # (e.g. a stale Train snapshot) must not be shown.
    blocked = train_for(proc("2023-0320"))[0]
    for pid in ("2024-0098", "2021-0106", "2017-0003"):  # signed / in force / withdrawn
        s = classify(proc(pid), acts_for(proc(pid)), [blocked], TODAY)
        assert s.stage in ("adopted", "in_force", "withdrawn")
        assert s.stall is None or s.stall.official_label is None, pid


def test_lagging_train_status_does_not_override_facts():
    # The Train still says "Close to adoption" for the Return Regulation, in force since 15 Oct 2026
    p = proc("2025-0059")
    assert [t.status for t in train_for(p)] == ["Close to adoption"]
    s = classify(p, acts_for(p), train_for(p), TODAY)
    assert s.stage == "in_force" and s.since == "2026-10-15"
    # ... and for a file signed on 21 Oct 2026
    p = proc("2024-0098")
    assert [t.status for t in train_for(p)] == ["Close to adoption"]
    assert classify(p, acts_for(p), train_for(p), TODAY).label == "Signed, awaiting publication"


def test_train_withdrawn_is_not_a_recorded_withdrawal():
    # The Train lists the 2018 Return Directive recast as "Withdrawn"; neither the EP nor OEIL
    # records a withdrawal, so the recorded procedural stage is kept.
    p = proc("2018-0329")
    assert [t.status for t in train_for(p)] == ["Withdrawn"]
    s = classify(p, [], train_for(p), TODAY)
    assert s.stage == "proposed"
    assert classify(proc("2017-0003"), [], train_for(proc("2017-0003")), TODAY).stage == "withdrawn"


# ============================================================ act linkage
def test_act_linked_to_several_procedures_needs_evidence():
    # Cellar links the 2026 Return Regulation to 2018/0329(COD) and 2025/0059(COD); the 2018
    # file itself records no adoption, so the act does not make it "in force".
    p = proc("2018-0329")
    assert [a.celex for a in acts_for(p)] == ["32026R2280"]
    s = classify(p, acts_for(p), [], TODAY)
    assert s.stage == "proposed"
    assert s.application is None


# ============================================================ no invented dates
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


@pytest.mark.parametrize("pid", sorted(p.stem[3:] for p in FIX.glob("ep_2*.json")))
@pytest.mark.parametrize("today", [TODAY, date(2024, 3, 20), date(2019, 1, 1)])
def test_no_dates_invented(pid, today):
    p = proc(pid)
    acts = acts_for(p)
    s = classify(p, acts, [], today)
    known = {e.date for e in p.events}
    for a in acts:
        known |= {
            d
            for d in [
                a.entry_into_force,
                a.date_publication,
                a.date_signature,
                a.date_document,
                a.end_of_validity,
            ]
            + a.other_application_dates
            + a.transposition_deadlines
            if d
        }
    used = {s.since} if s.since else set()
    if s.stall:
        used.add(s.stall.last_event_date)
        assert s.stall.last_event_date <= today.isoformat()
    if s.application:
        used |= {d for d in [s.application.entry_into_force] if d}
        used |= set(s.application.application_dates) | set(s.application.transposition_deadlines)
    for m in re.finditer(rf"(\d{{1,2}}) ({MONTHS}) (\d{{4}})", all_text(s)):
        month = MONTHS.split("|").index(m[2]) + 1
        used.add(f"{m[3]}-{month:02d}-{int(m[1]):02d}")
    assert used <= known, used - known
    if s.since:
        assert s.since <= today.isoformat()


# ============================================================ whole snapshot (if present)
SNAPSHOT = Path(__file__).parent.parent / "data" / "snapshot" / "ep_procedures" / "procedures.json"


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="no ep_procedures snapshot")
def test_snapshot_invariants():
    procs = [Procedure.model_validate(x) for x in json.loads(SNAPSHOT.read_text(encoding="utf-8"))]
    for p in procs:
        s = classify(p, [], [], TODAY)
        kinds = {e.kind.value for e in p.events}
        if s.stage == "adopted" and p.type == "COD":
            assert kinds & {"signature", "council_adoption", "ep_position"} or p.stage_raw, p.id
        if s.stage == "withdrawn":
            assert "withdrawal" in kinds, p.id
        if p.type == "CNS":
            assert s.stage != "rejected", p.id
        if s.stage in ("in_force", "published", "withdrawn", "rejected", "lapsed"):
            assert s.stall is None, p.id
        assert "block" not in all_text(s).lower(), p.id


def test_expired_or_repealed_act_is_no_longer_in_force_not_published():
    # The same real act, as if its validity had ended (e.g. repealed by a recast): it must not be
    # classified as "published, not yet in force".
    p = proc("2021-0106")
    expired = [a.model_copy(update={"end_of_validity": "2025-01-01", "in_force": False}) for a in acts_for(p)]
    s = classify(p, expired, [], TODAY)
    assert (s.stage, s.label) == ("no_longer_in_force", "No longer in force")
    assert s.next_step.text.startswith("None")
    no_date = [a.model_copy(update={"end_of_validity": None, "in_force": False}) for a in acts_for(p)]
    assert classify(p, no_date, [], TODAY).stage == "no_longer_in_force"


def test_act_pending_entry_into_force_is_not_no_longer_in_force():
    # Electoral Act amendments (e.g. Decision 2018/994): EUR-Lex "not in force", entry into force
    # 1001-01-01 (pending approval by every Member State), no end of validity
    p = proc("2021-0106")
    pending = [
        a.model_copy(
            update={"entry_into_force": None, "entry_into_force_pending": True, "in_force": False,
                    "end_of_validity": None, "other_application_dates": []}
        )
        for a in acts_for(p)
    ]  # fmt: skip
    s = classify(p, pending, [], TODAY)
    assert (s.stage, s.label) == ("published", "Published, not yet in force")
    assert "not yet in force" in s.explanation and "no longer" not in all_text(s).lower()
    assert s.next_step.text.startswith("Entry into force once the condition")
    assert s.application is not None and s.application.entry_into_force_pending


def test_repealed_act_names_the_repealing_act():
    p = proc("2021-0106")
    repealed = [
        a.model_copy(update={"end_of_validity": "2025-01-01", "in_force": False, "repealed_by": ["32026R0001"]})
        for a in acts_for(p)
    ]
    s = classify(p, repealed, [], TODAY)
    assert s.stage == "no_longer_in_force"
    # an act not in our data is named by the number its CELEX id gives, and linked to EUR-Lex
    assert "repealed by Regulation 2026/1." in s.explanation
    assert [(r.celex, r.url) for r in s.named_acts] == [
        ("32026R0001", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R0001")
    ]


def test_directive_next_step_uses_general_deadline_not_application_date():
    # Consumer Credit Directive 2023/2225, Art. 48(1): adopt and publish by 20 November 2025, apply
    # from 20 November 2026 (Cellar labels ADOPTION / APPLICATION)
    from pipeline.models.entities import TranspositionDate

    p = proc("2021-0104")
    dated = [
        a.model_copy(
            update={
                "transposition_deadlines": ["2025-11-20", "2026-11-20"],
                "transposition_dates": [
                    TranspositionDate(date="2025-11-20", labels=["ADOPTION"], articles=["48.1"]),
                    TranspositionDate(date="2026-11-20", labels=["APPLICATION"], articles=["48.1"]),
                ],
            }
        )
        for a in acts_for(p)
    ]
    s = classify(p, dated, [], TODAY)
    assert "transposition deadline (20 November 2025) has passed" in s.next_step.text
    assert "must transpose" not in s.next_step.text
    assert "apply from 20 November 2026" in s.next_step.text
    assert s.application.transposition_deadlines == ["2025-11-20"]
    assert [(x.date, x.kind, x.articles) for x in s.application.transposition] == [
        ("2025-11-20", "deadline", ["Art. 48(1)"]),
        ("2026-11-20", "application", ["Art. 48(1)"]),
    ]


def _directive_step(celex: str, today: date = TODAY) -> str:
    """Next step of the CSRD procedure if its act carried another directive's real transposition record
    (tests/fixtures/eurlex/transposition_acts.json, with the checks of data/curated/transposition.yaml)."""
    from pipeline.build import apply_transposition_checks, load_transposition_checks

    recs = json.loads((FIX.parent / "eurlex" / "transposition_acts.json").read_text(encoding="utf-8"))
    r = apply_transposition_checks(
        LegalAct.model_validate(next(x for x in recs if x["celex"] == celex)), load_transposition_checks().get(celex)
    )
    keep = ("title", "transposition_deadlines", "transposition_dates", "transposition_checked")
    p = proc("2021-0104")
    acts = [a.model_copy(update={k: getattr(r, k) for k in keep}) for a in acts_for(p)]
    return classify(p, acts, [], today).next_step.text


def test_amld6_next_step_names_the_general_deadline_not_a_derogation():
    # Directive (EU) 2024/1640, Art. 78(1): 10 July 2027 in general; 2025, 2026 and 2029 for specific articles
    text = _directive_step("32024L1640")
    assert text.startswith("The Member States bound by the directive must transpose it into national law by 10 July 2027.")
    assert "earlier transposition deadlines for specific provisions, which have passed: 10 July 2025 and 10 July 2026" in text
    assert "later transposition deadline for specific provisions: 10 July 2029" in text
    assert "has passed: the Member States bound by the directive were required" not in text


def test_a_transposition_deadline_has_passed_only_once_its_day_is_over():
    # Directive (EU) 2024/1640, Art. 78(1): "... necessary to comply with this Directive by 10 July 2027", and
    # "with Articles 11, 12, 13 and 15 by 10 July 2026 and with Article18 by 10 July 2029": on the day itself the
    # measures are still due, not overdue (the build said "has passed" on that day)
    on_day = _directive_step("32024L1640", date(2027, 7, 10))
    assert on_day.startswith("The Member States bound by the directive must transpose it into national law by 10 July 2027.")
    assert "later transposition deadline for specific provisions: 10 July 2029" in on_day
    after = _directive_step("32024L1640", date(2027, 7, 11))
    assert after.startswith("The transposition deadline (10 July 2027) has passed")
    earlier = _directive_step("32024L1640", date(2026, 7, 10))
    assert "earlier transposition deadlines for specific provisions: 10 July 2025 (passed) and 10 July 2026." in earlier
    assert "10 July 2029" in _directive_step("32024L1640", date(2029, 7, 10))
    assert "10 July 2029" not in _directive_step("32024L1640", date(2029, 7, 11))


def test_driving_licences_next_step():
    # Directive (EU) 2025/2205, Art. 29: adopt by 26 November 2028, apply from 26 November 2029; Art. 9(2)(j), (k)
    # by 26 November 2027
    text = _directive_step("32025L2205")
    assert "must transpose it into national law by 26 November 2028." in text
    assert "The national measures are to apply from 26 November 2029." in text
    assert "an earlier transposition deadline for specific provisions: 26 November 2027" in text


@pytest.mark.parametrize(
    "celex, general, later",
    [
        ("32019L0882", "28 June 2025", "28 June 2027"),  # EAA Art. 31: 2027 is an optional derogation
        ("32024L1619", "11 January 2026", "11 January 2027"),  # CRD VI Art. 2(1)
        ("32024L0927", "16 April 2026", "16 April 2027"),  # AIFMD II Art. 3(1)
        ("32023L2226", "1 January 2026", "1 January 2028 and 1 January 2030"),  # DAC8 Art. 2
        ("32025L0872", "1 January 2026", "1 January 2028"),  # DAC9 Art. 2(1), (3)
    ],
)
def test_general_application_date_is_stated_and_later_ones_are_for_specific_provisions(celex, general, later):
    text = _directive_step(celex)
    assert f"The national measures were to apply from {general}." in text
    assert f"for specific provisions: {later}." in text
    assert f"apply from {later}" not in text


def test_application_date_still_ahead():
    # Directive (EU) 2026/804, Art. 3(1): apply from 11 May 2028; Art. 11(3) and others from 11 May 2029
    text = _directive_step("32026L0804")
    assert "The national measures are to apply from 11 May 2028." in text
    assert "later application date for specific provisions: 11 May 2029." in text


def test_directives_without_a_transposition_date_are_not_told_to_transpose():
    codification = _directive_step("32022L2561")  # Directive (EU) 2022/2561 (codification): no transposition article
    assert codification == (
        "This directive is a codification of earlier directives. EUR-Lex records no transposition deadline for it."
    )
    other = _directive_step("32024L1306")  # time limits for sustainability reporting standards: no such clause
    assert other.startswith("EUR-Lex records no transposition deadline for this directive")
    assert "must transpose" not in codification + other


def _with_events(p: Procedure, *events) -> Procedure:
    return p.model_copy(update={"events": sorted([*p.events, *events], key=lambda e: e.date)})


def _event(kind: str, d: str, raw: str, title: str, institution: str = "EP", docs=()):
    from pipeline.models.entities import DocRef, Event, EventKind, SourceRef

    return Event(
        id=f"t-{raw}-{d}", date=d, kind=EventKind(kind), raw_type=raw, institution=institution, title=title,
        docs=[DocRef(id=x, label=x, kind="proposal") for x in docs],
        source=SourceRef(institution="EUR-Lex", url="https://eur-lex.europa.eu/", retrieved_at=RETRIEVED),
    )  # fmt: skip


def test_withdrawal_after_rejection_names_the_rejection():
    # Sustainable use of pesticides: Parliament rejected the proposal on 22 November 2023 (final vote
    # 161821), the Commission withdrew it on 6 May 2024: never "not a rejection by Parliament"
    p = _with_events(
        proc("2022-0196"),
        _event("rejection", "2023-11-22", "ep_vote:final:rejected", "Parliament rejected the proposal"),
    )
    s = classify(p, [], [], TODAY)
    assert s.stage == "withdrawn"
    assert "Parliament had rejected the proposal on 22 November 2023" in s.explanation
    assert "not a vote of Parliament" not in s.explanation


def test_replaced_proposal():
    # Cellar RPL_byCOM on 2018/0329(COD): replaced by COM(2025)0101 (the Return Regulation)
    p = _with_events(
        proc("2018-0329"),
        _event("withdrawal", "2025-03-11", "cellar:RPL_byCOM", "Commission withdrew the proposal and replaced it",
               "Commission", docs=["COM(2025)0101"]),
    )  # fmt: skip
    s = classify(p, acts_for(p), [], TODAY)
    assert (s.stage, s.label, s.since) == ("withdrawn", "Replaced by a new Commission proposal", "2025-03-11")
    assert "COM(2025)0101" in s.explanation
    assert s.next_step.text.startswith("None")


def test_mandate_decision_alone_is_not_negotiations():
    # the plenary endorsing the committee's decision to negotiate (EP activity code containing
    # "INTERINSTITUTIONAL_NEGOTIATIONS") is not a trilogue
    p = proc("2024-0068")
    first_mandate = next(e for e in p.events if e.kind.value == "negotiation_mandate")
    early = [
        e for e in p.events
        if e.date <= first_mandate.date and (e.raw_type or "").rsplit("/", 1)[-1] != "INTERINSTITUTIONAL_NEGOTIATION"
    ]  # fmt: skip
    endorse = _event("negotiation_mandate", first_mandate.date,
                     "def/ep-activities/PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
                     "Plenary endorsed the committee decision to open negotiations")  # fmt: skip
    s = classify(p.model_copy(update={"events": [*early, endorse], "stage_raw": None}), [], [], TODAY)
    assert (s.stage, s.label) == ("negotiations", "Mandate to negotiate with the Council")


def test_stale_consultation_does_not_assert_a_pending_council_decision():
    s = status("2023-0320", date(2030, 1, 1))  # CNS opinion of 10 April 2024, nothing since
    assert s.stage == "parliament_position"
    assert s.next_step.basis == "unknown" and s.next_step.text.startswith("Not determined")
    recent = status("2023-0320", date(2024, 6, 1))
    assert "Council decides" in recent.next_step.text


# ============================================================ act validity (real EUR-Lex records)
# tests/fixtures/eurlex/validity_acts.json: the snapshot records of these acts (subjects left out)
VALIDITY = {
    a.celex: a
    for a in (
        LegalAct.model_validate(x)
        for x in json.loads((FIX.parent / "eurlex" / "validity_acts.json").read_text(encoding="utf-8"))
    )
}
TODAY_V = date(2026, 10, 23)


def _bare_proc(ref: str, ptype: str, celex_refs: list[str]) -> Procedure:
    from pipeline.models.entities import SourceRef

    return Procedure(
        id=ref[:9].replace("/", "-"), reference=ref, type=ptype, title=ref, stage_raw="Procedure completed",
        celex_refs=celex_refs, oeil_url=f"https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference={ref}",
        source=SourceRef(institution="EP", url="https://data.europarl.europa.eu/", retrieved_at=RETRIEVED),
    )  # fmt: skip


def act_status(celex: str, ref: str, ptype: str = "COD") -> DossierStatus:
    return classify(_bare_proc(ref, ptype, [celex]), [VALIDITY[celex]], [], TODAY_V, others=VALIDITY)


def test_decision_addressed_to_a_member_state_takes_effect_on_notification():
    # Decision (EU) 2020/853, Art. 3: "This Decision is addressed to the Federal Republic of Germany".
    # Cellar: date of effect (PE) 1001-01-01, comment DATNOT; in force 0. Not "not yet in force".
    s = act_status("32020D0853", "2019/0107(COD)")
    assert (s.stage, s.label, s.since) == ("takes_effect_on_notification", "Takes effect on notification", "2020-06-22")
    assert "EUR-Lex gives its date of effect as the date of notification to them, without recording" in s.explanation
    assert "297" not in s.explanation  # Art. 297(2) TFEU is about non-legislative acts; this one is legislative
    assert "not yet in force" not in all_text(s) and "no longer" not in all_text(s).lower()
    assert s.next_step.text.startswith("None") and "once" not in s.next_step.text
    assert s.application.effect_on_notification and not s.application.entry_into_force_pending


def test_partial_end_of_validity_names_the_later_decision():
    # Decision (EU) 2020/1531 (France, Channel Fixed Link): Cellar records a partial end of validity on
    # 2024-03-17 "V 32024D0867 ART 6"; Art. 6 of Decision (EU) 2024/867: "Decision (EU) 2020/1531 remains
    # applicable to the extent referred to in Article 5(2)."
    s = act_status("32020D1531", "2020/0160(COD)")
    assert s.stage == "takes_effect_on_notification"
    assert "partial end of its validity on 17 March 2024 and refers to Decision (EU) 2024/867." in s.explanation
    assert [(r.celex, r.label) for r in s.named_acts] == [("32024D0867", "Decision (EU) 2024/867")]


def test_electoral_act_amendment_needs_approval_by_every_member_state():
    # Decision 2018/994, Art. 2(1): "subject to approval by the Member States in accordance with their
    # respective constitutional requirements"; Art. 2(2): enters into force after the last notification
    s = act_status("32018D0994", "2015/0907(APP)", "APP")
    assert (s.stage, s.label) == ("published", "Published, not yet in force")
    assert "every Member State has approved it in accordance with its constitutional requirements" in s.explanation
    assert "(Article 223(1) TFEU); EUR-Lex refers to Art. 2(2) of the decision" in s.explanation
    assert s.next_step.text.startswith("Entry into force once every Member State has approved the decision")
    assert "Article 223(1) TFEU" in (s.application.entry_into_force_condition or "")


def test_repealed_by_a_codification_names_it_and_says_the_rules_continue():
    # Directive (EU) 2017/853 (firearms), repealed by Directive (EU) 2021/555 "... (codification)"
    s = act_status("32017L0853", "2015/0269(COD)")
    assert s.stage == "no_longer_in_force"
    assert "EUR-Lex records it as repealed by Directive (EU) 2021/555." in s.explanation
    assert "Directive (EU) 2021/555 is a codification: the rules continue in it, unchanged in substance" in s.explanation
    assert "32021L0555" not in s.explanation
    assert [(r.celex, r.label, r.url) for r in s.named_acts] == [
        ("32021L0555", "Directive (EU) 2021/555", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32021L0555")
    ]


def test_end_of_validity_before_the_act_itself_is_explained():
    # Council Regulation 1377/2014 of 18 December 2014: Cellar end of validity 2013-12-31, "Implicitly
    # repealed by 32014R0609" - the own-resources recast of 26 May 2014, older than the act: its rules cannot
    # "continue" in it
    # "No longer in force" since the day after the last day of validity: Regulation 609/2014, Art. 19, "It shall
    # apply from 1 January 2014"
    s = act_status("32014R1377", "2014/0332(CNS)", "CNS")
    assert s.stage == "no_longer_in_force" and s.since == "2014-01-01"
    assert "a date earlier than the act itself, which is dated 18 December 2014" in s.explanation
    assert "EUR-Lex gives 31 December 2013 as the end of its validity" in s.explanation
    assert "implicitly repealed by Council Regulation (EU, Euratom) No 609/2014, with effect from 1 January 2014" in (
        s.explanation
    )
    assert "recast" not in s.explanation and "its validity ended on" not in s.explanation
    assert s.application.after_end_of_validity == []  # every date of the act is later than such an end


def test_application_date_after_the_end_of_validity_is_marked():
    # Regulation (EU) 2024/2822 (designs): validity ended 2026-06-30 (repealed by the codification 2026/715);
    # EUR-Lex still records 2026-07-01 as a date from which some provisions apply
    s = act_status("32024R2822", "2022/0391(COD)")
    assert s.stage == "no_longer_in_force"
    # its last day of validity is 30 June 2026: no longer in force from 1 July 2026, still in force on 30 June
    assert s.since == "2026-07-01" and "its validity ended on 30 June 2026" in s.explanation
    on_30_june = VALIDITY["32024R2822"].model_copy(update={"in_force": True})  # EUR-Lex's flag as it was that day
    last_day = classify(_bare_proc("2022/0391(COD)", "COD", ["32024R2822"]), [on_30_june], [], date(2026, 6, 30),
                        others=VALIDITY)  # fmt: skip
    assert last_day.stage == "in_force" and "its validity ends on 30 June 2026" in last_day.explanation
    assert s.application.after_end_of_validity == ["2026-07-01"]
    assert "Regulation (EU) 2026/715 is a codification" in s.explanation


def test_in_force_act_states_its_recorded_end_and_repeal():
    # Directive (EU) 2015/849 (AMLD4): in force, end of validity 2027-07-09, repealed by Directive (EU) 2024/1640
    s = act_status("32015L0849", "2013/0025(COD)")
    assert s.stage == "in_force"
    assert "EUR-Lex records that its validity ends on 9 July 2027 and that Directive (EU) 2024/1640 repeals it." in (
        s.explanation
    )
    assert [r.celex for r in s.named_acts] == ["32024L1640"]


def test_commission_implementing_act_is_not_a_final_act_of_the_procedure():
    # EPBD 2021/0426(COD): OEIL listed Commission Implementing Regulation (EU) 2025/1328 as a "Corrigendum to
    # final act"; the procedure's act is Directive (EU) 2024/1275, which must be transposed (Art. 35)
    from pipeline.analysis.status import relevant_acts

    p = _bare_proc("2021/0426(COD)", "COD", ["32024L1275", "32025R1328"])
    acts = [VALIDITY["32024L1275"], VALIDITY["32025R1328"]]
    assert [a.celex for a in relevant_acts(p, acts, [], TODAY_V)] == ["32024L1275"]
    s = classify(p, acts, [], TODAY_V)
    assert s.stage == "in_force" and s.since == "2024-05-28"
    assert "transpos" in s.next_step.text and "regulation applies directly" not in s.next_step.text


# ============================================================ real snapshot records (tests/fixtures/procedure_records.json)
RECORDS = json.loads((Path(__file__).parent / "fixtures" / "procedure_records.json").read_text(encoding="utf-8"))


def rec(pid: str) -> Procedure:
    return Procedure.model_validate(next(p for p in RECORDS["procedures"] if p["id"] == pid))


def rec_act(celex: str) -> LegalAct:
    return LegalAct.model_validate(next(a for a in RECORDS["acts"] if a["celex"] == celex))


def test_adoption_after_a_withdrawal_notice_outranks_it():
    # 2010/0095(COD): Cellar WDW_byCOM of 7 March 2015, then the Council adopted Directive (EU) 2015/1535 on
    # 13 July 2015 (signed 9 September, published 17 September 2015; in force)
    p = _with_events(rec("2010-0095"), _event("withdrawal", "2015-03-07", "cellar:WDW_byCOM",
                                              "Commission withdrew the proposal", "Commission"))  # fmt: skip
    s = classify(p, [rec_act("32015L1535")], [], TODAY)
    assert s.stage == "in_force" and "withdr" not in s.explanation
    assert classify(p, [], [], TODAY).stage != "withdrawn"  # the recorded adoption steps alone outrank it
    assert classify(p, [], [], date(2015, 5, 1)).stage == "withdrawn"  # before the adoption, the notice stands


def test_negotiations_run_from_the_first_trilogue():
    # 2022/0155(COD) (CSA Regulation): mandate confirmed in plenary on 22 November 2023, first trilogue
    # (EP activity INTERINSTITUTIONAL_NEGOTIATION) on 9 December 2025
    s = classify(rec("2022-0155"), [], [], TODAY)
    assert (s.stage, s.label, s.since) == ("negotiations", "Negotiations with the Council", "2025-12-09")


def test_a_committee_decision_to_negotiate_is_not_parliaments_mandate():
    # 2025/0255(COD): only the committee's decision of 19 October 2026 (OEIL "Committee decision to open
    # interinstitutional negotiations with report adopted in committee"; OEIL status "Awaiting committee decision")
    s = classify(rec("2025-0255"), [], [], TODAY)
    assert (s.stage, s.label, s.since) == ("proposed", "Committee decided to negotiate with the Council", "2026-10-19")
    assert "does not hold a mandate yet" in s.explanation and "Rule 72" in s.explanation
    assert s.next_step.text.startswith("The committee's decision is announced in plenary")
    # 2025/0176(COD): announced in plenary on 19 January 2026, confirmed by plenary on 21 January 2026
    p = rec("2025-0176")
    for day in (date(2026, 1, 19), date(2026, 1, 21)):
        s = classify(p, [], [], day)
        assert (s.stage, s.label) == ("negotiations", "Mandate to negotiate with the Council")
    # 2025/0045(COD) (Omnibus I): committee decision 13 Oct 2025, announced 20 Oct, rejected by plenary on 22 Oct
    # (PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS); file referred back for negotiations on 13 Nov 2025
    p = rec("2025-0045")
    s = classify(p, [], [], date(2025, 10, 23))
    assert (s.stage, s.label, s.since) == (
        "proposed", "Parliament rejected the committee's decision to negotiate", "2025-10-22"
    )
    assert "no mandate" in s.explanation and s.next_step.text.startswith("Parliament votes on the committee report")
    s = classify(p, [], [], date(2025, 11, 14))
    assert (s.stage, s.label, s.since) == ("negotiations", "Mandate to negotiate with the Council", "2025-11-13")


def test_consent_file_with_only_the_commission_proposal_waits_for_the_council_draft():
    # 2025/0571(APP), MFF 2028-2034: OEIL lists only COM(2025)0571 ("Preparatory document"); Parliament's consent
    # (Art. 312(2) TFEU) concerns the Council's draft, which is not recorded yet
    s = classify(rec("2025-0571"), [], [], TODAY)
    assert s.stage == "proposed"
    assert "no Council draft submitted to Parliament is recorded" in s.explanation
    assert s.next_step.text.startswith("The Council agrees on its draft") and s.next_step.institution == "Council"
    # 2025/0313(APP): the Council's text 06190/2026 was submitted to Parliament on 21 May 2026
    s = classify(rec("2025-0313"), [], [], date(2026, 6, 1))
    assert s.next_step.text == "Parliament decides whether to give its consent."


def test_consent_given_in_the_linked_vote_is_stated():
    # 2025/0313(APP): vote 197472 of 6 October 2026 (A10-0206/2026, "Draft Council regulation"), decision_outcome
    # ADOPTED 462-121-75; T10-0324/2026: Parliament "Gives its consent to the draft Council regulation"
    from pipeline.models.entities import EpVote

    p = rec("2025-0313")
    vote = EpVote.model_validate(next(v for v in RECORDS["ep_votes"] if v["id"] == "197472"))
    assert (vote.kind, vote.outcome, vote.outcome_basis) == ("final", "adopted", "published")
    s = classify(p, [], [], TODAY, votes=[vote])
    assert (s.stage, s.label, s.since, s.basis) == ("parliament_position", "Parliament gave its consent", "2026-10-06",
                                                    "source")  # fmt: skip
    assert "gave its consent on 6 October 2026" in s.explanation and "only if" not in s.explanation
    assert s.next_step.text == "The Council decides whether to adopt the act." and s.next_step.institution == "Council"
    # without the vote, or with an outcome only derived from the counts, the decision stays unqualified
    assert classify(p, [], [], TODAY).label == "Parliament voted on consent"
    derived = vote.model_copy(update={"outcome_basis": "derived"})
    assert classify(p, [], [], TODAY, votes=[derived]).label == "Parliament voted on consent"
    refused = vote.model_copy(update={"outcome": "rejected"})
    assert classify(p, [], [], TODAY, votes=[refused]).stage == "rejected"


def test_council_decision_reported_by_the_train_is_not_presented_as_pending():
    # 2025/0806(CNS): Parliament's opinion of 26 November 2025; the Legislative Train reports "Adopted / Completed"
    # (20 September 2026). Council Regulation (EU) 2026/415 cites "the Opinion of the European Parliament" of that day,
    # but no official record (Cellar dossier, OEIL, Council document ST 16026/25) ties it to the procedure: not linked
    from pipeline.models.entities import SourceRef

    url = ("https://www.europarl.europa.eu/legislative-train/theme-a-new-plan-for-europe-s-sustainable-prosperity-and-"
           "competitiveness/file-collection-of-statistical-information-by-the-european-central-bank")  # fmt: skip
    tf = TrainFile(
        title="Collection of statistical information by the European Central Bank", status="Adopted / Completed",
        last_updated="2026-09-20", procedure_refs=["2025/0806(CNS)"], url=url,
        source=SourceRef(institution="LegislativeTrain", url=url, retrieved_at="2026-10-22T17:52:59Z"),
    )  # fmt: skip
    p = rec("2025-0806")
    s = classify(p, [], [tf], TODAY)
    assert (s.stage, s.label, s.since) == ("parliament_position", "Parliament gave its opinion", "2025-11-26")
    # what the official records say, precisely: OEIL's stage and no final act, none recorded by EUR-Lex either
    assert s.explanation == (
        "Parliament has delivered its opinion. Under the consultation procedure the Council takes the final decision; "
        "the official sources in our data do not record it. The Legislative Observatory gives the file's stage as "
        "“Awaiting final decision” and lists no final act, and no act in our EUR-Lex data is recorded as adopted under "
        "this procedure. The EP Legislative Train reports this file as “Adopted / Completed” (information updated as "
        "of 20 September 2026)."
    )
    assert s.next_step.basis == "unknown"
    # without the Train's report the decision is still to come
    assert "do not record it" not in classify(p, [], [], TODAY).explanation


def test_act_adopted_by_parliament_with_the_councils_consent():
    # Statute for Members (Art. 223(2) TFEU), no step recorded yet: Parliament adopts, the Council consents
    s = classify(rec("2026-0900"), [], [], TODAY)
    assert "Article 223(2) TFEU" in s.explanation and "Parliament adopts the act itself" in s.explanation
    assert s.next_step.institution == "EP" and "Council then decides whether to give its consent" in s.next_step.text
    # Statute of the Ombudsman (Art. 228(4) TFEU): Council consent 18 June 2021, Parliament's adoption 23 June 2021
    p, act = rec("2019-0900"), rec_act("32021R1163")
    s = classify(p, [act], [], date(2021, 6, 20))
    assert (s.stage, s.label, s.since) == ("parliament_position", "Council gave its consent", "2021-06-18")
    assert s.next_step.text == "Parliament adopts the act."
    s = classify(p, [act], [], date(2021, 7, 1))
    assert (s.stage, s.label, s.since) == ("adopted", "Adopted by Parliament", "2021-06-23")
    # detected from the act's title ("Regulation (EU, Euratom) 2021/1163 of the European Parliament of 24 June 2021")
    assert parliament_adopts(p.model_copy(update={"id": "2099-0900"}), [act])
    assert not parliament_adopts(p.model_copy(update={"id": "2099-0900"}), [rec_act("32019L2121")])


def test_council_act_never_recorded_as_published_has_no_pending_publication_step():
    # 2016/0810(CNS) (Georgia-Europol): OEIL "Procedure completed, awaiting publication in Official Journal" and
    # Council adoption of 23 January 2017; no publication recorded nine years later
    s = classify(rec("2016-0810"), [], [], TODAY)
    assert (s.stage, s.label) == ("adopted", "Adopted by the Council")
    assert "only after publication" not in s.explanation and "No publication" in s.explanation
    assert s.next_step.basis == "unknown" and "since 23 January 2017" in s.next_step.text
    assert classify(rec("2016-0810"), [], [], date(2017, 2, 1)).next_step.text.startswith("Publication")
    # before that: never "applicable law only after publication", as a Council act can enter into force on its
    # adoption (Council Decision 2014/161/EU: 11 March 2014, published 25 March 2014) or take effect on notification
    early = classify(rec("2016-0810"), [], [], date(2017, 2, 1)).explanation
    assert "applicable law" not in early and "only after publication" not in early
    assert "which can be the day of its adoption" in early and early.endswith("(Article 297 TFEU).")


def test_procedure_completed_without_any_recorded_act_is_not_called_adopted():
    # 2021/0415(CNS): OEIL "Procedure completed", only the Commission proposal recorded (it ended as Council
    # Recommendation (EU) 2022/915, which our data does not link)
    s = classify(rec("2021-0415"), [], [], TODAY)
    assert (s.stage, s.label, s.basis) == ("unknown", "Procedure completed", "source")
    assert s.next_step.basis == "unknown" and s.stall is None
