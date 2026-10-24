"""Council of the European Union voting-rule arithmetic (pure functions, no I/O).

This concerns the Council of the EU (ministers of the Member States), NOT the European Council.

Legal rules implemented
- QMV, all Member States take part, Council acts on a proposal from the Commission or the High
  Representative (TEU Art. 16(4)): at least 55 % of the members of the Council, comprising at least
  fifteen of them, representing Member States comprising at least 65 % of the population of the Union.
  A blocking minority must include at least four Council members, failing which the qualified
  majority is deemed attained.
- QMV, all take part, NOT on a Commission/HR proposal (TFEU Art. 238(2)): at least 72 % of the members
  representing at least 65 % of the population. (No "four members" blocking-minority clause.)
- QMV where not all members take part (TFEU Art. 238(3), e.g. Denmark/Ireland opt-outs): the same
  percentages computed over the *participating* Member States only (238(3)(a): 55 % / 65 %, with a
  blocking minority of at least the minimum number of members representing more than 35 % of the
  participating population, plus one member; 238(3)(b): 72 % / 65 % when not on a Commission/HR proposal).
- Under QMV, abstentions (and votes against) count as "not supporting".
- Unanimity: abstentions by members present in person or represented do not prevent adoption
  (TFEU Art. 238(4)); any participating Member State voting against prevents adoption. This is the ONLY
  rule under which a single country's "no" is a veto.
- Simple majority (TFEU Art. 238(1)): a majority of the component members (14 of 27). Where some
  members do not take part, it is computed over the participating members (assumption, flagged in the
  result's `notes`).

"not_participating" means a Member State that does not take part in the vote under the Treaties
(opt-outs, enhanced cooperation); it is excluded from the thresholds. It is NOT an abstention.

Population figures are the official ones the Council applies, i.e. Annex III to the Council's Rules of
Procedure as amended each year by a Council Decision (Art. 11(6) of the Rules of Procedure). They are
stored below with the CELEX of the decision. For years without verified figures the population checks
return None (never guessed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pipeline.models.countries import MEMBER_STATES
from pipeline.models.entities import CouncilPosition, Model

Rule = Literal["qmv", "unanimity", "simple_majority"]


@dataclass(frozen=True)
class PopulationTable:
    year: int
    celex: str  # Council Decision amending Annex III to the Council's Rules of Procedure
    label: str
    valid_from: str  # ISO date (inclusive)
    valid_to: str  # ISO date (inclusive)
    population: dict[str, int] = field(repr=False)

    @property
    def total(self) -> int:
        return sum(self.population.values())


# Figures transcribed from the official texts (Cellar XHTML of each CELEX) and checked: the per-State
# figures sum exactly to the EU total printed in each decision. Tests re-check the published totals.
# 2019: only the EU-28 table of 32018D2076 is included; its EU-27 table (applicable only after a UK
# withdrawal during 2019) never applied. 2020: EU-28 until 31 Jan 2020, EU-27 from 1 Feb 2020
# (the Treaties ceased to apply to the UK on 1 February 2020), both from 32019D2209.
# fmt: off
POPULATION_TABLES: tuple[PopulationTable, ...] = (
    PopulationTable(2019, "32018D2076", "Council Decision (EU, Euratom) 2018/2076, Annex III point 1 (EU-28)", "2019-01-01", "2019-12-31",
        {"AT": 8802000, "BE": 11413058, "BG": 7050034, "CY": 864236, "CZ": 10493154, "DE": 82719022, "DK": 5774877, "EE": 1319133, "ES": 46659302, "FI": 5501930, "FR": 67221943, "GB": 66238007, "GR": 10738928, "HR": 4105493, "HU": 9778371, "IE": 4830392, "IT": 61166142, "LT": 2808901, "LU": 600124, "LV": 1934379, "MT": 475701, "NL": 17321110, "PL": 37976687, "PT": 10291027, "RO": 19523621, "SE": 10157000, "SI": 2066880, "SK": 5443120}),
    PopulationTable(2020, "32019D2209", "Council Decision (EU, Euratom) 2019/2209, Annex III point 1 (EU-28)", "2020-01-01", "2020-01-31",
        {"AT": 8842000, "BE": 11467923, "BG": 7000039, "CY": 875898, "CZ": 10528984, "DE": 82940663, "DK": 5799763, "EE": 1324820, "ES": 46934632, "FI": 5512119, "FR": 67028048, "GB": 66647112, "GR": 10722287, "HR": 4076246, "HU": 9772756, "IE": 4904240, "IT": 61068437, "LT": 2794184, "LU": 612179, "LV": 1919968, "MT": 493559, "NL": 17423013, "PL": 37972812, "PT": 10276617, "RO": 19405156, "SE": 10243000, "SI": 2080908, "SK": 5450421}),
    PopulationTable(2020, "32019D2209", "Council Decision (EU, Euratom) 2019/2209, Annex III point 2 (EU-27)", "2020-02-01", "2020-12-31",
        {"AT": 8842000, "BE": 11467923, "BG": 7000039, "CY": 875898, "CZ": 10528984, "DE": 82940663, "DK": 5799763, "EE": 1324820, "ES": 46934632, "FI": 5512119, "FR": 67028048, "GR": 10722287, "HR": 4076246, "HU": 9772756, "IE": 4904240, "IT": 61068437, "LT": 2794184, "LU": 612179, "LV": 1919968, "MT": 493559, "NL": 17423013, "PL": 37972812, "PT": 10276617, "RO": 19405156, "SE": 10243000, "SI": 2080908, "SK": 5450421}),
    PopulationTable(2021, "32020D2030", "Council Decision (EU, Euratom) 2020/2030, Annex III", "2021-01-01", "2021-12-31",
        {"AT": 8897000, "BE": 11549888, "BG": 6951482, "CY": 888005, "CZ": 10557001, "DE": 83100961, "DK": 5816443, "EE": 1328976, "ES": 47329981, "FI": 5521292, "FR": 67098824, "GR": 10709739, "HR": 4058165, "HU": 9769526, "IE": 4964440, "IT": 60897891, "LT": 2794090, "LU": 623962, "LV": 1907675, "MT": 514564, "NL": 17549457, "PL": 37958138, "PT": 10295909, "RO": 19317984, "SE": 10330000, "SI": 2095861, "SK": 5457873}),
    PopulationTable(2022, "32021D2320", "Council Decision (EU, Euratom) 2021/2320, Annex III", "2022-01-01", "2022-12-31",
        {"AT": 8926000, "BE": 11566041, "BG": 6916548, "CY": 896000, "CZ": 10574153, "DE": 83120520, "DK": 5833883, "EE": 1330068, "ES": 47394223, "FI": 5527493, "FR": 67439614, "GR": 10682547, "HR": 4036355, "HU": 9730772, "IE": 5006324, "IT": 59862348, "LT": 2795680, "LU": 633347, "LV": 1893223, "MT": 516100, "NL": 17617840, "PL": 37840001, "PT": 10298252, "RO": 19186201, "SE": 10370000, "SI": 2108977, "SK": 5459781}),
    PopulationTable(2023, "32022D2518", "Council Decision (EU, Euratom) 2022/2518, Annex III", "2023-01-01", "2023-12-31",
        {"AT": 8967500, "BE": 11631136, "BG": 6838937, "CY": 904700, "CZ": 10545457, "DE": 83203320, "DK": 5864667, "EE": 1331796, "ES": 47432805, "FI": 5541241, "FR": 67842582, "GR": 10603810, "HR": 3862305, "HU": 9689010, "IE": 5060004, "IT": 59607184, "LT": 2805998, "LU": 643648, "LV": 1875757, "MT": 520971, "NL": 17734036, "PL": 37654247, "PT": 10352042, "RO": 19038098, "SE": 10440000, "SI": 2107180, "SK": 5434712}),
    PopulationTable(2024, "32023D2827", "Council Decision (EU, Euratom) 2023/2827, Annex III", "2024-01-01", "2024-12-31",
        {"AT": 9087000, "BE": 11754004, "BG": 6498567, "CY": 920701, "CZ": 10833385, "DE": 84311244, "DK": 5921952, "EE": 1365884, "ES": 48063694, "FI": 5593070, "FR": 68070697, "GR": 10415585, "HR": 3850894, "HU": 9599744, "IE": 5194336, "IT": 59691110, "LT": 2857279, "LU": 658278, "LV": 1883008, "MT": 542051, "NL": 17956453, "PL": 37723532, "PT": 10516621, "RO": 19051562, "SE": 10541000, "SI": 2116972, "SK": 5454629}),
    PopulationTable(2025, "32024D3231", "Council Decision (EU, Euratom) 2024/3231, Annex III", "2025-01-01", "2025-12-31",
        {"AT": 9132500, "BE": 11832049, "BG": 6445481, "CY": 933505, "CZ": 10916836, "DE": 83399432, "DK": 5954471, "EE": 1374687, "ES": 48630010, "FI": 5619851, "FR": 68401997, "GR": 10401302, "HR": 3861967, "HU": 9584627, "IE": 5351681, "IT": 59685948, "LT": 2885891, "LU": 670093, "LV": 1871882, "MT": 563443, "NL": 18089177, "PL": 37565715, "PT": 10639726, "RO": 19064409, "SE": 10573000, "SI": 2123949, "SK": 5455252}),
    PopulationTable(2026, "32025D2427", "Council Decision (EU, Euratom) 2025/2427, Annex III", "2026-01-01", "2026-12-31",
        {"AT": 9180000, "BE": 11900123, "BG": 6437360, "CY": 982966, "CZ": 10921096, "DE": 83502300, "DK": 5985790, "EE": 1369995, "ES": 49093546, "FI": 5626971, "FR": 68635943, "GR": 10409547, "HR": 3874350, "HU": 9539502, "IE": 5440278, "IT": 59635202, "LT": 2890664, "LU": 680084, "LV": 1860565, "MT": 574250, "NL": 18191086, "PL": 37475594, "PT": 10749635, "RO": 19036031, "SE": 10583000, "SI": 2130850, "SK": 5456246}),
)
# fmt: on

# EU totals exactly as printed in each decision (used by tests to check the transcription).
PUBLISHED_TOTALS: dict[tuple[str, int], int] = {
    ("32018D2076", 28): 513_274_572,
    ("32019D2209", 28): 514_117_784,
    ("32019D2209", 27): 447_470_672,
    ("32020D2030", 27): 448_285_127,
    ("32021D2320", 27): 447_562_291,
    ("32022D2518", 27): 447_533_143,
    ("32023D2827", 27): 450_473_252,
    ("32024D3231", 27): 451_028_881,
    ("32025D2427", 27): 452_162_974,
}

EU27 = frozenset(MEMBER_STATES)
EU28 = EU27 | {"GB"}


def population_table(year: int, members: frozenset[str] | set[str]) -> PopulationTable | None:
    """The official population table applicable in `year` to a Council of exactly `members`."""
    for t in POPULATION_TABLES:
        if t.year == year and set(t.population) == set(members):
            return t
    return None


class CouncilAssessment(Model):
    """Result of applying a Council voting rule to a recorded set of positions."""

    rule: Rule
    legal_basis: str  # e.g. "TEU Art. 16(4)", "TFEU Art. 238(3)(a)", "TFEU Art. 238(4)"
    on_commission_proposal: bool
    year: int
    members: int  # Member States in the Council at the time (27, or 28 before February 2020)
    participating: int
    states_for: int
    states_against: int
    states_abstain: int
    states_not_participating: int
    # Minimum number of supporting states required (QMV / simple majority); None for unanimity.
    states_required: int | None
    # Population (official Council figures). None if no verified figures exist for that year.
    population_for: int | None = None
    population_participating: int | None = None
    population_for_pct: float | None = None  # share of the participating population, rounded to 0.01
    population_required_pct: float | None = None  # 65.0 under QMV, else None
    population_source_celex: str | None = None
    # True/False by the rule's arithmetic; None if it cannot be established (missing population figures).
    adopted_by_rule: bool | None
    # QMV only: did the non-supporting states form a blocking minority?
    blocking_minority_formed: bool | None = None
    # QMV only: smallest blocking minority (in states) that can block by population
    # (4 under TEU Art. 16(4); computed under TFEU Art. 238(3)(a); None where no such clause applies).
    blocking_minority_min_states: int | None = None
    # QMV only: population criterion not met but the qualified majority is "deemed attained".
    deemed_attained: bool = False
    # Unanimity only: at least one participating state voted against.
    veto_exercised: bool | None = None
    # Smallest number of supporting states that, by withholding support, would have prevented adoption
    # (computed only for adopted outcomes where the population figures are known or not needed).
    states_needed_to_block: int | None = None
    margin_states: int | None = None  # states_for - states_required
    margin_population_pct: float | None = None  # population_for_pct - 65 (QMV)
    single_state_veto_possible: bool
    notes: list[str] = []


def _ceil_pct(n: int, pct: int) -> int:
    """ceil(n * pct / 100) in exact integer arithmetic."""
    return (n * pct + 99) // 100


def _meets_population(pop_for: int, pop_total: int) -> bool:
    return pop_for * 100 >= 65 * pop_total


def _min_states_over_35pct(pops: list[int]) -> int:
    """Minimum number of members whose combined population exceeds 35 % of sum(pops)."""
    total = sum(pops)
    acc = 0
    for i, p in enumerate(sorted(pops, reverse=True), start=1):
        acc += p
        if acc * 100 > 35 * total:
            return i
    return len(pops)


def assess(
    positions: dict[str, CouncilPosition],
    rule: str,
    on_commission_proposal: bool = True,
    *,
    year: int,
) -> CouncilAssessment | None:
    """Apply a Council voting rule to recorded positions.

    `positions` must cover exactly the Council's membership at the time (EU-27, or EU-28 including "GB"
    before February 2020), with ISO alpha-2 keys (Greece "GR"). Returns None if the rule is not one of
    "qmv" / "unanimity" / "simple_majority", or if the positions do not describe a full Council.
    """
    if rule not in ("qmv", "unanimity", "simple_majority"):
        return None
    members = set(positions)
    if members not in (EU27, EU28) or any(
        p not in ("for", "against", "abstain", "not_participating") for p in positions.values()
    ):
        return None
    if "GB" in members and year > 2020:
        return None

    part = [c for c, p in positions.items() if p != "not_participating"]
    supporters = [c for c, p in positions.items() if p == "for"]
    n_for = len(supporters)
    n_against = sum(1 for p in positions.values() if p == "against")
    n_abstain = sum(1 for p in positions.values() if p == "abstain")
    n_np = len(members) - len(part)
    n_part = len(part)
    all_take_part = n_np == 0
    notes: list[str] = []

    table = population_table(year, members)
    pop_for = pop_part = None
    pop_pct = None
    if table is not None and n_part:
        pop_for = sum(table.population[c] for c in supporters)
        pop_part = sum(table.population[c] for c in part)
        pop_pct = round(100 * pop_for / pop_part, 2)
    elif table is None:
        notes.append(f"No verified official population figures for {year}; population checks not computed.")

    base = dict(
        rule=rule,
        on_commission_proposal=on_commission_proposal,
        year=year,
        members=len(members),
        participating=n_part,
        states_for=n_for,
        states_against=n_against,
        states_abstain=n_abstain,
        states_not_participating=n_np,
        population_for=pop_for,
        population_participating=pop_part,
        population_for_pct=pop_pct,
        population_source_celex=table.celex if table else None,
        notes=notes,
    )

    if rule == "unanimity":
        adopted = n_against == 0 and n_for >= 1
        return CouncilAssessment(
            **base,
            legal_basis="TFEU Art. 238(4)" + ("" if all_take_part else " (participating Member States only)"),
            states_required=None,
            adopted_by_rule=adopted,
            veto_exercised=n_against > 0,
            states_needed_to_block=1 if adopted else None,
            single_state_veto_possible=True,
        )

    if rule == "simple_majority":
        required = n_part // 2 + 1
        if not all_take_part:
            notes.append(
                "Simple majority computed over participating members (Treaty text: component members)."
            )
        adopted = n_for >= required
        return CouncilAssessment(
            **base,
            legal_basis="TFEU Art. 238(1)",
            states_required=required,
            adopted_by_rule=adopted,
            states_needed_to_block=(n_for - required + 1) if adopted else None,
            margin_states=n_for - required,
            single_state_veto_possible=False,
        )

    # ---- QMV
    if all_take_part:
        if on_commission_proposal:
            legal_basis = "TEU Art. 16(4)"
            required = max(15, _ceil_pct(n_part, 55))
            min_block: int | None = 4
        else:
            legal_basis = "TFEU Art. 238(2)"
            required = _ceil_pct(n_part, 72)
            min_block = None
    else:
        if on_commission_proposal:
            legal_basis = "TFEU Art. 238(3)(a)"
            required = _ceil_pct(n_part, 55)
            min_block = (
                _min_states_over_35pct([table.population[c] for c in part]) + 1 if table is not None else None
            )
        else:
            legal_basis = "TFEU Art. 238(3)(b)"
            required = _ceil_pct(n_part, 72)
            min_block = None

    states_ok = n_for >= required
    non_supporters = n_part - n_for
    result = dict(
        legal_basis=legal_basis,
        states_required=required,
        population_required_pct=65.0,
        margin_states=n_for - required,
        single_state_veto_possible=False,
        blocking_minority_min_states=min_block,
    )

    if pop_for is None or pop_part is None:
        # Without official population figures only a failed states criterion is conclusive.
        if not states_ok:
            return CouncilAssessment(**base, **result, adopted_by_rule=False, blocking_minority_formed=True)
        if on_commission_proposal and not all_take_part and min_block is None:
            notes.append("Blocking-minority size under TFEU Art. 238(3)(a) needs population figures.")
        return CouncilAssessment(**base, **result, adopted_by_rule=None, blocking_minority_formed=None)

    pop_ok = _meets_population(pop_for, pop_part)
    deemed = False
    if states_ok and not pop_ok and min_block is not None and non_supporters < min_block:
        deemed = True  # blocking minority too small: QM deemed attained
    adopted = states_ok and (pop_ok or deemed)

    needed: int | None = None
    if adopted:
        # Withholding support by the k most populous supporters is optimal for the population test;
        # the states test only depends on k.
        sup_pops = sorted((table.population[c] for c in supporters), reverse=True) if table else []
        removed = 0
        for k in range(1, n_for + 1):
            removed += sup_pops[k - 1]
            if n_for - k < required:
                needed = k
                break
            pop_fails = not _meets_population(pop_for - removed, pop_part)
            if pop_fails and (min_block is None or non_supporters + k >= min_block):
                needed = k
                break

    return CouncilAssessment(
        **base,
        **result,
        adopted_by_rule=adopted,
        blocking_minority_formed=not adopted,
        deemed_attained=deemed,
        states_needed_to_block=needed,
        margin_population_pct=round(pop_pct - 65.0, 2) if pop_pct is not None else None,
    )
