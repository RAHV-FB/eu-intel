"""What each of a directive's transposition dates is.

Cellar stores several kinds of date under `directive_date_transposition`: the deadline to adopt and
publish national measures, later deadlines for specific provisions, and the dates from which the
national measures must (or, for some provisions, may) apply. For example, Directive (EU) 2023/2225
(consumer credit), Art. 48(1): "adopt and publish, by 20 November 2025 ... They shall apply those
measures from 20 November 2026".

Each value's comment_on_date annotation (see pipeline/sources/eurlex.py) labels it ADOPTION, APPLICATION
and/or AU+TARD ("at the latest"). Here:

- a date labelled APPLICATION and not ADOPTION is an application date, not a deadline;
- every other date (ADOPTION, AU+TARD alone, or no label) is a deadline to transpose;
- the general deadline is the earliest deadline; later deadlines are "further deadlines" (Cellar does
  not say which provisions they cover - the article reference points to the text that does);
- if Cellar labels every date APPLICATION only, the labels do not separate the dates and all of them
  are treated as deadlines (the earliest is the general one), as without annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pipeline.models.entities import LegalAct

Kind = Literal["deadline", "further_deadline", "application"]


@dataclass(frozen=True)
class Dated:
    date: str
    kind: Kind
    articles: tuple[str, ...] = ()


def classify(act: LegalAct) -> list[Dated]:
    """The directive's transposition dates, ascending, each with its kind. [] for other acts."""
    if act.act_type != "directive" or not act.transposition_deadlines:
        return []
    notes = {t.date: t for t in act.transposition_dates}
    dates = sorted(set(act.transposition_deadlines))

    def is_application(d: str) -> bool:
        labels = set(notes[d].labels) if d in notes else set()
        return "APPLICATION" in labels and "ADOPTION" not in labels

    deadlines = [d for d in dates if not is_application(d)] or dates
    general = deadlines[0]
    out = []
    for d in dates:
        kind: Kind = "deadline" if d == general else "further_deadline" if d in deadlines else "application"
        out.append(Dated(d, kind, tuple(notes[d].articles) if d in notes else ()))
    return out


def general_deadline(act: LegalAct) -> str | None:
    """The date by which Member States had to (or must) transpose the directive in general."""
    return next((x.date for x in classify(act) if x.kind == "deadline"), None)


def article_label(ref: str) -> str:
    """Cellar article reference "48.1" -> "Art. 48(1)"; "6" -> "Art. 6"."""
    head, _, para = ref.partition(".")
    return f"Art. {head}({para})" if para else f"Art. {head}"


def articles_text(articles: tuple[str, ...] | list[str]) -> str:
    return ", ".join(article_label(a) for a in articles)
