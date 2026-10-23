"""Opt-outs recorded in a directive's recitals (pipeline/sources/optouts.py); recital texts verbatim."""

from __future__ import annotations

import json

import pytest

from pipeline.http import HttpError
from pipeline.models.entities import DirectiveOptOut, SourceStatus
from pipeline.snapshot import read_records
from pipeline.sources.optouts import fetch, not_bound, plain_text

# Directive (EU) 2021/1883 (EU Blue Card), recitals 69 and 70
BLUE_CARD = (
    "(69) In accordance with Articles 1 and 2 of Protocol No 22 on the position of Denmark, annexed to the TEU and to "
    "the TFEU, Denmark is not taking part in the adoption of this Directive and is not bound by it or subject to its "
    "application. (70) In accordance with Articles 1 and 2 and Article 4a(1) of Protocol No 21 on the position of the "
    "United Kingdom and Ireland in respect of the Area of Freedom, Security and Justice, annexed to the TEU and to the "
    "TFEU, and without prejudice to Article 4 of that Protocol, Ireland is not taking part in the adoption of this "
    "Directive and is not bound by it or subject to its application."
)
# Directive (EU) 2016/343 (presumption of innocence), recital 50
THOSE_MEMBER_STATES = (
    "(50) In accordance with Articles 1 and 2 of Protocol No 21 on the position of the United Kingdom and Ireland in "
    "respect of the Area of Freedom, Security and Justice, annexed to the TEU and to the TFEU and without prejudice to "
    "Article 4 of that Protocol, those Member States are not taking part in the adoption of this Directive and are "
    "not bound by it or subject to its application."
)
# an opt-in: Ireland bound
OPT_IN = (
    "In accordance with Article 3 of Protocol No 21 ..., Ireland has notified its wish to take part in the adoption "
    "and application of this Directive."
)


def test_both_countries_not_bound():
    countries, quotes = not_bound(BLUE_CARD)
    assert countries == ["DK", "IE"]
    assert quotes[0].startswith("(69) In accordance") and quotes[1].startswith("(70) In accordance")


def test_those_member_states_refers_back_to_the_protocol():
    assert not_bound(THOSE_MEMBER_STATES)[0] == ["IE"]


def test_opt_in_and_other_directives_are_not_opt_outs():
    assert not_bound(OPT_IN) == ([], [])
    assert not_bound("Member States shall bring into force the laws ... necessary to comply with this Directive.") == ([], [])


def test_plain_text():
    body = "<p>Ireland is <i>not</i>&#160;taking part</p><script>x()</script><p>it’s</p>".encode()
    assert plain_text(body) == " Ireland is not taking part it's "


# Directive 2014/57/EU (criminal sanctions for market abuse), recital 31
THEREFORE = (
    "(31) In accordance with Articles 1 and 2 of Protocol No 22 on the position of Denmark annexed to the TEU and to "
    "the TFEU, Denmark is not taking part in the adoption of this Directive and is therefore not bound by it or "
    "subject to its application."
)
# Directive 2014/66/EU (intra-corporate transferees), recital 47
BY_OR_SUBJECT = (
    "(47) In accordance with Articles 1 and 2 of Protocol No 21 on the position of the United Kingdom and Ireland in "
    "respect of the area of freedom, security and justice, annexed to the TEU and to the TFEU, and without prejudice "
    "to Article 4 of that Protocol, those Member States are not taking part in the adoption of this Directive, and are "
    "not bound by or subject to its application."
)


def test_other_standard_wordings():
    assert not_bound(THEREFORE)[0] == ["DK"]
    assert not_bound(BY_OR_SUBJECT)[0] == ["IE"]


def test_opt_ins_after_adoption():
    from pipeline.sources.optouts import opt_ins

    rows = [
        {"celex": "32024D2087", "title": "Commission Decision (EU) 2024/2087 of 31\xa0July 2024 confirming the "
         "participation of Ireland in Directive (EU)\xa02024/1346 of the European Parliament and of the Council laying "
         "down standards for the reception of applicants for international protection"},
        {"celex": "32018D0753", "title": "Commission Decision (EU) 2018/753 of 22 May 2018 confirming the "
         "participation of Ireland in Directive 2013/33/EU of the European Parliament and of the Council"},
        # a regulation, and enhanced cooperation: not a directive opt-in
        {"celex": "32024D2088", "title": "Commission Decision (EU) 2024/2088 of 31 July 2024 confirming the "
         "participation of Ireland in Regulation (EU) 2024/1351 of the European Parliament and the Council"},
        {"celex": "32024D0807", "title": "Commission Decision (EU) 2024/807 of 29 February 2024 confirming the "
         "participation of Poland in the enhanced cooperation on the establishment of the European Public "
         "Prosecutor’s Office"},
    ]  # fmt: skip
    assert opt_ins(rows) == {"32024L1346": {"IE": "32024D2087"}, "32013L0033": {"IE": "32018D0753"}}


