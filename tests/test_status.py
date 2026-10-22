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

from pipeline.analysis.status import DossierStatus, classify
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
    assert "must transpose the directive into national law by 6 July 2024" in early.next_step.text
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
    assert "not a rejection by Parliament" in s.explanation
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
