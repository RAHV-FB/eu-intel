"""What each of a directive's transposition dates is.

Cellar stores several kinds of date under `directive_date_transposition`: the deadline to adopt and
publish national measures, deadlines for specific provisions, and the dates from which the national
measures must (or, for some provisions, may) apply. For example, Directive (EU) 2023/2225 (consumer
credit), Art. 48(1): "adopt and publish, by 20 November 2025 ... They shall apply those measures from
20 November 2026".

Each value's comment_on_date annotation (see pipeline/sources/eurlex.py) labels it ADOPTION, APPLICATION
and/or AU+TARD ("at the latest") and names the article setting it. Here:

- a date labelled APPLICATION and not ADOPTION is an application date, not a deadline;
- every other date (ADOPTION, AU+TARD alone, or no label) is a deadline to transpose;
- if Cellar labels every date APPLICATION only, the labels do not separate the dates: the general
  deadline is chosen among all of them (as below) and the others stay application dates;
- the general deadline is, in this order: the date checked against the act's text
  (data/curated/transposition.yaml, see `CheckedTransposition`); the deadline whose article reference
  comes first in the text, when no other deadline shares it (Directive (EU) 2023/2864: Art. 17(1) sets
  10 January 2026 for "this Directive", Art. 17(2) 10 July 2025 for Article 3 only); otherwise the
  earliest deadline ("date order": the data do not decide, and validate.py lists such directives). The
  earliest is not always right: Directive (EU) 2024/1640, Art. 78(1), sets 10 July 2027 in general and
  10 July 2025 for Article 74 only, both under the same article reference;
- the other deadlines are deadlines for specific provisions ("further deadlines"), earlier or later than
  the general one. Cellar does not say which provisions they cover; the article reference points to the
  text that does;
- a date is "other" (recorded by EUR-Lex, but the data do not establish what it is) when the curated
  check says so; when it comes from another article than the general deadline (Directive (EU) 2020/2184,
  Art. 25, a transitional period); or when it is an application date before the general deadline set in
  a paragraph that sets no deadline (Directive (EU) 2025/516, Art. 6(1): Member States "may apply ...
  from 14 April 2025").

The general application date (`application_start`) is the checked one, else the general deadline itself
when Cellar labels it APPLICATION too and gives one article for it (Directive (EU) 2024/927, Art. 3(1):
"adopt and publish, by 16 April 2026 ... apply those measures from 16 April 2026"), else the first
application date after the general deadline. With several articles on an APPLICATION-labelled general
deadline the label may belong to any of them, and the general application date is left undetermined.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pipeline.models.entities import LegalAct

Kind = Literal["deadline", "further_deadline", "application", "other"]
# How the general deadline was established (see the module docstring); "single": the only deadline
Basis = Literal["checked", "article", "date_order", "single"]


@dataclass(frozen=True)
class Dated:
    date: str
    kind: Kind
    articles: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()  # Cellar's ADOPTION / APPLICATION / AU+TARD


def _ref_key(ref: str) -> tuple[tuple[int, str], ...]:
    """Cellar article reference in text order: "49.1.2" -> ((49, ''), (1, ''), (2, '')), "57.2a" -> (.., (2, 'a'))."""
    out = []
    for part in ref.split("."):
        m = re.match(r"(\d+)(.*)", part)
        out.append((int(m.group(1)), m.group(2)) if m else (0, part))
    return tuple(out)


def _article(ref: str) -> str:
    return ref.partition(".")[0]


def _paragraph(ref: str) -> str:
    """The paragraph of an article reference: "49.1.2" -> "49.1", "12.3(a)" -> "12.3", "6" -> "6"."""
    head, _, rest = ref.partition(".")
    m = re.match(r"\d+[a-z]*", rest)
    return f"{head}.{m.group(0)}" if m else head


def _general(act: LegalAct, deadlines: list[str], arts: dict[str, tuple[str, ...]]) -> tuple[str, Basis]:
    chk = act.transposition_checked
    if chk and chk.deadline in arts:
        return chk.deadline, "checked"
    if len(deadlines) == 1:
        return deadlines[0], "single"
    if all(arts[d] for d in deadlines):
        first = {d: min(_ref_key(r) for r in arts[d]) for d in deadlines}
        top = [d for d in deadlines if first[d] == min(first.values())]
        if len(top) == 1:
            return top[0], "article"
    return deadlines[0], "date_order"


def _classify(act: LegalAct) -> tuple[list[Dated], Basis | None]:
    if act.act_type != "directive" or not act.transposition_deadlines:
        return [], None
    notes = {t.date: t for t in act.transposition_dates}
    dates = sorted(set(act.transposition_deadlines))
    arts = {d: tuple(notes[d].articles) if d in notes else () for d in dates}
    labels = {d: tuple(notes[d].labels) if d in notes else () for d in dates}

    def is_application(d: str) -> bool:
        return "APPLICATION" in labels[d] and "ADOPTION" not in labels[d]

    deadlines = [d for d in dates if not is_application(d)] or dates
    general, basis = _general(act, deadlines, arts)
    chk = act.transposition_checked
    other = set(chk.other) if chk else set()
    general_articles = {_article(r) for r in arts[general]}
    # paragraphs that set a deadline (a general deadline may be labelled APPLICATION only)
    setting_deadlines = {general} | {d for d in dates if not is_application(d)}
    deadline_paragraphs = {_paragraph(r) for d in setting_deadlines for r in arts[d]}
    out = []
    for d in dates:
        own = arts[d]
        kind: Kind
        if d == general:
            kind = "deadline"
        elif d in other or (general_articles and own and not {_article(r) for r in own} & general_articles):
            kind = "other"
        elif not is_application(d):
            kind = "further_deadline"
        elif d < general and own and not {_paragraph(r) for r in own} & deadline_paragraphs:
            kind = "other"  # e.g. an optional early application ("may apply ... from")
        else:
            kind = "application"
        out.append(Dated(d, kind, own, labels[d]))
    return out, basis


def classify(act: LegalAct) -> list[Dated]:
    """The directive's transposition dates, ascending, each with its kind. [] for other acts."""
    return _classify(act)[0]


