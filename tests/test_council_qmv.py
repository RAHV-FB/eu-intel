"""Unit tests of Council voting-rule arithmetic (constructed position sets) plus real recorded votes."""

from __future__ import annotations

import pytest

from pipeline.analysis.council_qmv import (
    EU27,
    POPULATION_TABLES,
    PUBLISHED_TOTALS,
    assess,
    population_table,
)

LEFT = ["BE", "BG", "CZ", "DK", "DE", "EE", "IE", "GR", "ES", "FR", "HR", "IT", "CY", "LV"]
RIGHT = ["LT", "LU", "HU", "MT", "NL", "AT", "PL", "PT", "RO", "SI", "SK", "FI", "SE"]
CODE = {"Y": "for", "N": "against", "A": "abstain", ".": "not_participating"}


def sheet(left: str, right: str, uk: str | None = None) -> dict[str, str]:
    """Positions in the protocol order of the Council voting sheet (Y/N/A/. per state)."""
    pos = {c: CODE[s] for c, s in zip(LEFT + RIGHT, left + right, strict=True)}
    if uk is not None:
        pos["GB"] = CODE[uk]
    return pos


def by_population(year: int) -> list[str]:
    t = population_table(year, EU27)
    assert t is not None
    return sorted(t.population, key=lambda c: -t.population[c])


def all_(pos: str) -> dict[str, str]:
    return dict.fromkeys(EU27, pos)


# ------------------------------------------------------------------ population data
def test_population_tables_match_published_totals():
    for t in POPULATION_TABLES:
        assert t.total == PUBLISHED_TOTALS[(t.celex, len(t.population))], t.label
        assert all(v > 0 for v in t.population.values())


def test_population_table_selection():
    assert population_table(2024, EU27).celex == "32023D2827"
    assert population_table(2025, EU27).celex == "32024D3231"
    assert population_table(2026, EU27).celex == "32025D2427"
    eu28 = set(EU27) | {"GB"}
    assert population_table(2020, eu28).valid_to == "2020-01-31"
    assert population_table(2020, EU27).valid_from == "2020-02-01"
    assert population_table(2019, eu28).celex == "32018D2076"
    assert population_table(2019, EU27) is None  # the 2019 EU-27 table never applied
    assert population_table(2018, EU27) is None
    assert population_table(2027, EU27) is None


# ------------------------------------------------------------------ QMV (TEU 16(4))
def test_qmv_all_for():
    a = assess(all_("for"), "qmv", year=2026)
    assert a.adopted_by_rule is True
    assert (a.states_for, a.states_required, a.population_for_pct) == (27, 15, 100.0)
    assert a.legal_basis == "TEU Art. 16(4)"
    assert a.single_state_veto_possible is False
    # Withholding by DE, FR, IT drops below 65 % but 3 states are not a blocking minority (min 4):
    # the 4th largest (ES) is needed.
    assert a.states_needed_to_block == 4


def test_qmv_abstentions_count_as_not_supporting():
    pos = all_("for")
    for c in by_population(2024)[:4]:  # DE, FR, IT, ES abstain
        pos[c] = "abstain"
    a = assess(pos, "qmv", year=2024)
    assert a.states_for == 23 and a.states_abstain == 4
    assert a.population_for_pct < 65
    assert a.adopted_by_rule is False and a.blocking_minority_formed is True


def test_qmv_blocking_minority_needs_four_states_deemed_attained():
    pos = all_("for")
    for c in by_population(2026)[:3]:  # DE, FR, IT (> 35 % of the population) vote against
        pos[c] = "against"
    a = assess(pos, "qmv", year=2026)
    assert a.population_for_pct < 65
    assert a.deemed_attained is True
    assert a.adopted_by_rule is True
    assert a.blocking_minority_formed is False


def test_qmv_states_threshold_15_of_27():
    largest = by_population(2026)
    pos = all_("against")
    for c in largest[:14]:
        pos[c] = "for"
    a = assess(pos, "qmv", year=2026)
    assert a.population_for_pct > 65  # population criterion met ...
    assert a.adopted_by_rule is False  # ... but only 14 of the required 15 states
    assert a.margin_states == -1
    pos[largest[14]] = "for"
    assert assess(pos, "qmv", year=2026).adopted_by_rule is True


