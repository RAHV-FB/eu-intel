"""Opt-outs recorded in a directive's recitals (pipeline/sources/optouts.py); recital texts verbatim."""

from __future__ import annotations

from pipeline.sources.optouts import not_bound, plain_text

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
