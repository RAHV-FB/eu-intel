"""Margin of a European Parliament plenary vote relative to the legally required majority.

`margin(vote, component_members)` answers "by how many votes did this pass / fail?" for an EpVote whose
`majority_rule` is established (pipeline/sources/ep_votes.py sets it only from the Treaty text applying to
that kind of vote). It returns None when the rule is "unknown", the counts are missing, a rule that needs
the number of component Members is given none, or the computed result contradicts the published outcome.

Legal basis (texts retrieved from the Publications Office, CELEX 12016E231 / 12016E234 / 12016E294 /
12016E290 / 12016E354, 62018CJ0650):
- votes_cast — TFEU Art. 231: "Save as otherwise provided in the Treaties, the European Parliament shall act
  by a majority of the votes cast." Only votes for and against are votes cast: Rule 178(3) of the Rules of
  Procedure ("In calculating whether a text has been adopted or rejected, account shall be taken only of
  votes cast for and against, except in those cases for which the Treaties lay down a specific majority",
  as quoted in CJEU C-650/18 Hungary v Parliament, 3 June 2021, ECLI:EU:C:2021:426, para. 7), and the Court
  held that abstentions are not "votes cast" (paras 89 ff.). A text passes if for > against, i.e.
  for >= floor((for + against) / 2) + 1; a tie fails.
- component_members — e.g. TFEU Art. 294(7)(b),(c) (second reading), Art. 290(2) (objection to a delegated
  act): "a majority of its component members", i.e. for >= floor(M / 2) + 1, abstentions and absences
  counting like votes against.
- two_thirds_cast — TFEU Art. 234 (motion of censure) and Art. 354 (Art. 7 TEU): "a two-thirds majority of
  the votes cast, representing a majority of the component Members": for >= ceil(2/3 x (for + against))
  AND for >= floor(M / 2) + 1.

Number of component Members (M): the statutory composition is set by European Council decisions under
Art. 14(2) TEU (see SEATS / statutory_seats()). The Treaty wording "component Members" may be applied by
Parliament to the Members actually in office (vacant seats excluded); press reports of the 18 July 2024
Commission-President vote give both 360 (719 in office) and 361 (720 seats). Callers therefore pass M
explicitly; statutory_seats() is the documented official default, not a confirmed EP calculation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pipeline.models.entities import EpVote

Rule = Literal["votes_cast", "component_members", "two_thirds_cast"]

# Statutory number of Members (seats), with the official act that fixes it.
SEATS: tuple[tuple[str, str | None, int, str], ...] = (
    (
        "2019-07-02",
        "2020-01-31",
        751,
        "European Council Decision 2013/312/EU, Art. 3 — applies until the withdrawal of the United Kingdom "
        "becomes legally effective (European Council Decision (EU) 2018/937, Art. 3(2))",
    ),
    ("2020-02-01", "2024-07-15", 705, "European Council Decision (EU) 2018/937, Art. 3(1) — 2019-2024 term"),
    ("2024-07-16", None, 720, "European Council Decision (EU) 2023/2061, Art. 3 — 2024-2029 term"),
)


def statutory_seats(day: str) -> int | None:
    """Statutory number of Members of the European Parliament on `day` (ISO date), or None if not covered."""
    for start, end, seats, _basis in SEATS:
        if start <= day and (end is None or day <= end):
            return seats
    return None


class Margin(BaseModel):
    rule: Rule
    threshold: int  # votes in favour needed
    votes_for: int
    votes_cast: int  # for + against (abstentions are not votes cast)
    component_members: int | None = None
    distance: int  # votes_for - threshold; >= 0 means the required majority was reached
    relative: float | None  # distance / votes cast
    label: str


def _plural(n: int) -> str:
    return f"{n} vote" if n == 1 else f"{n} votes"


def threshold(rule: str, n_for: int, n_against: int, component_members: int | None) -> int | None:
    """Votes in favour required under `rule`, or None when it cannot be established."""
    cast = n_for + n_against
    majority_of_members = component_members // 2 + 1 if component_members else None
    if rule == "votes_cast":
        return cast // 2 + 1 if cast > 0 else None
    if rule == "component_members":
        return majority_of_members
    if rule == "two_thirds_cast":
        if majority_of_members is None or cast <= 0:
            return None
        two_thirds = -(-2 * cast // 3)  # ceil(2 * cast / 3)
        return max(two_thirds, majority_of_members)
    return None


def margin(vote: EpVote, component_members: int | None = None) -> Margin | None:
    rule = vote.majority_rule
    if rule == "unknown" or vote.n_for is None or vote.n_against is None:
        return None
    need = threshold(rule, vote.n_for, vote.n_against, component_members)
    if need is None:
        return None
    cast = vote.n_for + vote.n_against
    distance = vote.n_for - need
    reached = distance >= 0
    if (vote.outcome == "adopted" and not reached) or (vote.outcome == "rejected" and reached):
        return None  # contradicts the official result: the rule does not describe this vote
    if distance > 0:
        label = f"Passed by {_plural(distance)} above the required majority"
    elif distance == 0:
        label = "Passed with exactly the required majority"
    else:
        label = f"Fell {_plural(-distance)} short"
    return Margin(
        rule=rule,
        threshold=need,
        votes_for=vote.n_for,
        votes_cast=cast,
        component_members=component_members if rule != "votes_cast" else None,
        distance=distance,
        relative=round(distance / cast, 4) if cast else None,
        label=label,
    )