# ---------------------------------------------------------------- fetch: an incomplete opt-in answer
# Ireland opted into these two directives after adoption (Protocol No 21, Article 4)
OPTED_IN = {"32024L1346": {"IE": "32024D2087"}, "32023L2843": {"IE": "32024D0788"}}
# rows of Cellar's answer to opt_ins_query() on 2026-10-23 (30 rows in all); with a server-side time limit the
# same query answered HTTP 200 with the first row only
REG = {"celex": "32017D1518", "title": "Commission Decision (EU) 2017/1518 of 31 August 2017 confirming the "
       "participation of Ireland in Regulation (EU) 2017/353 of the European Parliament and of the Council replacing "
       "Annexes A and B to Regulation (EU) 2015/848 on insolvency proceedings"}  # fmt: skip
D0788 = {"celex": "32024D0788", "title": "Commission Decision (EU) 2024/788 of 6\xa0March 2024 on confirming the "
         "participation of Ireland in Directive (EU)\xa02023/2843 of the European Parliament and of the Council "
         "amending Directives\xa02011/99/EU and\xa02014/41/EU ..."}  # fmt: skip
D2087 = {"celex": "32024D2087", "title": "Commission Decision (EU) 2024/2087 of 31\xa0July 2024 confirming the "
         "participation of Ireland in Directive (EU)\xa02024/1346 of the European Parliament and of the Council "
         "laying down standards for the reception of applicants for international protection"}  # fmt: skip


class Cellar:
    """The opt-in SPARQL query only: the directives' texts were all read in earlier runs."""

    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows, error

    def sparql(self, query, use_cache=True):
        if self.error:
            raise self.error
        return self.rows

    def get(self, *args, **kw):
        raise AssertionError("no directive text is due")


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """The two directives' records from data/snapshot (eurlex acts and optouts) and a previous manifest entry."""
    import pipeline.snapshot as snap

    real = snap.SNAPSHOT
    monkeypatch.setattr(snap, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    for source, name in (("eurlex", "acts"), ("optouts", "directives")):
        recs = [r for r in json.loads((real / source / f"{name}.json").read_text(encoding="utf-8"))
                if r["celex"] in OPTED_IN]  # fmt: skip
        assert len(recs) == 2
        (tmp_path / source).mkdir()
        (tmp_path / source / f"{name}.json").write_text(json.dumps(recs), encoding="utf-8")
    snap.update_manifest(SourceStatus(source="optouts", status="ok", fetched_at=PREVIOUS, attempted_at=PREVIOUS))
    return tmp_path


PREVIOUS = "2026-10-23T05:00:21Z"


def opted_in() -> dict[str, dict[str, str]]:
    return {r.celex: r.opted_in for r in read_records("optouts", "directives", DirectiveOptOut)}


def test_a_complete_opt_in_answer(stored):
    status = fetch(Cellar([REG, D0788, D2087]))
    assert status.status == "ok", status.note
    assert opted_in() == OPTED_IN and status.records["not_bound_IE"] == 0


@pytest.mark.parametrize(
    "rows", [[], [REG], [REG, D2087]], ids=["empty", "first-row-only", "one-directive-missing"]
)
def test_a_short_opt_in_answer_keeps_the_recorded_opt_ins(stored, rows):
    """An answer without them (HTTP 200, empty or cut short) used to erase both opt-ins with status "ok", so the
    site said Ireland was not bound by Directives 2024/1346 and 2023/2843 (Commission Decisions 2024/2087 and
    2024/788 confirm its participation)."""
    status = fetch(Cellar(rows))
    assert opted_in() == OPTED_IN and status.records["not_bound_IE"] == 0
    assert status.status == "partial" and "answer lacked" in status.note, status.note
    assert "32023L2843 IE (32024D0788)" in status.note


def test_a_failed_opt_in_query_keeps_them_and_the_last_retrieval_time(stored):
    status = fetch(Cellar(error=HttpError("sparql", 500, "gave up")))
    assert opted_in() == OPTED_IN and status.records["not_bound_IE"] == 0
    assert status.status == "partial" and "the query failed this run" in status.note
    assert status.fetched_at == PREVIOUS  # nothing was retrieved in this run