def general_deadline(act: LegalAct) -> str | None:
    """The date by which Member States had to (or must) transpose the directive in general."""
    return next((x.date for x in classify(act) if x.kind == "deadline"), None)


def general_deadline_basis(act: LegalAct) -> Basis | None:
    """How the general deadline was established; None without transposition dates."""
    return _classify(act)[1]


def application_start(act: LegalAct, dated: list[Dated] | None = None) -> str | None:
    """The date from which the national measures apply in general, when the data establish it."""
    xs = classify(act) if dated is None else dated
    general = next((x for x in xs if x.kind == "deadline"), None)
    if general is None:
        return None
    chk = act.transposition_checked
    if chk and chk.applies_from and any(x.date == chk.applies_from for x in xs):
        return chk.applies_from
    if "APPLICATION" in general.labels:
        return general.date if len(general.articles) <= 1 else None
    return next((x.date for x in xs if x.kind == "application" and x.date > general.date), None)


SUBPARAGRAPHS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def article_label(ref: str) -> str:
    """Cellar article reference "48.1" -> "Art. 48(1)"; "6" -> "Art. 6"; "12.3(a)" -> "Art. 12(3)(a)";
    "49.1.2" -> "Art. 49(1), second subparagraph"."""
    head, _, rest = ref.partition(".")
    if not rest:
        return f"Art. {head}"
    para, _, sub = rest.partition(".")
    m = re.fullmatch(r"(\d+[a-z]*)(\(.*\))?", para)
    label = f"Art. {head}({m.group(1)}){m.group(2) or ''}" if m else f"Art. {head}({para})"
    if sub.isdigit() and 0 < int(sub) <= len(SUBPARAGRAPHS):
        return f"{label}, {SUBPARAGRAPHS[int(sub) - 1]} subparagraph"
    return f"{label}, subparagraph {sub}" if sub else label


def articles_text(articles: tuple[str, ...] | list[str]) -> str:
    return ", ".join(article_label(a) for a in articles)
