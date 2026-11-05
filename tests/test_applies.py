"""What applies when, where (pipeline/analysis/applies.py) and its feeds: one row per act, date and kind, with the
provisions checked against the act's text or the articles EUR-Lex names; no transposition date whose role is not
established and no date after an act's validity; the window from 31 days before the build; which Member States each
act binds, never "all" when some are not bound or not known; Atom feeds of the next 90 days and iCalendar files
(CRLF, folded at 75 octets, TEXT escaped), with ids and timestamps that do not change from one build to the next."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.analysis import applies, ical
from pipeline.build import Builder, build, norm_ref
from pipeline.models.countries import MEMBER_STATES
from pipeline.models.entities import (
    CheckedTransposition,
    CouncilVote,
    DirectiveOptOut,
    LegalAct,
    RegulationOptIn,
    SourceRef,
    TranspositionDate,
)
from pipeline.validate import applies_problems

ATOM = "{http://www.w3.org/2005/Atom}"
SITE = "https://rahv-fb.github.io/eu-intel/"
TODAY = "2026-11-05"
LO = "2026-10-05"  # 31 days before
ALL = sorted(MEMBER_STATES)


def _act(celex: str = "32099R0001", act_type: str = "regulation", title: str = "Regulation (EU) 2099/1 of the "
         "European Parliament and of the Council of 1 March 2026 on testing (Testing Act)", **kw) -> LegalAct:  # fmt: skip
    url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
    src = SourceRef(institution="EUR-Lex", url=url, label=f"EUR-Lex / Cellar – CELEX {celex}", identifier=celex,
                    retrieved_at="2026-11-05T00:00:00Z")  # fmt: skip
    kw.setdefault("date_document", "2026-03-01")
    kw.setdefault("date_publication", "2026-03-10")
    kw.setdefault("procedure_refs", ["2099/0001(COD)"])
    return LegalAct(celex=celex, act_type=act_type, title=title, eurlex_url=url, source=src, **kw)


def _vote(positions: dict[str, str], date: str = "2026-02-20") -> CouncilVote:
    return CouncilVote(id="ST-1-2026", date=date, title="Regulation on testing", procedure_refs=["2099/0001(COD)"],
                       voting_rule="qmv", outcome="adopted", positions=positions,
                       source=SourceRef(institution="Council", retrieved_at="2026-11-05T00:00:00Z",
                                        url="https://data.consilium.europa.eu/doc/document/ST-1-2026-INIT/EN/pdf"))  # fmt: skip


def _stand_in(acts: list[LegalAct], votes: list[CouncilVote] = (), optouts: list[DirectiveOptOut] = (),
              opt_ins: list[RegulationOptIn] = (), checks: dict | None = None, schengen: dict | None = None) -> Builder:  # fmt: skip
    """A Builder holding only what applies.where_of reads, so that its own participation methods run."""
    b = Builder.__new__(Builder)
    b.optouts = {o.celex: o for o in optouts}
    b.act_refs = {a.celex: [norm_ref(r) for r in a.procedure_refs] for a in acts}
    latest: dict[str, CouncilVote] = {}
    for cv in sorted(votes, key=lambda v: v.date):
        for r in cv.procedure_refs:
            latest[norm_ref(r)] = cv
    b.not_participating_by_ref = {ref: ({c for c, p in cv.positions.items() if p == "not_participating"}, cv)
                                  for ref, cv in latest.items()}  # fmt: skip
    b.transposition_checks = checks or {}
    b.denmark_schengen = schengen or {}
    b.s = SimpleNamespace(regulation_opt_ins=list(opt_ins))
    return b


def _positions(**special: str) -> dict[str, str]:
    return {c: special.get(c, "for") for c in ALL}


# ------------------------------------------------------------------------------------------- kinds
def test_an_act_gives_one_row_per_date_and_kind_with_what_applies():
    # a regulation: in force on 1 April, some provisions from 1 June (partial), the act in general from 1 December, a
    # later general date ("further"), and EUR-Lex marks the entry into force as a date from which some provisions apply
    a = _act(entry_into_force="2026-11-10", partial_on_entry_into_force=True,
             other_application_dates=["2026-12-01", "2027-01-01", "2027-06-01"],
             partial_application_dates=["2027-06-01"])  # fmt: skip
    rows = applies.act_rows(a, None, LO)
    got = [(r["date"], r["kind"], r["partial"], r.get("further", False), r["title"]) for r in rows]
    assert got == [
        ("2026-11-10", "entry_into_force", False, False, "Enters into force"),
        ("2026-11-10", "applies", True, False, "Some provisions start to apply"),
        ("2026-12-01", "applies", False, False, "Rules start to apply"),
        ("2027-01-01", "applies", False, True, "Further provisions start to apply"),
        ("2027-06-01", "applies", True, False, "Some provisions start to apply"),
    ]
    # EUR-Lex records the dates only: no provisions, no articles, the act's record as the source, no check
    assert all(r["provisions"] is None and r["articles"] == [] and "checked" not in r for r in rows)
    assert {r["source"]["url"] for r in rows} == {a.eurlex_url}


def test_checked_dates_carry_their_provisions_their_source_and_whether_eurlex_records_them():
    # data/curated/act_dates.yaml replaced Cellar's dates in the build (apply_act_dates): the entry into force corrected,
    # provisions applying from it, a general date and one EUR-Lex does not record, set by an amending act (source 1)
    cur = {"celex": "32099R0001", "entry_into_force": "2026-11-11", "reviewed": "2026-10-23",
           "application": [{"date": "2026-11-11", "partial": True, "provisions": "Articles 1 and 2 (Art. 9(2))"},
                           {"date": "2027-03-01", "partial": False, "provisions": "The Regulation in general (Art. 9(3))"},
                           {"date": "2027-09-01", "partial": True, "provisions": "Article 5 (Art. 9(4), added by Regulation "
                            "(EU) 2099/9)", "source": 1}],
           "sources": [{"label": "Regulation (EU) 2099/1, Article 9", "url": "https://eur-lex.europa.eu/eli/reg/2099/1/oj"},
                       {"label": "Regulation (EU) 2099/9, Article 1", "url": "https://eur-lex.europa.eu/eli/reg/2099/9/oj",
                        "celex": "32099R0009"}]}  # fmt: skip
    a = _act(entry_into_force="2026-11-11", other_application_dates=["2027-03-01", "2027-09-01"],
             partial_application_dates=["2027-09-01"])  # fmt: skip
    eurlex = {"entry_into_force": "2026-11-10", "application": ["2027-03-01"], "partial_on_entry_into_force": False}
    rows = {(r["kind"], r["date"]): r for r in applies.act_rows(a, cur, LO, eurlex)}
    assert set(rows) == {("entry_into_force", "2026-11-11"), ("applies", "2026-11-11"), ("applies", "2027-03-01"),
                         ("applies", "2027-09-01")}  # fmt: skip
    on_eif = rows[("applies", "2026-11-11")]
    assert (on_eif["partial"], on_eif["provisions"]) == (True, "Articles 1 and 2 (Art. 9(2))")
    assert rows[("applies", "2027-03-01")]["title"] == "Rules start to apply"
    # whether EUR-Lex records the date as it stands: not the corrected entry into force, nor the amending act's date
    assert {k: r["checked"] for k, r in rows.items()} == {
        ("entry_into_force", "2026-11-11"): {"reviewed": "2026-10-23", "eurlex": False},
        ("applies", "2026-11-11"): {"reviewed": "2026-10-23", "eurlex": False},
        ("applies", "2027-03-01"): {"reviewed": "2026-10-23", "eurlex": True},
        ("applies", "2027-09-01"): {"reviewed": "2026-10-23", "eurlex": False},
    }
    # the source is the text checked, as the file's timeline cites it: the amending act for the date it set
    assert rows[("applies", "2027-09-01")]["source"] | {} == {
        "institution": "EUR-Lex", "url": "https://eur-lex.europa.eu/eli/reg/2099/9/oj",
        "label": "Regulation (EU) 2099/9, Article 1 (checked 23 October 2026)", "identifier": "32099R0009",
        "retrieved_at": None, "published": None}  # fmt: skip
    assert rows[("applies", "2027-03-01")]["source"]["identifier"] == "32099R0001"


def test_a_directive_gives_its_deadlines_and_national_application_dates_never_another_date():
    # Art. 30(1): transpose by 1 Dec 2026 and apply from 1 June 2027; Art. 30(2): Article 7 by 1 Dec 2027; a date of
    # Art. 31 (another article than the deadline's): "other", whose role the data do not establish
    a = _act("32099L0002", "directive", "Directive (EU) 2099/2 of the European Parliament and of the Council on testing",
             entry_into_force="2026-03-30",
             transposition_deadlines=["2026-12-01", "2027-06-01", "2027-12-01", "2028-01-01"],
             transposition_dates=[TranspositionDate(date="2026-12-01", labels=["ADOPTION"], articles=["30.1"]),
                                  TranspositionDate(date="2027-06-01", labels=["APPLICATION"], articles=["30.1"]),
                                  TranspositionDate(date="2027-12-01", labels=["ADOPTION"], articles=["30.2"]),
                                  TranspositionDate(date="2028-01-01", labels=["APPLICATION"], articles=["31"])])  # fmt: skip
    a = a.model_copy(update={"transposition_checked": CheckedTransposition(
        deadline="2026-12-01", applies_from="2027-06-01", exceptions="Art. 30(3): Malta may transpose by 2027.",
        application_exceptions="Art. 30(1): the measures for Article 16 apply from 2030.")})  # fmt: skip
    rows = applies.act_rows(a, None, LO)
    assert [(r["date"], r["kind"], r["partial"], r["articles"]) for r in rows] == [
        ("2026-12-01", "transposition_deadline", False, ["Art. 30(1)"]),
        ("2027-06-01", "national_application", False, ["Art. 30(1)"]),
        ("2027-12-01", "transposition_deadline", True, ["Art. 30(2)"]),
    ]
    assert [r["title"] for r in rows] == ["Deadline for Member States to transpose the directive",
                                          "Application date for the national measures",
                                          "Transposition deadline for specific provisions"]  # fmt: skip
    assert rows[0]["exceptions"] == "Art. 30(3): Malta may transpose by 2027."
    assert rows[1]["exceptions"] == "Art. 30(1): the measures for Article 16 apply from 2030."
    assert "exceptions" not in rows[2]


# ------------------------------------------------------------------------------------------- exclusions, window
def test_dates_after_the_end_of_validity_and_before_the_window_are_left_out():
    a = _act(entry_into_force="2026-09-01", other_application_dates=["2026-10-05", "2026-12-01", "2027-07-01"],
             end_of_validity="2027-06-30")  # fmt: skip
    # the entry into force is more than 31 days before the build; 1 July 2027 is after the act's validity ended
    assert [(r["date"], r["kind"]) for r in applies.act_rows(a, None, LO)] == [
        ("2026-10-05", "applies"), ("2026-12-01", "applies")]  # fmt: skip
    # an end of validity earlier than the act itself (a retroactive repeal) is not a limit: every date is later
    b = _act(other_application_dates=["2026-12-01"], end_of_validity="2025-12-31")
    assert [r["date"] for r in applies.act_rows(b, None, LO)] == ["2026-12-01"]


def test_rows_start_31_days_before_the_build_sorted_by_date_and_kind():
    reg = _act(entry_into_force="2026-12-01", other_application_dates=["2026-10-04", "2026-10-05", "2026-12-01"])
    b = _stand_in([reg], [_vote(_positions())])
    b.today, b.dossier_ids, b.act_dates, b.eurlex_dates = TODAY, ["2099-0001"], {}, {}
    b.dossier_acts = {"2099-0001": [reg]}
    b.dossier_detail = {"2099-0001": {"title": "Testing Act", "topics": ["tech"], "known_as": {"names": ["TA"]}}}
    data = applies.rows(b)
    assert data["from"] == LO
    assert [(r["date"], r["kind"]) for r in data["rows"]] == [
        ("2026-10-05", "applies"), ("2026-12-01", "entry_into_force"), ("2026-12-01", "applies")]  # fmt: skip
    r = data["rows"][0]
    assert r["id"] == "32099R0001/applies/2026-10-05"
    # the file's title is not repeated among the act's names; the act's own short title is, then the file's names
    assert r["act"] | {} == {"celex": "32099R0001", "label": "Regulation (EU) 2099/1", "type": "regulation",
                             "names": ["TA"], "url": reg.eurlex_url}  # fmt: skip
    assert (r["dossier_id"], r["dossier_title"], r["topics"]) == ("2099-0001", "Testing Act", ["tech"])


# ------------------------------------------------------------------------------------------- where
def test_a_regulation_binds_all_member_states_that_took_part_and_says_why_the_others_are_not_bound():
    reg = _act()
    w = applies.where_of(reg, _stand_in([reg], [_vote(_positions())]))
    assert (w["bound"], w["not_bound"], w["unknown"]) == (ALL, [], [])
    assert applies.where_text(w) == "All 27 Member States."
    # Denmark and Ireland recorded as not taking part; Ireland's participation confirmed later (Protocol No 21, Art. 4)
    later = RegulationOptIn(decision="32026D0100", celex=reg.celex, country="IE",
                            title="Commission Decision (EU) 2026/100 of 4 May 2026 confirming the participation of Ireland")  # fmt: skip
    w = applies.where_of(reg, _stand_in([reg], [_vote(_positions(DK="not_participating", IE="not_participating"))],
                                        opt_ins=[later]))  # fmt: skip
    assert w["bound"] == [c for c in ALL if c != "DK"] and w["unknown"] == []
    assert w["not_bound"] == [{"country": "DK", "reason": "The Council’s voting result of 20 February 2026 records "
                               "Denmark as not taking part.",
                               "url": "https://data.consilium.europa.eu/doc/document/ST-1-2026-INIT/EN/pdf"}]  # fmt: skip
    assert w["opted_in"] == [{"country": "IE", "label": "Commission Decision (EU) 2026/100",
                              "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026D0100"}]  # fmt: skip
    assert applies.where_text(w).startswith("26 Member States, not Denmark. Denmark: The Council’s voting result")


def test_without_a_record_of_their_participation_denmark_and_ireland_are_not_known_never_all():
    reg = _act()
    w = applies.where_of(reg, _stand_in([reg]))  # no Council voting result with positions
    assert (len(w["bound"]), w["unknown"]) == (25, ["DK", "IE"])
    text = applies.where_text(w)
    assert text == "25 Member States. Whether it binds Denmark and Ireland is not known from our data."
    assert "All" not in text and "all" not in text
    # a regulation implementing enhanced cooperation binds only those taking part: with no voting result, none is known
    ec = _act(title="Council Regulation (EU) 2099/3 implementing enhanced cooperation in the area of testing")
    w = applies.where_of(ec, _stand_in([ec]))
    assert (w["bound"], w["unknown"], w["note"]) == ([], ALL, applies.ENHANCED_NOTE)


def test_a_directive_s_recitals_and_its_own_exemptions_say_who_is_not_bound():
    d = _act("32099L0002", "directive", "Directive (EU) 2099/2 on testing")
    oo = DirectiveOptOut(
        celex=d.celex, status="ok", not_bound=["DK", "IE"], schengen_art4=["DK"],
        quotes=["(63) In accordance with Articles 1 and 2 of Protocol No 22 on the position of Denmark, annexed to the "
                "TEU and to the TFEU, Denmark is not taking part in the adoption of this Directive and is not bound by it.",
                "(64) In accordance with Articles 1 and 2 of Protocol No 21 on the position of the United Kingdom and "
                "Ireland in respect of the area of freedom, security and justice, Ireland is not taking part in the "
                "adoption of this Directive and is not bound by it or subject to its application.",
                "Given that this Directive builds upon the Schengen acquis, Denmark shall decide ..."],
        url=d.eurlex_url, source=d.source)  # fmt: skip
    checks = {d.celex: {"exemption": {"provision": "Art. 33(4)", "countries": ["CY", "MT"],
                                      "country_note": "for as long as no rail system is established within its territory"}}}  # fmt: skip
    schengen = {d.celex: {"decision": "implement", "notified": "2026-06-01", "document": "ST 1/26",
                          "url": "https://data.consilium.europa.eu/doc/document/ST-1-2026-INIT/en/pdf"}}  # fmt: skip
    w = applies.where_of(d, _stand_in([d], optouts=[oo], checks=checks, schengen=schengen))
    reasons = {x["country"]: x["reason"] for x in w["not_bound"]}
    assert set(reasons) == {"CY", "DK", "IE", "MT"} and len(w["bound"]) == 23 and w["unknown"] == []
    assert reasons["IE"] == "Under Protocol No 21, Ireland is not taking part in its adoption and is not bound by it (recital 64)."
    assert reasons["DK"].startswith("Under Protocol No 22, Denmark is not taking part in its adoption and is not bound "
                                    "by it (recital 63). Denmark decided to implement it in its national law")  # fmt: skip
    assert reasons["MT"] == ("The directive does not require Malta to transpose it (Art. 33(4): for as long as no rail "
                             "system is established within its territory).")  # fmt: skip
    # recitals not read and no voting result: Denmark and Ireland not known
    w = applies.where_of(d, _stand_in([d]))
    assert w["unknown"] == ["DK", "IE"]


def test_a_decision_binds_its_addressees_which_the_data_do_not_record():
    dec = _act("32099D0004", "decision", "Decision (EU) 2099/4 of the European Parliament and of the Council on testing")
    w = applies.where_of(dec, _stand_in([dec], [_vote(_positions(DK="not_participating"))]))
    assert w["bound"] == [] and [x["country"] for x in w["not_bound"]] == ["DK"] and len(w["unknown"]) == 26
    assert applies.where_text(w).startswith(applies.DECISION_NOTE + " Denmark: The Council’s voting result")
    assert "All 27" not in applies.where_text(w)


# ------------------------------------------------------------------------------------------- iCalendar
def test_ical_text_is_escaped_and_lines_are_folded_at_75_octets_without_splitting_a_character():
    assert ical.text("Art. 5(1); 2027, OJ \\ L\nnext") == "Art. 5(1)\\; 2027\\, OJ \\\\ L\\nnext"
    assert ical.text("a\x07b\r\nc") == "ab\\nc"  # a control character cannot be in a TEXT value
    line = "SUMMARY:" + "Règlement – “écrit” " * 12
    folded = ical.fold(line)
    parts = folded.split("\r\n")
    assert len(parts) > 2 and all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert "".join([parts[0], *(p[1:] for p in parts[1:])]) == line  # unfolding gives the line back
    assert ical.fold("X:short") == "X:short"
    assert (ical.day("2026-12-31"), ical.next_day("2026-12-31"), ical.utc("2026-10-23")) == (
        "20261231", "20270101", "20261023T000000Z")  # fmt: skip


def _unfold(cal: str) -> list[str]:
    return cal.replace("\r\n ", "").split("\r\n")


def _feeds_stand_in(today: str = TODAY) -> tuple[Builder, dict]:
    reg = _act(entry_into_force="2026-11-20", other_application_dates=["2027-02-01", "2027-05-01"],
               partial_application_dates=["2027-02-01"], date_publication="2026-10-31")  # fmt: skip
    dec = _act("32099D0004", "decision", "Decision (EU) 2099/4 on testing, budgets; and \\ other things",
               entry_into_force="2026-12-24", date_publication="2026-03-01", procedure_refs=["2099/0004(COD)"])  # fmt: skip
    b = _stand_in([reg, dec], [_vote(_positions(DK="not_participating"))])
    b.today, b.act_dates, b.eurlex_dates = today, {}, {}
    b.dossier_ids = ["2099-0001", "2099-0004"]
    b.dossier_acts = {"2099-0001": [reg], "2099-0004": [dec]}
    b.act = {a.celex: a for a in (reg, dec)}
    b.dossier_detail = {"2099-0001": {"title": "Testing Act", "topics": ["tech"], "known_as": None},
                        "2099-0004": {"title": "Testing budgets; and other things", "topics": [], "known_as": None}}  # fmt: skip
    b.topic_list = [{"slug": "tech", "label": "Technology & AI"}, {"slug": "health", "label": "Health & Consumers"}]
    return b, applies.rows(b)


def test_calendars_are_crlf_folded_whole_day_events_with_stable_uids():
    b, data = _feeds_stand_in()
    out = applies.build_feeds(b, data, SITE)
    # one Atom feed and one calendar for everything, each topic and each Member State
    assert len(out) == 2 * (1 + len(b.topic_list) + len(MEMBER_STATES))
    cal = out["feeds/applies/all.ics"]
    assert cal.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:") and cal.endswith("END:VCALENDAR\r\n")
    assert "\n" not in cal.replace("\r\n", "")  # every line ends in CRLF
    assert all(len(x.encode("utf-8")) <= 75 for x in cal.split("\r\n"))
    lines = _unfold(cal)
    assert "X-WR-CALNAME:When new rules apply (EU Legislative Intelligence)" in lines
    events = cal.count("BEGIN:VEVENT")
    assert events == len(data["rows"]) == cal.count("END:VEVENT")
    assert "DTSTART;VALUE=DATE:20261224" in lines and "DTEND;VALUE=DATE:20261225" in lines
    # TEXT escaped: the file title's semicolon, comma and backslash
    assert "SUMMARY:Testing budgets\\; and other things: Enters into force" in lines
    uids = [x for x in lines if x.startswith("UID:")]
    assert len(uids) == len(set(uids)) == events
    assert "UID:eu-intel-applies-32099R0001-applies-2027-02-01@rahv-fb.github.io" in uids
    assert "URL:https://rahv-fb.github.io/eu-intel/legislation/2099-0001/" in lines
    # UIDs and DTSTAMPs do not depend on the site's address or on the day of the build
    other = applies.build_feeds(_feeds_stand_in("2026-11-12")[0], data, "https://example.org/laws/")["feeds/applies/all.ics"]
    stamps = lambda c: [x for x in _unfold(c) if x.startswith(("UID:", "DTSTAMP:"))]  # noqa: E731
    assert stamps(other) == stamps(cal)
    assert "DTSTAMP:20261031T000000Z" in lines  # the act's publication
    # a Member State's calendar: the acts that bind it, or of which it is not known (the decision); not Denmark's
    dk = _unfold(out["feeds/applies/countries/DK.ics"])
    assert sum(x == "BEGIN:VEVENT" for x in dk) == 1 and "SUMMARY:Testing budgets\\; and other things: Enters into force" in dk
    assert out["feeds/applies/countries/FR.ics"].count("BEGIN:VEVENT") == events


def test_atom_feeds_list_the_next_90_days_and_an_entry_does_not_change_from_build_to_build():
    b, data = _feeds_stand_in()
    out = applies.build_feeds(b, data, SITE)
    root = ET.fromstring(out["feeds/applies/all.xml"])
    assert root.findtext(f"{ATOM}id") == f"{applies.TAG_BASE}/feeds/applies/all.xml"
    entries = root.findall(f"{ATOM}entry")
    # within 90 days of 5 November 2026: 20 Nov, 24 Dec, 1 Feb; not 1 May 2027
    assert [e.findtext(f"{ATOM}id").rsplit("/", 2)[1:] for e in entries] == [
        ["entry_into_force", "2026-11-20"], ["entry_into_force", "2026-12-24"], ["applies", "2027-02-01"]]  # fmt: skip
    first = entries[0]
    assert first.findtext(f"{ATOM}title") == "Testing Act: Enters into force (20 November 2026)"
    assert first.find(f"{ATOM}link[@rel='alternate']").get("href") == f"{SITE}legislation/2099-0001/"
    assert "Where: 26 Member States, not Denmark." in first.findtext(f"{ATOM}summary")
    # an entry is dated when its date came within 90 days, or when its act was published if later (31 Oct 2026)
    assert first.findtext(f"{ATOM}updated") == "2026-10-31T00:00:00Z"
    assert entries[2].findtext(f"{ATOM}updated") == "2026-11-03T00:00:00Z"  # 1 Feb 2027 less 90 days
    assert root.findtext(f"{ATOM}updated") == "2026-11-03T00:00:00Z"
    # a week later the same entries read the same; 1 May 2027 is not in the next 90 days until 31 January 2027
    later = applies.build_feeds(_feeds_stand_in("2026-11-12")[0], data, SITE)["feeds/applies/all.xml"]
    assert later == out["feeds/applies/all.xml"]
    late = ET.fromstring(applies.build_feeds(_feeds_stand_in("2027-01-31")[0], data, SITE)["feeds/applies/all.xml"])
    assert [e.findtext(f"{ATOM}updated") for e in late.findall(f"{ATOM}entry")][-1] == "2027-01-31T00:00:00Z"
    # the entry ids are tag URIs, the same in the topic feed and on another site address
    tech = ET.fromstring(applies.build_feeds(b, data, "https://example.org/")["feeds/applies/topics/tech.xml"])
    ids = {e.findtext(f"{ATOM}id") for e in tech.findall(f"{ATOM}entry")}
    assert ids and ids <= {e.findtext(f"{ATOM}id") for e in entries}
    # a topic with no dates: a well-formed feed without entries
    empty = ET.fromstring(out["feeds/applies/topics/health.xml"])
    assert empty.findall(f"{ATOM}entry") == [] and empty.findtext(f"{ATOM}updated")


# ------------------------------------------------------------------------------------------- the built output
FIX = Path(__file__).parent / "fixtures" / "build"


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("applies")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    o = base / "public"
    assert build(out=o, snapshot=base / "snapshot", curated=FIX / "curated", state=base / "state", today="2025-01-20") == 0
    return o


def test_the_build_writes_applies_json_its_feeds_and_calendars(out: Path):
    from pipeline.contract import Contract

    data = json.loads((out / "applies.json").read_text(encoding="utf-8"))
    assert Contract.load().check_value(data, "AppliesData") == []
    assert data["from"] == "2024-12-20" and data["rows"]
    assert [r["date"] for r in data["rows"]] == sorted(r["date"] for r in data["rows"])

    def file_of(pid: str) -> dict | None:
        p = out / "dossiers" / f"{pid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    assert applies_problems(data, file_of) == []
    topics = json.loads((out / "topics.json").read_text(encoding="utf-8"))
    for key in ["all", *(f"topics/{t['slug']}" for t in topics), *(f"countries/{c}" for c in MEMBER_STATES)]:
        ET.parse(out / "feeds" / "applies" / f"{key}.xml")
        cal = (out / "feeds" / "applies" / f"{key}.ics").read_bytes()
        assert cal.startswith(b"BEGIN:VCALENDAR\r\n") and b"\n" not in cal.replace(b"\r\n", b""), key


def test_the_validator_reports_a_row_its_file_contradicts():
    file = {"acts": [{"celex": "32099L0002", "act_type": "directive", "entry_into_force": "2026-03-30",
                      "other_application_dates": [], "transposition_deadlines": ["2026-12-01", "2028-01-01"],
                      "end_of_validity": "2027-06-30", "date_document": "2026-03-01"}],
            "application": {"transposition": [{"date": "2026-12-01", "kind": "deadline", "articles": []},
                                              {"date": "2028-01-01", "kind": "other", "articles": []}]}}  # fmt: skip

    def row(kind: str, day: str, **w: list) -> dict:
        where = {"bound": w.get("bound", ALL), "not_bound": w.get("not_bound", []), "unknown": w.get("unknown", [])}
        return {"id": f"32099L0002/{kind}/{day}", "date": day, "kind": kind, "dossier_id": "2099-0002",
                "act": {"celex": "32099L0002"}, "where": where}  # fmt: skip

    good = [row("entry_into_force", "2026-03-30"), row("transposition_deadline", "2026-12-01")]
    assert applies_problems({"from": "2026-01-01", "rows": good}, lambda pid: file) == []
    bad = [row("applies", "2026-12-01"), row("national_application", "2026-12-01"), row("transposition_deadline", "2028-01-01"),
           row("entry_into_force", "2026-03-30", bound=ALL[1:]), row("entry_into_force", "2026-03-30")]  # fmt: skip
    msgs = applies_problems({"from": "2026-04-01", "rows": bad}, lambda pid: file)
    assert any("2026-12-01 is not a date of 32099L0002 of kind applies" in m for m in msgs)
    assert any("gives 2026-12-01 as a transposition date of kind 'deadline'" in m for m in msgs)
    assert any("kind 'other'" in m for m in msgs) and any("after the end of the act's validity" in m for m in msgs)
    assert any("does not list each Member State once" in m for m in msgs) and any("listed twice" in m for m in msgs)
    assert any("before the first day listed" in m for m in msgs)


# ------------------------------------------------------------------------------------------- real records
SNAP = Path(__file__).resolve().parent.parent / "data" / "snapshot"


@pytest.mark.skipif(not (SNAP / "optouts" / "directives.json").exists(), reason="no snapshot")
def test_a_real_directive_names_the_recitals_that_leave_denmark_and_ireland_out():
    # Directive (EU) 2024/1260 (asset recovery and confiscation), recitals 63 and 64
    def record(rel: str, key: str, value: str) -> dict:
        with (SNAP / rel).open(encoding="utf-8") as f:
            for line in f:
                if f'"{key}":"{value}"' in line:
                    return json.loads(line.strip().rstrip(","))
        raise AssertionError(value)

    d = LegalAct.model_validate(record("eurlex/acts.json", "celex", "32024L1260"))
    oo = DirectiveOptOut.model_validate(record("optouts/directives.json", "celex", "32024L1260"))
    w = applies.where_of(d, _stand_in([d], optouts=[oo]))
    assert [(x["country"], re.sub(r"\d+", "N", x["reason"])) for x in w["not_bound"]] == [
        ("DK", "Under Protocol No N, Denmark is not taking part in its adoption and is not bound by it (recital N)."),
        ("IE", "Under Protocol No N, Ireland is not taking part in its adoption and is not bound by it (recital N)."),
    ]
    assert "Protocol No 22" in w["not_bound"][0]["reason"] and "Protocol No 21" in w["not_bound"][1]["reason"]