def test_qmv_population_threshold():
    smallest = list(reversed(by_population(2026)))
    pos = all_("abstain")
    for c in smallest[:22]:
        pos[c] = "for"
    a = assess(pos, "qmv", year=2026)
    assert a.states_for == 22 and a.population_for_pct < 65
    assert a.adopted_by_rule is False and a.blocking_minority_formed is True


def test_qmv_not_on_commission_proposal_72_percent():
    largest = by_population(2025)
    pos = all_("against")
    for c in largest[:19]:
        pos[c] = "for"
    a = assess(pos, "qmv", on_commission_proposal=False, year=2025)
    assert a.legal_basis == "TFEU Art. 238(2)"
    assert a.states_required == 20 and a.adopted_by_rule is False
    assert a.blocking_minority_min_states is None
    pos[largest[19]] = "for"
    assert assess(pos, "qmv", on_commission_proposal=False, year=2025).adopted_by_rule is True
    # The same 19 would pass on a Commission proposal (55 %).
    pos[largest[19]] = "against"
    assert assess(pos, "qmv", year=2025).adopted_by_rule is True


def test_qmv_eu28_requires_16_states():
    pos = sheet("YYYYAYYYYYYYYY", "YYYYYYYYYYYYY", uk="Y")
    a = assess(pos, "qmv", year=2019)
    assert a.members == 28 and a.states_required == 16
    # Official sheet ST 9584/19 (22 May 2019): Germany abstained; 83,88 % of the population in favour.
    assert a.population_for_pct == 83.88
    assert a.population_source_celex == "32018D2076"


def test_qmv_decided_by_population_hand_computed():
    # 2026 figures (Council Decision (EU, Euratom) 2025/2427): EU 452,162,974; 65 % = 293,905,933.1.
    # Germany 83,502,300 + Spain 49,093,546 + Netherlands 18,191,086 = 150,786,932.
    # With Bulgaria (6,437,360) against: 157,224,292 against, 294,938,682 for = 65.23 % -> adopted.
    # With Austria (9,180,000) instead: 159,966,932 against, 292,196,042 for = 64.62 % -> not adopted, although
    # 23 of the 15 Member States needed are in favour and 4 (the minimum of a blocking minority) are against.
    pos = dict(all_("for"), DE="against", ES="against", NL="against", BG="against")
    a = assess(pos, "qmv", year=2026)
    assert (a.states_for, a.states_required, a.population_for, a.population_participating) == (
        23, 15, 294_938_682, 452_162_974,
    )  # fmt: skip
    assert (a.population_for_pct, a.adopted_by_rule, a.blocking_minority_formed) == (65.23, True, False)
    pos["BG"], pos["AT"] = "for", "against"
    a = assess(pos, "qmv", year=2026)
    assert (a.states_for, a.population_for, a.population_for_pct) == (23, 292_196_042, 64.62)
    assert (a.adopted_by_rule, a.blocking_minority_formed, a.deemed_attained) == (False, True, False)
    assert a.margin_states == 8 and a.margin_population_pct == -0.38


def test_qmv_four_state_blocking_minority_edge_hand_computed():
    # Germany 83,502,300 + France 68,635,943 + Italy 59,635,202 = 211,773,445 against (46.84 % > 35 %): 240,389,529
    # for (53.16 %). Three Member States are not a blocking minority (TEU Art. 16(4)): QM deemed attained. Malta
    # (574,250) joining them makes four: 239,815,279 for (53.04 %), and the act is not adopted.
    pos = dict(all_("for"), DE="against", FR="against", IT="against")
    a = assess(pos, "qmv", year=2026)
    assert (a.population_for, a.population_for_pct) == (240_389_529, 53.16)
    assert (a.adopted_by_rule, a.deemed_attained, a.blocking_minority_formed) == (True, True, False)
    assert a.states_needed_to_block == 1  # any one of the 24 in favour joining the three makes four
    pos["MT"] = "against"
    a = assess(pos, "qmv", year=2026)
    assert (a.population_for, a.population_for_pct) == (239_815_279, 53.04)
    assert (a.adopted_by_rule, a.deemed_attained, a.blocking_minority_formed) == (False, False, True)
    pos["MT"] = "abstain"  # an abstention counts as not in favour, as a vote against does
    assert assess(pos, "qmv", year=2026).adopted_by_rule is False


