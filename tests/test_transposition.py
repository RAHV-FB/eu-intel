"""Classification of a directive's transposition dates from Cellar's annotations."""

from __future__ import annotations

from pipeline.analysis.transposition import article_label, classify, general_deadline
from pipeline.models.entities import LegalAct, SourceRef, TranspositionDate


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
