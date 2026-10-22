"""Generate the TEST-ONLY build fixture (invented data; ids/urls deliberately fake)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.models import entities as E

OUT = Path(__file__).resolve().parent
T = "2099-01-01T00:00:00Z"


def src(inst, ident):
    return E.SourceRef(
        institution=inst,
        url=f"https://example.invalid/{ident}",
        label=f"TEST ONLY {ident}",
        identifier=ident,
        retrieved_at=T,
    )


def m(oid, kind, start, end, term):
    return E.Membership(org_id=oid, kind=kind, role="MEMBER", start=start, end=end, term=term)


orgs = [
    E.Organization(
        id="G9EPP",
        kind="group",
        code="EPP",
        label="TEST Group EPP (term 9)",
        start="2019-07-02",
        end="2024-07-15",
        source=src("EP", "G9EPP"),
    ),
    E.Organization(
        id="G10EPP",
        kind="group",
        code="EPP",
        label="TEST Group EPP (term 10)",
        start="2024-07-16",
        source=src("EP", "G10EPP"),
    ),
    E.Organization(
        id="G10SD",
        kind="group",
        code="S&D",
        label="TEST Group S&D",
        start="2024-07-16",
        source=src("EP", "G10SD"),
    ),
    E.Organization(
        id="G9GRE",
        kind="group",
        code="Greens/EFA",
        label="TEST Group Greens/EFA",
        start="2019-07-02",
        end="2024-07-15",
        source=src("EP", "G9GRE"),
    ),
    E.Organization(
        id="P1",
        kind="party",
        code="TPA",
        label="Test Party A",
        country="ES",
        start="2019-07-02",
        source=src("EP", "P1"),
    ),
    E.Organization(
        id="P2",
        kind="party",
        code="TPB",
        label="Test Party B",
        country="DE",
        start="2019-07-02",
        source=src("EP", "P2"),
    ),
]
meps = [
    # T1 switches from Greens/EFA (term 9) to S&D (term 10)
    E.Mep(
        id="T1",
        name="Testa Sánchez",
        family_name="Sánchez",
        sort_label="SANCHEZ",
        country="ES",
        active=True,
        terms=[9, 10],
        memberships=[
            m("G9GRE", "group", "2019-07-02", "2024-07-15", 9),
            m("G10SD", "group", "2024-07-16", None, 10),
            m("P1", "party", "2019-07-02", None, 10),
        ],
        official_url="https://example.invalid/meps/T1",
        source=src("EP", "T1"),
    ),
    E.Mep(
        id="T2",
        name="Testo Müller",
        family_name="Müller",
        sort_label="MULLER",
        country="DE",
        active=True,
        terms=[9, 10],
        memberships=[
            m("G9EPP", "group", "2019-07-02", "2024-07-15", 9),
            m("G10EPP", "group", "2024-07-16", None, 10),
            m("P2", "party", "2019-07-02", None, 10),
        ],
        official_url="https://example.invalid/meps/T2",
        source=src("EP", "T2"),
    ),
    E.Mep(
        id="T3",
        name="Testi Former",
        family_name="Former",
        sort_label="FORMER",
        country="DE",
        active=False,
        terms=[9],
        memberships=[
            m("G9EPP", "group", "2019-07-02", "2024-07-15", 9),
            m("P2", "party", "2019-07-02", "2024-07-15", 9),
        ],
        official_url="https://example.invalid/meps/T3",
        source=src("EP", "T3"),
    ),
    E.Mep(
        id="T4",
        name="Testu García",
        family_name="García",
        sort_label="GARCIA",
        country="ES",
        active=True,
        terms=[10],
        memberships=[m("G10EPP", "group", "2024-07-16", None, 10), m("P1", "party", "2024-07-16", None, 10)],
        official_url="https://example.invalid/meps/T4",
        source=src("EP", "T4"),
    ),
]


def ev(pid, i, d, kind, title, docs=()):
    return E.Event(
        id=f"{pid}-ev{i}",
        date=d,
        kind=kind,
        institution="EP",
        title=title,
        docs=[E.DocRef(id=x) for x in docs],
        source=src("EP", f"{pid}-ev{i}"),
    )


procs = [
    E.Procedure(
        id="2099-0001",
        reference="2099/0001(COD)",
        type="COD",
        title="Proposal for a Regulation of the European Parliament and of the Council laying down test rules on widgets (Test Widgets Act)",
        subjects=[E.Subject(code="3.30.06", label="TEST ICT")],
        started="2023-01-10",
        committees=[E.CommitteeRole(code="TEST", name="Test committee")],
        rapporteurs=[E.Rapporteur(mep_id="T2", name="Testo Müller", committee="TEST")],
        events=[
            ev("2099-0001", 1, "2023-01-10", "proposal", "Commission proposal published", ["COM(2099)0001"]),
            ev("2099-0001", 2, "2024-03-01", "committee_report", "Committee report tabled"),
            ev(
                "2099-0001",
                3,
                "2024-04-10",
                "ep_position",
                "Parliament adopts its position",
                ["TA-9-2099-0001"],
            ),
            ev("2099-0001", 4, "2024-11-05", "council_adoption", "Council adopts the act"),
        ],
        com_refs=["COM(2099)0001"],
        oeil_url="https://example.invalid/oeil/2099-0001",
        source=src("EP", "2099-0001"),
    ),
    E.Procedure(
        id="2099-0002",
        reference="2099/0002(CNS)",
        type="CNS",
        title="Proposal for a Council Directive on test procedures for gadgets",
        subjects=[E.Subject(code="7.10", label="TEST migration")],
        started="2020-02-01",
        events=[ev("2099-0002", 1, "2020-02-01", "proposal", "Commission proposal published")],
        oeil_url="https://example.invalid/oeil/2099-0002",
        source=src("EP", "2099-0002"),
    ),
    E.Procedure(
        id="2099-0003",
        reference="2099/0003(COD)",
        type="COD",
        title="Proposal for a Directive on test thingamajigs",
        subjects=[E.Subject(code="3.30.25", label="TEST internet")],
        started="2021-05-01",
        events=[
            ev("2099-0003", 1, "2021-05-01", "proposal", "Commission proposal published"),
            ev("2099-0003", 2, "2022-06-01", "ep_position", "Parliament adopts its position"),
        ],
        oeil_url="https://example.invalid/oeil/2099-0003",
        source=src("EP", "2099-0003"),
    ),
]
acts = [
    E.LegalAct(
        celex="32099R0001",
        act_type="regulation",
        title="Regulation (EU) 2099/1 of the European Parliament and of the Council of 20 November 2024 laying down test rules on widgets (Test Widgets Act)",
        date_document="2024-11-20",
        date_signature="2024-11-20",
        date_publication="2024-12-01",
        entry_into_force="2024-12-21",
        other_application_dates=["2025-06-01", "2027-01-01"],
        in_force=True,
        procedure_refs=["2099/0001(COD)"],
        amended_by=["32099R0077"],
        amends=["32099L0003"],
        eurlex_url="https://example.invalid/eurlex/32099R0001",
        source=src("EUR-Lex", "32099R0001"),
    ),
    E.LegalAct(
        celex="32099L0003",
        act_type="directive",
        title="Directive (EU) 2099/3 on test thingamajigs",
        date_document="2023-01-15",
        date_signature="2023-01-15",
        date_publication="2023-02-01",
        entry_into_force="2023-02-21",
        transposition_deadlines=["2025-02-21"],
        in_force=True,
        procedure_refs=["2099/0003(COD)"],
        eurlex_url="https://example.invalid/eurlex/32099L0003",
        source=src("EUR-Lex", "32099L0003"),
    ),
    # act whose procedure is not in procedures.json -> EUR-Lex-only dossier
    E.LegalAct(
        celex="32099L0009",
        act_type="directive",
        title="Directive (EU) 2099/9 of the European Parliament and of the Council of 1 March 2025 on test doohickeys",
        date_document="2025-03-01",
        date_publication="2025-03-10",
        entry_into_force="2025-03-30",
        transposition_deadlines=["2027-03-30"],
        in_force=True,
        procedure_refs=["2099/0009(COD)"],
        eurlex_url="https://example.invalid/eurlex/32099L0009",
        source=src("EUR-Lex", "32099L0009"),
    ),
]
votes = [
    E.EpVote(
        id="V1",
        event_id="TEST-DEC-V1",
        date="2024-04-10",
        term=9,
        title="TEST legislative resolution",
        kind="final",
        outcome="adopted",
        n_for=2,
        n_against=1,
        n_abstain=0,
        majority_rule="votes_cast",
        has_ballots=True,
        procedure_refs=["2099/0001(COD)"],
        doc_ids=["TA-9-2099-0001"],
        source=src("EP", "V1"),
    ),
    E.EpVote(
        id="V2",
        event_id="TEST-DEC-V2",
        date="2024-04-10",
        term=9,
        title="TEST amendment 12",
        kind="amendment",
        outcome="rejected",
        n_for=1,
        n_against=2,
        n_abstain=0,
        has_ballots=True,
        procedure_refs=["2099/0001(COD)"],
        source=src("EP", "V2"),
    ),
    E.EpVote(
        id="V3",
        event_id="TEST-DEC-V3",
        date="2025-01-15",
        term=10,
        title="TEST motion for a resolution",
        kind="resolution",
        outcome="rejected",
        n_for=1,
        n_against=2,
        n_abstain=1,
        has_ballots=True,
        source=src("EP", "V3"),
    ),
    # outcome not recorded by the source: no margin may be shown (regression for a known defect)
    E.EpVote(
        id="V4",
        event_id="TEST-DEC-V4",
        date="2022-06-01",
        term=9,
        title="TEST vote with unrecorded outcome",
        kind="final",
        outcome="unknown",
        n_for=300,
        n_against=200,
        n_abstain=10,
        majority_rule="votes_cast",
        procedure_refs=["2099/0003(COD)"],
        source=src("EP", "V4"),
    ),
]
ballots = [
    E.EpBallots(vote_id="V1", favor=["T1", "T2"], against=["T3"]),
    E.EpBallots(vote_id="V2", favor=["T1"], against=["T2", "T3"]),
    # official totals 1/2/1 but only 1/2/0 recorded individually -> reconciliation mismatch
    E.EpBallots(vote_id="V3", favor=["T1"], against=["T2", "T4"], intended_favor=["T4"]),
]
council = [
    E.CouncilVote(
        id="C1",
        date="2024-11-05",
        title="TEST Regulation on widgets",
        procedure_refs=["2099/0001(COD)"],
        voting_rule="qmv",
        stage="TEST adoption of the legislative act",
        written_procedure=False,
        outcome="adopted",
        positions={
            c: ("against" if c == "HU" else "abstain" if c == "PL" else "for")
            for c in "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
        },
        source=src("Council", "C1"),
    ),
]
measures = [
    E.NationalMeasure(
        id="M1",
        directive_celex="32099L0003",
        country="ES",
        title="TEST Ley de prueba",
        date="2025-01-01",
        source=src("EUR-Lex", "M1"),
    ),
    E.NationalMeasure(
        id="M2",
        directive_celex="32099L0003",
        country="DE",
        title="TEST Gesetz",
        date="2025-02-01",
        source=src("EUR-Lex", "M2"),
    ),
]
coverage = [
    E.ImplementationCoverage(celex="32099L0003", measures=2, source=src("EUR-Lex", "cov-32099L0003")),
    E.ImplementationCoverage(celex="32099L0009", measures=0, source=src("EUR-Lex", "cov-32099L0009")),
]
infr = [
    E.InfringementCase(
        id="INFR(2099)0001",
        country="FR",
        title="TEST failure to notify",
        celex=None,
        legal_basis=["32099L0003"],
        non_communication=True,
        latest_stage="Letter of formal notice",
        latest_decision_date="2025-04-01",
        status="open",
        source=src("Commission", "INFR(2099)0001"),
    )
]
train = [
    E.TrainFile(
        url="https://example.invalid/train/gadgets",
        title="TEST gadgets",
        status="Blocked in Council",
        procedure_refs=["2099/0002(CNS)"],
        source=src("LegislativeTrain", "train-gadgets"),
    )
]


def write(source, name, recs):
    p = OUT / "snapshot" / source / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "[\n"
        + ",\n".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for r in recs)
        + "\n]\n"
    )


write("ep_people", "meps", meps)
write("ep_people", "orgs", orgs)
write("ep_procedures", "procedures", procs)
write("ep_votes", "votes", votes)
write("ep_votes", "ballots", ballots)
write("eurlex", "acts", acts)
write("council", "votes", council)
write("implementation", "measures", measures)
write("implementation", "coverage", coverage)
write("implementation", "infringements", infr)
write("train", "files", train)
man = {
    s: E.SourceStatus(source=s, status="ok", fetched_at=T, attempted_at=T, records={"test": 1}).model_dump(
        mode="json"
    )
    for s in ["ep_people", "ep_procedures", "ep_votes", "eurlex", "council", "implementation", "train"]
}
(OUT / "snapshot" / "_manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
cur = OUT / "curated"
cur.mkdir(parents=True, exist_ok=True)
(cur / "featured.yaml").write_text("""# TEST ONLY curated fixture (invented)
- id: "2099-0001"
  reference: "2099/0001(COD)"
  celex: ["32099R0001"]
  short_title: "Test Widgets Act"
  what: "TEST ONLY: sets invented rules on widgets."
  why: "TEST ONLY: used by tests/test_build.py."
  aliases: ["TWA", "widget law"]
  topics: ["tech"]
  featured: true
  feature_order: 1
  sources:
    - {label: "TEST source", url: "https://example.invalid/source"}
  reviewed: "2099-01-01"
""")
(cur / "topics.yaml").write_text("""# TEST ONLY topics fixture
- slug: tech
  label: "Technology & AI"
  description: "TEST tech topic"
  ep_subjects: ["3.30"]
  search_aliases: ["digital"]
- slug: migration
  label: "Migration"
  description: "TEST migration topic"
  ep_subjects: ["7.10"]
  search_aliases: ["asylum"]
""")
(cur / "aliases.yaml").write_text("""# TEST ONLY alias rules
- {terms: ["gizmo"], expands_to: ["test thingamajigs"]}
""")
(OUT / "README.txt").write_text(
    "TEST-ONLY fixture: invented records (fake ids such as 2099/0001(COD), CELEX 32099R0001, MEP T1,\n"
    "URLs on example.invalid). Used by tests/test_build.py, test_validate.py, test_activity.py.\n"
    "Regenerate with: .venv/bin/python tests/fixtures/build/make_fixture.py\n"
)
print("ok")