def test_population_share_short_of_65_is_never_shown_as_65():
    # 2026: Germany 83,502,300, Greece 10,409,547, Croatia 3,874,350, Hungary 9,539,502, Lithuania 2,890,664, Poland
    # 37,475,594 and Sweden 10,583,000 against: 158,274,957. The 20 in favour: 293,888,017 of 452,162,974 = 64.996 %,
    # 17,916 people short of 65 % (293,905,933.1). Rounded to two decimals that is 65.00, next to "at least 65 % was
    # needed" and "not met"; the share is given as 64.99 instead.
    against = ("DE", "GR", "HR", "HU", "LT", "PL", "SE")
    a = assess(dict(all_("for"), **dict.fromkeys(against, "against")), "qmv", year=2026)
    assert (a.states_for, a.population_for, a.adopted_by_rule) == (20, 293_888_017, False)
    assert (a.population_for_pct, a.margin_population_pct) == (64.99, -0.01)
    # a share at or above 65 % keeps its ordinary rounding (Eurodac, ST 9841/24: the sheet's 85,52 %)
    assert assess(all_("for"), "qmv", year=2026).population_for_pct == 100.0


def test_build_passes_on_a_qualified_majority_deemed_attained():
    # the page must not say that both thresholds were met when the population criterion was not (council_assessment)
    from pipeline.build import _as_dict, council_assessment

    pos = dict(all_("for"), DE="against", FR="against", IT="against")
    a = council_assessment(_as_dict(assess(pos, "qmv", year=2026)))
    assert (a["adopted_by_rule"], a["population_for_pct"], a["deemed_attained"]) == (True, 53.16, True)
    assert council_assessment(_as_dict(assess(all_("for"), "qmv", year=2026)))["deemed_attained"] is False
    assert council_assessment(_as_dict(assess(pos, "unanimity", year=2026)))["deemed_attained"] is False


# ------------------------------------------------------------------ participation (TFEU 238(3))
def test_not_participating_is_not_abstention():
    base = sheet("YYAYYYYYYYYYYY", "YYNYYYNYYYAYY")
    np_ = dict(base, DK="not_participating", IE="not_participating")
    ab = dict(base, DK="abstain", IE="abstain")
    a_np, a_ab = assess(np_, "qmv", year=2024), assess(ab, "qmv", year=2024)
    assert a_np.participating == 25 and a_ab.participating == 27
    assert a_np.states_not_participating == 2 and a_np.states_abstain == 2
    assert a_ab.states_abstain == 4
    assert a_np.legal_basis == "TFEU Art. 238(3)(a)" and a_ab.legal_basis == "TEU Art. 16(4)"
    assert a_np.states_required == 14 and a_ab.states_required == 15
    assert a_np.population_for_pct > a_ab.population_for_pct


def test_real_eurodac_2024_with_opt_outs():
    # ST 9841/24, Eurodac regulation 2016/0132(COD), 14 May 2024: DK and IE not participating,
    # HU and PL against, CZ and SK abstaining. The official sheet shows 85,52 % and "(14 MS)".
    pos = sheet("YYA.YY.YYYYYYY", "YYNYYYNYYYAYY")
    a = assess(pos, "qmv", year=2024)
    assert (a.states_for, a.states_against, a.states_abstain, a.states_not_participating) == (21, 2, 2, 2)
    assert a.states_required == 14
    assert a.population_for_pct == 85.52
    assert a.adopted_by_rule is True
    assert a.blocking_minority_min_states == 4


