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
