"""Classification of a directive's transposition dates from Cellar's annotations.

The second part uses real EUR-Lex records (tests/fixtures/eurlex/transposition_acts.json, copied from
data/snapshot/eurlex/acts.json) and the checks in data/curated/transposition.yaml.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pytest

from pipeline.analysis.transposition import (
    application_start,
    article_label,
    classify,
    general_deadline,
    general_deadline_basis,
)
from pipeline.build import apply_transposition_checks, load_transposition_checks
from pipeline.models.entities import LegalAct, SourceRef, TranspositionDate

FIX = Path(__file__).parent / "fixtures" / "eurlex" / "transposition_acts.json"


def directive(dates: dict[str, list[str]], act_type: str = "directive") -> LegalAct:
    return LegalAct(
        celex="32099L0001",
        act_type=act_type,  # type: ignore[arg-type]
        title="Directive",
        transposition_deadlines=sorted(dates),
        transposition_dates=[TranspositionDate(date=d, labels=labels) for d, labels in sorted(dates.items())],
        eurlex_url="https://eur-lex.europa.eu/",
        source=SourceRef(institution="EUR-Lex", url="https://eur-lex.europa.eu/", retrieved_at="2026-10-22T00:00:00Z"),
    )


def kinds(a: LegalAct) -> list[tuple[str, str]]:
    return [(x.date, x.kind) for x in classify(a)]


def test_adoption_and_application_dates():  # NIS2 Art. 41(1)
    a = directive({"2024-10-17": ["ADOPTION"], "2024-10-18": ["APPLICATION"]})
    assert kinds(a) == [("2024-10-17", "deadline"), ("2024-10-18", "application")]
    assert general_deadline(a) == "2024-10-17"


def test_optional_early_application_date_is_not_the_deadline():  # VAT in the digital age 2025/516
    a = directive({
        "2025-04-14": ["APPLICATION"],  # Art. 6(1): Member States *may* apply ... from
        "2026-12-31": ["ADOPTION", "AU+TARD"],
        "2027-01-01": ["APPLICATION"],
        "2028-06-30": ["ADOPTION", "AU+TARD"],
    })  # fmt: skip
    assert general_deadline(a) == "2026-12-31"
    assert kinds(a) == [
        ("2025-04-14", "application"),
        ("2026-12-31", "deadline"),
        ("2027-01-01", "application"),
        ("2028-06-30", "further_deadline"),
    ]


def test_at_the_latest_dates_are_deadlines():  # AMLD4 2015/849 Art. 67
    a = directive({"2017-06-26": ["AU+TARD"], "2024-12-30": ["ADOPTION", "APPLICATION"]})
    assert kinds(a) == [("2017-06-26", "deadline"), ("2024-12-30", "further_deadline")]


def test_unlabelled_dates_are_deadlines():  # Drinking Water Directive 2020/2184
    a = directive({"2023-01-12": [], "2026-01-12": []})
    assert kinds(a) == [("2023-01-12", "deadline"), ("2026-01-12", "further_deadline")]


def test_only_application_labels_fall_back_to_deadlines():
    a = directive({"2027-01-01": ["APPLICATION"], "2028-01-01": ["APPLICATION"]})
    assert general_deadline(a) == "2027-01-01"


def test_not_a_directive_or_no_dates():
    assert classify(directive({"2027-01-01": []}, act_type="regulation")) == []
    assert general_deadline(directive({})) is None


def test_article_label():
    assert article_label("48.1") == "Art. 48(1)"
    assert article_label("6") == "Art. 6"
    assert article_label("12.3(a)") == "Art. 12(3)(a)"
    assert article_label("93.3a") == "Art. 93(3a)"
    assert article_label("49.1.2") == "Art. 49(1), second subparagraph"


# ============================================================ real records
@cache
def _records() -> dict[str, dict]:
    return {a["celex"]: a for a in json.loads(FIX.read_text(encoding="utf-8"))}


def real(celex: str, checked: bool = True) -> LegalAct:
    a = LegalAct.model_validate(_records()[celex])
    return apply_transposition_checks(a, load_transposition_checks().get(celex)) if checked else a


def test_amld6_general_deadline_is_the_checked_one_not_the_earliest():
    # Directive (EU) 2024/1640, Art. 78(1): "... necessary to comply with this Directive by 10 July 2027";
    # 10 July 2025 (Art. 74), 10 July 2026 (Arts 11-13, 15) and 10 July 2029 (Art. 18) are derogations, and
    # Cellar gives "78.1" for all four dates, so only the check of the text decides
    raw = real("32024L1640", checked=False)
    assert (general_deadline(raw), general_deadline_basis(raw)) == ("2025-07-10", "date_order")
    a = real("32024L1640")
    assert (general_deadline(a), general_deadline_basis(a)) == ("2027-07-10", "checked")
    assert kinds(a) == [
        ("2025-07-10", "further_deadline"),
        ("2026-07-10", "further_deadline"),
        ("2027-07-10", "deadline"),
        ("2029-07-10", "further_deadline"),
    ]


@pytest.mark.parametrize(
    "celex, general",
    [
        ("32023L2864", "2026-01-10"),  # Art. 17(1) "this Directive"; Art. 17(2) 10 July 2025 for Article 3
        ("32025L2205", "2028-11-26"),  # Art. 29(1); Art. 29(2) 26 November 2027 for Art. 9(2)(j), (k)
        ("32019L2177", "2021-06-30"),  # Art. 4(1); Art. 4(2) 30 June 2020 for point (1) of Article 2
    ],
)
def test_article_reference_decides_the_general_deadline(celex, general):
    a = real(celex, checked=False)
    assert (general_deadline(a), general_deadline_basis(a)) == (general, "article")


def test_pressure_equipment_first_paragraph_is_a_derogation():
    # Directive 2014/68/EU, Art. 49(1): Article 13 only, by 28 February 2015; Art. 49(2): the bulk, by 18 July 2016
    assert general_deadline(real("32014L0068", checked=False)) == "2015-02-28"  # the article rule alone
    a = real("32014L0068")
    assert general_deadline(a) == "2016-07-18"
    assert application_start(a) == "2016-07-19"
    assert article_label(classify(a)[0].articles[0]) == "Art. 49(1), first subparagraph"


@pytest.mark.parametrize(
    "celex, date",
    [
        ("32020L2184", "2026-01-12"),  # Art. 25, "Transitional period": another article than Art. 24
        ("32025L0516", "2025-04-14"),  # Art. 6(1): Member States "may apply ... from 14 April 2025"
        ("32019L0879", "2024-01-01"),  # Art. 3(1): conditional application date of one provision (checked)
    ],
)
def test_dates_whose_role_is_not_established_are_other(celex, date):
    a = real(celex)
    assert dict(kinds(a))[date] == "other"
    assert date not in [x.date for x in classify(a) if x.kind in ("deadline", "further_deadline", "application")]


@pytest.mark.parametrize(
    "celex, start",
    [
        ("32019L0882", "2025-06-28"),  # EAA Art. 31(2); 28 June 2027 is the optional Art. 4(8) derogation
        ("32024L1619", "2026-01-11"),  # CRD VI Art. 2(1); 11 January 2027 for Article 1, points (9) and (13)
        ("32024L0927", "2026-04-16"),  # AIFMD II Art. 3(1): adopt by and apply from 16 April 2026
        ("32023L2226", "2026-01-01"),  # DAC8 Art. 2(1)
        ("32025L0872", "2026-01-01"),  # DAC9 Art. 2(1)
        ("32026L0804", "2028-05-11"),  # Art. 3(1): apply from 11 May 2028; 11 May 2029 for Art. 11(3) and others
        ("32025L2205", "2029-11-26"),  # Art. 29(1), second subparagraph (checked: Cellar labels cannot tell)
    ],
)
def test_general_application_date(celex, start):
    assert application_start(real(celex)) == start


def test_application_date_left_undetermined_when_labels_cannot_tell():
    # Driving licences: 26 November 2028 is labelled APPLICATION for Art. 29(3) (Article 17), not Art. 29(1)
    assert application_start(real("32025L2205", checked=False)) is None


def test_every_curated_check_names_recorded_dates():
    checks = load_transposition_checks()
    assert checks, "data/curated/transposition.yaml is empty"
    for celex, e in checks.items():
        assert e.get("provision") and e.get("quote") and e.get("source", {}).get("url") and e.get("reviewed"), celex
        if celex in _records():
            assert real(celex).transposition_checked is not None, celex