def test_real_csddd_2024():
    # ST 10263/24, CSDDD 2022/0051(COD), 24 May 2024: 17 yes, 10 abstentions; sheet shows 68,41 %.
    pos = sheet("AAAYAAYYYYYYYY", "AYAAYAYYYYAYY")
    a = assess(pos, "qmv", year=2024)
    assert (a.states_for, a.states_abstain) == (17, 10)
    assert a.population_for_pct == 68.41
    assert a.adopted_by_rule is True
    assert a.states_needed_to_block == 1  # Italy (13.25 %) alone withholding support would have blocked


def test_238_3_a_blocking_minority_size_is_computed():
    pos = all_("for")
    for c in ("DE", "FR"):
        pos[c] = "not_participating"
    a = assess(pos, "qmv", year=2026)
    # Without DE and FR the participating population is ~300.0 M; IT + ES (~108.7 M, 36.2 %) already
    # exceed 35 %, so the blocking minority is "minimum number (2) plus one member" = 3, not TEU's 4.
    assert a.blocking_minority_min_states == 3
    assert a.states_required == 14  # ceil(55 % of 25)
    pos.update(IT="against", ES="against")  # 2 states with >35 %: not enough, QM deemed attained
    a = assess(pos, "qmv", year=2026)
    assert a.population_for_pct < 65 and a.deemed_attained is True and a.adopted_by_rule is True
    pos["PL"] = "abstain"
    assert assess(pos, "qmv", year=2026).adopted_by_rule is False


# ------------------------------------------------------------------ unanimity / simple majority
def test_unanimity_abstention_does_not_prevent_adoption():
    pos = all_("for")
    pos["HU"] = "abstain"
    a = assess(pos, "unanimity", year=2026)
    assert a.adopted_by_rule is True and a.veto_exercised is False
    assert a.single_state_veto_possible is True
    assert a.states_needed_to_block == 1
    assert a.states_required is None and a.population_required_pct is None


def test_unanimity_single_against_is_veto():
    pos = all_("for")
    pos["MT"] = "against"
    a = assess(pos, "unanimity", year=2026)
    assert a.adopted_by_rule is False and a.veto_exercised is True


def test_unanimity_among_participants():
    pos = all_("for")
    pos["DK"] = "not_participating"
    a = assess(pos, "unanimity", year=2026)
    assert a.adopted_by_rule is True and a.participating == 26


def test_only_unanimity_allows_single_state_veto():
    pos = all_("for")
    pos["DE"] = "against"
    assert assess(pos, "qmv", year=2026).adopted_by_rule is True
    assert assess(pos, "qmv", year=2026).single_state_veto_possible is False
    assert assess(pos, "simple_majority", year=2026).single_state_veto_possible is False
    assert assess(pos, "unanimity", year=2026).adopted_by_rule is False


def test_simple_majority_14_of_27():
    pos = all_("abstain")
    for c in sorted(EU27)[:14]:
        pos[c] = "for"
    a = assess(pos, "simple_majority", year=2026)
    assert a.states_required == 14 and a.adopted_by_rule is True and a.states_needed_to_block == 1
    pos[sorted(EU27)[0]] = "against"
    assert assess(pos, "simple_majority", year=2026).adopted_by_rule is False


# ------------------------------------------------------------------ missing data / invalid input
def test_no_population_figures_for_year():
    pos = all_("for")
    a = assess(pos, "qmv", year=2027)
    assert a.population_for_pct is None and a.population_source_celex is None
    assert a.adopted_by_rule is None  # cannot be established without official figures
    pos = all_("against")
    for c in sorted(EU27)[:10]:
        pos[c] = "for"
    assert assess(pos, "qmv", year=2027).adopted_by_rule is False  # fails the states test regardless


@pytest.mark.parametrize(
    "positions,rule",
    [
        ({"DE": "for"}, "qmv"),  # incomplete Council
        (all_("for"), "unknown"),
        ({**all_("for"), "XX": "for"}, "qmv"),
        ({**all_("for"), "DE": "yes"}, "qmv"),
    ],
)
def test_invalid_input_returns_none(positions, rule):
    assert assess(positions, rule, year=2026) is None


def test_uk_only_before_2021():
    pos = dict(all_("for"), GB="for")
    assert assess(pos, "qmv", year=2021) is None
    assert assess(pos, "qmv", year=2020).population_source_celex == "32019D2209"
