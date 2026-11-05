"""iCalendar (RFC 5545) for the calendars the site publishes: content lines, TEXT escaping and line folding.

- Lines end in CRLF (3.1) and are folded so that no line is longer than 75 octets: a longer line is split, never
  inside a UTF-8 sequence, and each continuation line starts with one space, which counts towards its 75 octets.
- TEXT values (3.3.11) escape a backslash, a semicolon and a comma with a backslash, and write a line break as "\\n".
  A control character other than a line break cannot be in a TEXT value and is left out.
- A whole-day event has a DATE start and the next day as its (exclusive) end (3.6.1, 3.8.2.2).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

LINE_OCTETS = 75
# control characters a TEXT value cannot hold (3.3.11: TSAFE-CHAR excludes CONTROL; line breaks are written as "\n")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def text(value: object) -> str:
    """A TEXT value, escaped: "Art. 5(1); 2027, OJ" -> "Art. 5(1)\\; 2027\\, OJ"."""
    s = _CONTROL.sub("", str(value))
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """A content line folded at 75 octets: CRLF and one space before each continuation (3.1)."""
    parts: list[str] = []
    cur: list[str] = []
    n = 0
    for ch in line:
        size = len(ch.encode("utf-8"))
        if cur and n + size > LINE_OCTETS:
            parts.append("".join(cur))
            cur, n = [], 1  # the continuation line's leading space
        cur.append(ch)
        n += size
    parts.append("".join(cur))
    return "\r\n ".join(parts)


def day(d: str) -> str:
    """A DATE value: "2026-12-02" -> "20261202"."""
    return date.fromisoformat(d).strftime("%Y%m%d")


def next_day(d: str) -> str:
    """The DATE value of the day after `d`: a whole-day event's DTEND."""
    return (date.fromisoformat(d) + timedelta(days=1)).strftime("%Y%m%d")


def utc(ts: str) -> str:
    """A UTC DATE-TIME value from an ISO date or timestamp: "2026-10-23" -> "20261023T000000Z"."""
    t = ts if "T" in ts else f"{ts}T00:00:00Z"
    return re.sub(r"[-:]", "", t[:19]) + "Z"


def calendar(head: list[tuple[str, str]], events: list[list[tuple[str, str]]]) -> str:
    """A VCALENDAR of VEVENTs, each given as (name with parameters, value) pairs already escaped; folded, CRLF."""
    lines = ["BEGIN:VCALENDAR", *(f"{k}:{v}" for k, v in head)]
    for ev in events:
        lines += ["BEGIN:VEVENT", *(f"{k}:{v}" for k, v in ev), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(x) + "\r\n" for x in lines)
