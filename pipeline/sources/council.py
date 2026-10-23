"""Council of the European Union: public voting results on legislative acts.

This is the Council of the EU (ministers of the Member States), NOT the European Council.

Official source and route
- The Council's own voting-results web pages (www.consilium.europa.eu) answer scripts with a "Browser
  check" (403), and its open-data datasets ("Council votes on legislative acts", SPARQL endpoint and RDF
  dump on data.consilium.europa.eu) were DISCONTINUED (data.europa.eu record modified 2025-03-10; the
  dump URL and /sparql now return 404). We do not try to get around the bot check.
- For every legislative act it adopts, the General Secretariat of the Council issues a public note
  titled "Voting result" (ST document, codes VOTE/PUBLIC). The Council transmits these documents to the
  Publications Office: they are catalogued in Cellar (created by corporate-body CONSIL, English title
  starting "Voting result", sometimes after a dash or bullet) and served as PDF by the Council's document service
  https://data.consilium.europa.eu/doc/document/<ST-NNNNN-YYYY-INIT>/EN/pdf (reachable by scripts).
- Page 1 of each note is text (interinstitutional file, act title, meeting/written procedure, reference
  documents). The annex is the GSC voting sheet, published only as a raster image: a fixed template
  listing the Member States in protocol order (two columns of 14 slots) with a coloured icon per State:
  green = yes, red = no, yellow = abstain, grey = not participating (empty slot after Sweden since 2020).

How the annex is read (deterministic, fail-closed; no OCR, no guessing)
- The page is rasterised with poppler's `pdftoppm` (system dependency, poppler-utils) and parsed in pure
  Python: icons are located as solid square components of the three icon colours, the two vote columns
  and the row pitch are fitted from them, the grid is anchored on the "Vote" header row, and every one of
  the 28 slots must classify unambiguously (coloured icon or grey glyph) or positions are left empty.
- The voting rule is read from two independent features of the sheet that must agree: the summary
  table shows population percentages only under QMV, and the footnote is a full-width QMV explanation vs
  the short "Abstentions do not prevent unanimity being reached". Otherwise rule = "unknown".
- The "Final result" arrow (green/red) gives the outcome; it is cross-checked against the arithmetic of
  pipeline.analysis.council_qmv on the read positions. On disagreement positions are dropped.
- When positions cannot be taken from a sheet (a slot is unreadable, or a note holds several sheets and we
  cannot tell which one records the vote), the voting rule and final result are still kept if every sheet
  read agrees on them, positions stay empty and `positions_note` says precisely what could not be read.
  The Council does publish every Member State's vote; an empty record is our reading failure, not the
  source's.

What was voted on (`stage`, `vote_on`): the subject lists the act's title followed by the item(s) voted on
("Adoption of the legislative act", "Adoption of the Council's position at first reading and of the
statement of the Council's reasons", "Approval of the joint text", ...). A vote on the Council's first-reading
position does not adopt the act: under the ordinary legislative procedure the act is adopted only when
Parliament approves that position at second reading (Art. 294(7) TFEU).

Opt-outs: the sheet marks Denmark/Ireland (etc.) as "Not participating" (blank weighting, grey icon);
this is kept as "not_participating", distinct from "abstain".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import statistics
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path

from pydantic import Field

from pipeline.analysis.council_qmv import assess
from pipeline.http import Http, HttpError
from pipeline.models.countries import FORMER_MEMBER_STATES, MEMBER_STATES
from pipeline.models.entities import (
    CouncilPosition,
    CouncilVote,
    CouncilVoteOn,
    Model,
    SourceRef,
    SourceStatus,
)
from pipeline.snapshot import fetch_deadline, now_iso, past, read_records, write_records

log = logging.getLogger("pipeline.sources.council")

SOURCE_ID = "council"
MIN_VOTE_DATE = "2019-01-01"
DOC_URL = "https://data.consilium.europa.eu/doc/document/{doc}/EN/pdf"
REGISTER_NOTE = "Council of the EU – Voting result {num}"
RENDER_DPI = 100
MAX_WORKERS = 4
# Bump when parsing changes: every note is then re-processed on the next fetch.
PARSER_VERSION = "2026-10-23.1"

# Protocol order of the GSC voting sheet (Member States by their name in their own language).
LEFT_COLUMN = ["BE", "BG", "CZ", "DK", "DE", "EE", "IE", "GR", "ES", "FR", "HR", "IT", "CY", "LV"]
RIGHT_COLUMN = ["LT", "LU", "HU", "MT", "NL", "AT", "PL", "PT", "RO", "SI", "SK", "FI", "SE"]
UK_LEFT_DATE = "2020-02-01"  # first day without the UK in the Council
MEMBER_STATE_NAMES = {**MEMBER_STATES, **FORMER_MEMBER_STATES}

# Voting-result notes created by the Council, English title starting "Voting result", in some notes after a dash or
# bullet ("- Voting result -", "· Voting result ·", "− Voting result −": ST 9887/25, 10177/25, 6219/25). The query
# selects titles containing the words; VOTING_RESULT_TITLE_RE keeps those that start with them.
SPARQL_VOTING_RESULTS = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?work ?docid ?date ?title ?event ?evdate ?evtype WHERE {
  ?work cdm:work_created_by_agent <http://publications.europa.eu/resource/authority/corporate-body/CONSIL> .
  ?work cdm:work_date_document ?date .
  FILTER(?date >= "%(min_date)s"^^<http://www.w3.org/2001/XMLSchema#date>)
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title .
  FILTER(CONTAINS(LCASE(STR(?title)), "voting result"))
  ?work cdm:work_id_document ?docid . FILTER(STRSTARTS(STR(?docid), "consil:"))
  OPTIONAL {
    ?work cdm:work_part_of_event_legal ?event .
    OPTIONAL { ?event cdm:event_legal_date ?evdate }
    OPTIONAL { ?event cdm:event_legal_type ?evtype }
  }
}
"""

# (a prefix match, as titles can run on without a space: "Voting resultREGULATION …", ST 11790/25)
VOTING_RESULT_TITLE_RE = re.compile(r"^[\W_]*voting\s+result", re.I)
# "Voting result" and the separators after it at the start of a subject or title
_VOTING_RESULT_PREFIX = re.compile(r"^[\W_]*voting\s+results?[\s\-–‒−·•:=]*", re.I)

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


# =============================================================== poppler helpers
def poppler_available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("pdftotext"))


def pdf_text_pages(pdf: bytes) -> list[str]:
    """Text of each page (pdftotext -layout), split on form feeds."""
    with tempfile.TemporaryDirectory(prefix="council-") as d:
        p = Path(d) / "doc.pdf"
        p.write_bytes(pdf)
        out = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"],
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


@dataclass
class Raster:
    w: int
    h: int
    data: bytes  # RGB, row-major

    def px(self, x: int, y: int) -> tuple[int, int, int]:
        j = (y * self.w + x) * 3
        d = self.data
        return d[j], d[j + 1], d[j + 2]


def parse_ppm(buf: bytes) -> Raster:
    if buf[:2] != b"P6":
        raise ValueError("not a binary PPM")
    vals: list[int] = []
    i = 2
    while len(vals) < 3:
        while buf[i : i + 1].isspace():
            i += 1
        if buf[i : i + 1] == b"#":
            while buf[i : i + 1] != b"\n":
                i += 1
            continue
        j = i
        while not buf[j : j + 1].isspace():
            j += 1
        vals.append(int(buf[i:j]))
        i = j
    i += 1
    w, h, maxval = vals
    if maxval != 255:
        raise ValueError("unsupported PPM depth")
    return Raster(w, h, buf[i : i + w * h * 3])


def render_page(pdf: bytes, page: int, dpi: int = RENDER_DPI) -> Raster:
    with tempfile.TemporaryDirectory(prefix="council-") as d:
        p = Path(d) / "doc.pdf"
        p.write_bytes(pdf)
        out = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), str(p)],
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout
    return parse_ppm(out)


# =============================================================== voting-sheet analysis
GREEN, RED, YELLOW = 1, 2, 3
ICON_POSITION: dict[int, CouncilPosition] = {GREEN: "for", RED: "against", YELLOW: "abstain"}


def _icon_class(r: int, g: int, b: int) -> int:
    if g > r + 15 and g > b + 40 and g > 120:
        return GREEN
    if r > 150 and r > g + 80 and r > b + 70:
        return RED
    if r > 190 and g > 150 and r - b > 90 and g - b > 70 and r >= g - 15:
        return YELLOW
    return 0


def _is_text(r: int, g: int, b: int) -> bool:
    """Dark/grey neutral pixel (anti-aliased black or grey text)."""
    return max(r, g, b) < 170 and max(r, g, b) - min(r, g, b) < 45


def _components(img: Raster) -> list[tuple[int, int, int, int, list[int]]]:
    """8-connected components of icon-coloured pixels: (x0, y0, x1, y1, counts per class)."""
    w, h, d = img.w, img.h, img.data
    lab = bytearray(w * h)
    for i in range(w * h):
        j = i * 3
        c = _icon_class(d[j], d[j + 1], d[j + 2])
        if c:
            lab[i] = c
    seen = bytearray(w * h)
    out = []
    for i in range(w * h):
        if not lab[i] or seen[i]:
            continue
        stack = [i]
        seen[i] = 1
        x0 = x1 = i % w
        y0 = y1 = i // w
        cnt = [0, 0, 0, 0]
        while stack:
            k = stack.pop()
            y, x = divmod(k, w)
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            cnt[lab[k]] += 1
            for dy in (-1, 0, 1):
                yy = y + dy
                if not 0 <= yy < h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w:
                        kk = yy * w + xx
                        if lab[kk] and not seen[kk]:
                            seen[kk] = 1
                            stack.append(kk)
        out.append((x0, y0, x1, y1, cnt))
    return out


@dataclass
class Sheet:
    """What was read from one GSC voting sheet (slot classes in protocol order)."""

    left: list[str]  # 14 entries of "for" | "against" | "abstain" | "grey"
    right: list[str]  # 14 entries
    outcome: str  # "adopted" | "not_adopted" | "unknown"
    rule: str  # "qmv" | "unanimity" | "unknown"
    diagnostics: dict[str, object] = field(default_factory=dict)


class SheetError(ValueError):
    """The sheet cannot be read in full. `partial` is set when the template, grid, final result and voting
    rule were recognised but some Member State slots were not: its `left`/`right` hold "" for those slots
    and `unreadable` lists them as (column, row)."""

    def __init__(
        self, message: str, partial: Sheet | None = None, unreadable: list[tuple[str, int]] | None = None
    ):
        super().__init__(message)
        self.partial = partial
        self.unreadable = unreadable or []


def analyse_sheet(img: Raster) -> Sheet:
    """Read a GSC voting sheet image. Raises SheetError if the template is not recognised exactly."""
    px = img.px
    # Single-colour, roughly square components: (xc, yc, width, class, fill ratio). Icons are drawn
    # slightly wider than tall in some templates, flags are ~1.5:1 and multi-coloured.
    squares: list[tuple[float, float, int, int, float]] = []
    for x0, y0, x1, y1, cnt in _components(img):
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        n = sum(cnt)
        k = max((GREEN, RED, YELLOW), key=lambda i: cnt[i])
        if 0.7 <= bh / bw <= 1.35 and cnt[k] >= 0.85 * n and bw >= 8:
            squares.append(((x0 + x1) / 2, (y0 + y1) / 2, bw, k, n / (bw * bh)))
    solid = [c for c in squares if c[2] <= 45 and c[4] >= 0.6]
    if len(solid) < 10:
        raise SheetError(f"too few vote icons ({len(solid)})")
    s = statistics.median(c[2] for c in solid)
    cand = sorted(c[:4] for c in solid if 0.8 * s <= c[2] <= 1.25 * s)
    big = [c[:4] for c in squares if c[2] >= 2 * s and c[4] >= 0.15]

    clusters: list[list[tuple[float, float, int, int]]] = []
    for c in cand:
        if clusters and c[0] - clusters[-1][-1][0] <= s / 2:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    clusters.sort(key=len, reverse=True)
    if len(clusters) < 3 or len(clusters[1]) < 4:
        raise SheetError("vote columns not found")
    grid = sorted(clusters[:2], key=lambda cl: cl[0][0])
    xl = statistics.median(c[0] for c in grid[0])
    xr = statistics.median(c[0] for c in grid[1])
    # Legend of the summary table: yes/no/abstain icons stacked vertically, left of the grid. In the 2019
    # template the "abstain" icon is a yellow ring around a disc (fill ratio about 0.48 at 100 dpi).
    left_of_grid = sorted(
        (c[:4] for c in squares if c[0] < xl - s and 0.6 * s <= c[2] <= 1.4 * s and c[4] >= 0.4),
        key=lambda c: c[1],
    )
    legend = []
    for i in range(len(left_of_grid) - 2):
        a, b, c = left_of_grid[i : i + 3]
        if (
            [a[3], b[3], c[3]] == [GREEN, RED, YELLOW]
            and abs(a[0] - b[0]) <= s / 2
            and abs(b[0] - c[0]) <= s / 2
            and 0.7 * s <= b[1] - a[1] <= 2.5 * s
            and 0.7 * s <= c[1] - b[1] <= 2.5 * s
        ):
            legend = [a, b, c]
            break
    if not legend:
        raise SheetError("legend (yes/no/abstain icons) not found")

    # Row pitch and origin, fitted on all grid icons of both columns.
    ys = sorted(c[1] for cl in grid for c in cl)
    diffs = [b - a for a, b in zip(ys, ys[1:], strict=False) if b - a > 0.5 * s]
    if not diffs:
        raise SheetError("cannot estimate row pitch")
    p = statistics.median([x for x in diffs if x < 1.5 * min(diffs)])
    y0 = ys[0]
    for _ in range(3):
        pairs = [(round((y - y0) / p), y) for y in ys]
        mk = sum(k for k, _ in pairs) / len(pairs)
        my = sum(y for _, y in pairs) / len(pairs)
        var = sum((k - mk) ** 2 for k, _ in pairs)
        if var:
            p = sum((k - mk) * (y - my) for k, y in pairs) / var
        y0 = my - p * mk + p * min(k for k, _ in pairs)
    pairs = [(round((y - y0) / p), y) for y in ys]
    residual = max(abs(y - (y0 + k * p)) for k, y in pairs)
    max_k = max(k for k, _ in pairs)
    if residual > 0.25 * s or not 0.9 * s < p < 2.0 * s or max_k > 13:
        raise SheetError(f"grid fit failed (pitch {p:.1f}, residual {residual:.1f}, rows {max_k + 1})")

    def text_count(xc: float, yc: float, hx: float, hy: float) -> int:
        n = 0
        for y in range(int(yc - hy), int(yc + hy) + 1):
            for x in range(int(xc - hx), int(xc + hx) + 1):
                if 0 <= x < img.w and 0 <= y < img.h and _is_text(*px(x, y)):
                    n += 1
        return n

    # Anchor: the "Vote" header text sits one pitch above slot 0 in both columns.
    shifts = [
        j
        for j in range(0, 14 - max_k)
        if all(text_count(xc, y0 - j * p - p, 0.6 * s, 0.3 * p) >= 3 for xc in (xl, xr))
    ]
    if len(shifts) != 1:
        raise SheetError(f"grid header anchor ambiguous: {shifts}")
    row0 = y0 - shifts[0] * p

    # Final result: one large green/red square to the right of the left vote column.
    finals = [b for b in big if b[0] > xl and b[3] in (GREEN, RED) and b[1] < row0]
    outcome = "unknown"
    if len(finals) == 1:
        outcome = "adopted" if finals[0][3] == GREEN else "not_adopted"

    # Voting rule signal 1: population percentages present in the summary table (QMV only).
    span = xr - xl
    pop_pixels = 0
    for y in range(int(legend[0][1] - 0.4 * s), int(legend[2][1] + 0.4 * s) + 1):
        for x in range(int(xl + 0.08 * span), int(xl + 0.35 * span) + 1):
            if _is_text(*px(x, y)):
                pop_pixels += 1
    # Signal 2: width of the first footnote text line below the grid (a full-width QMV explanation vs
    # "* Abstentions do not prevent unanimity being reached"). Thin rules (separators) are ignored;
    # some published sheets are cropped and have no footnote. A single sparse pixel row inside a line
    # (thin italic glyphs at this resolution) does not end the line.
    xa, xb = int(legend[0][0] - s), int(xr + s)
    y_start = int(row0 + 13.6 * p)
    foot: float | None = None
    run: list[list[int]] = []
    gap = 0
    for y in range(y_start, min(img.h, y_start + int(3 * p))):
        xs = [x for x in range(xa, xb) if _is_text(*px(x, y))]
        if len(xs) >= 2:
            run.append(xs)
            gap = 0
        elif run:
            gap += 1
            if gap == 1:
                continue
            if len(run) >= 4:
                foot = (max(max(r) for r in run) - min(min(r) for r in run)) / (xb - xa)
                break
            run, gap = [], 0
    rule = "unknown"
    if pop_pixels >= 8 and (foot is None or foot >= 0.75):
        rule = "qmv"
    elif pop_pixels == 0 and foot is not None and foot <= 0.6:
        rule = "unanimity"
    diagnostics: dict[str, object] = {
        "icon": s,
        "pitch": round(p, 2),
        "pop_pixels": pop_pixels,
        "footnote_width": foot,
    }

    hw, inner = int(0.4 * s), int(0.3 * s)
    area, inner_area = (2 * hw + 1) ** 2, (2 * inner + 1) ** 2
    unreadable: list[tuple[str, int]] = []
    details: list[str] = []

    def slot(xc: float, k: int, column: str) -> str:
        yc = row0 + k * p
        cnt = [0, 0, 0, 0]
        grey = 0
        for y in range(int(yc - hw), int(yc + hw) + 1):
            for x in range(int(xc - hw), int(xc + hw) + 1):
                r, g, b = px(x, y)
                c = _icon_class(r, g, b)
                cnt[c] += 1
                if not c and abs(y - yc) <= inner and abs(x - xc) <= inner and min(r, g, b) < 222:
                    grey += 1
        best = max((GREEN, RED, YELLOW), key=lambda i: cnt[i])
        others = sum(cnt[1:]) - cnt[best]
        if cnt[best] >= 0.5 * area and others <= 0.1 * cnt[best]:
            return ICON_POSITION[best]
        if sum(cnt[1:]) <= 0.05 * area and grey >= 0.05 * inner_area:
            return "grey"
        unreadable.append((column, k))
        details.append(f"slot ({xc:.0f}, row {k}) unreadable: colour {cnt[1:]}, grey {grey}")
        return ""

    left = [slot(xl, k, "left") for k in range(14)]
    right = [slot(xr, k, "right") for k in range(14)]
    # Every icon detected in a vote column must sit on a slot classified with the same colour.
    for col, cl in ((left, grid[0]), (right, grid[1])):
        for _xc, yc, _w, k in cl:
            row = round((yc - row0) / p)
            if not 0 <= row <= 13 or abs(yc - (row0 + row * p)) > 0.3 * s or col[row] != ICON_POSITION[k]:
                raise SheetError("detected icons inconsistent with the slot grid")
    sheet = Sheet(left=left, right=right, outcome=outcome, rule=rule, diagnostics=diagnostics)
    if unreadable:
        raise SheetError("; ".join(details), partial=sheet, unreadable=unreadable)
    return sheet


def sheet_positions(sheet: Sheet, vote_date: str) -> dict[str, CouncilPosition]:
    """Map the 28 slots to Member States for the membership on `vote_date`."""
    members = LEFT_COLUMN + RIGHT_COLUMN
    slots = sheet.left + sheet.right[:13]
    last = sheet.right[13]
    if vote_date < UK_LEFT_DATE:
        members = members + ["GB"]
        slots = slots + [last]
    elif last != "grey":
        raise SheetError("28th slot filled after the UK's withdrawal")
    return {c: ("not_participating" if v == "grey" else v) for c, v in zip(members, slots, strict=True)}  # type: ignore[misc]


# =============================================================== page-1 (note) parsing
@dataclass
class NoteMeta:
    doc_number: str | None = None  # "10199/24"
    procedure_refs: list[str] = field(default_factory=list)
    subject: str = ""
    title: str | None = None
    step: str | None = None
    meeting: str | None = None  # verbatim, e.g. "4024th meeting of the COUNCIL OF THE EUROPEAN UNION"
    configuration: str | None = None
    meeting_dates: list[str] = field(default_factory=list)  # ISO
    written_procedure_date: str | None = None
    written_procedure: bool = False  # subject says "Outcome of the written procedure completed on ..."
    council_doc: str | None = None
    # Versions declared void by this note, e.g. ["INIT"] from "... INIT should be considered null and void".
    nullified: list[str] = field(default_factory=list)


BULLETS = "•‒–-−=■▪►●·"
# "2021/0106 (COD)"; split procedures are written "2016/0224/A(COD)" (EP format "2016/0224A(COD)").
PROC_RE = re.compile(r"\b((?:19|20)\d{2})/(\d{4})(?:/?([A-Z]))?\s*\(\s*([A-Z]{3})\s*\)")


def _iso(day: int, month: str, year: int) -> str | None:
    m = MONTHS.get(month.lower())
    if not m and len(month) >= 3:  # tolerate typos in the source, e.g. "Decmber" (unique 3-letter prefix)
        hits = {v for k, v in MONTHS.items() if k[:3] == month[:3].lower()}
        m = hits.pop() if len(hits) == 1 else None
    if not m:
        return None
    try:
        return Date(year, m, day).isoformat()
    except ValueError:
        return None


DATE_RE = re.compile(
    r"(\d{1,2})\s*(?:(?:-|–|and|\+)\s*(\d{1,2})\s*)?\s([A-Za-z]{3,})\s+(\d{4})|(\d{1,2})\.(\d{1,2})\.(\d{4})"
)


def parse_dates(text: str) -> list[str]:
    """'21 May 2024' -> [..]; '27-28 October 2025', '3 and 4 December 2018', '7+8 June 2021' -> both days;
    '27.05.2025' -> [..]. Uses the first date expression in `text`."""
    m = DATE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        return []
    if m.group(5):
        try:
            return [Date(int(m.group(7)), int(m.group(6)), int(m.group(5))).isoformat()]
        except ValueError:
            return []
    days = [int(m.group(1))] + ([int(m.group(2))] if m.group(2) else [])
    return [x for x in (_iso(d, m.group(3), int(m.group(4))) for d in days) if x]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_note(page1: str) -> NoteMeta:
    meta = NoteMeta()
    lines = page1.splitlines()
    # Interinstitutional file(s): the lines following "Interinstitutional File(s):" up to "VOTE"/"NOTE".
    for i, ln in enumerate(lines):
        if re.search(r"Interinstitutional\s+Files?\s*:", ln):
            for nxt in lines[i : i + 6]:
                if re.match(r"\s*(NOTE|VOTE)\b", nxt.strip()) or re.search(r"\bVOTE \d+", nxt):
                    break
                for y, n, part, t in PROC_RE.findall(nxt):
                    ref = f"{y}/{n}{part}({t})"
                    if ref not in meta.procedure_refs:
                        meta.procedure_refs.append(ref)
            break
    m = re.search(r"^\s{20,}(\d{3,5}(?:/\d+)?/\d{2})\s*$", page1, re.M)
    if m:
        meta.doc_number = m.group(1)

    # Subject block: from "Subject:" while lines are blank or indented.
    start = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("Subject:")), None)
    if start is not None:
        block = [lines[start].split("Subject:", 1)[1]]
        for ln in lines[start + 1 :]:
            if ln.strip() and _indent(ln) < 10:
                break
            block.append(ln)
        parts = [ln.strip().lstrip(BULLETS).strip() for ln in block if ln.strip()]
        meta.subject = re.sub(r"\s+", " ", " ".join(parts)).strip()
    _parse_subject(meta)

    # Reference documents: first PE-CONS, else first Council document number.
    ref_start = next((i for i, ln in enumerate(lines) if re.match(r"\s*Reference documents?\s*:", ln)), None)
    if ref_start is not None:
        ref_block = []
        for ln in lines[ref_start : ref_start + 8]:
            if re.search(r"approved by|date of decision|statements|^\s*Any ", ln, re.I):
                break
            ref_block.append(ln)
        rb = " ".join(ref_block)
        pc = re.search(r"PE-CONS\s+(\d+)/(\d{2})", rb)
        st = re.search(r"\b(\d{3,5})/(?:\d+/)?(\d{2})\b", rb.split(":", 1)[-1])
        if pc:
            meta.council_doc = f"PE-CONS {pc.group(1)}/{pc.group(2)}"
        elif st:
            meta.council_doc = f"ST {st.group(1)}/{st.group(2)}"
    for m in re.finditer(
        r"ST\s+\d+/\d{2,4}\s+(INIT|REV\s*\d+)\s+should\s+be\s+considered\s+null\s+and\s+void", page1, re.I
    ):
        meta.nullified.append(re.sub(r"\s+", "_", m.group(1).upper()))
    return meta


# What the Council voted on: each item of the subject after the act's title starts with one of these words
# ("Adoption of the legislative act", "Approval of the joint statement", "Agreement in principle", ...).
STEP_RE = re.compile(
    r"\b(?:Adoption|Approval|Non-approval|Consent|Agreement\s+in\s+principle|Request\s+for|Derogation"
    r"|Decision\s+to\s+derogate)\b"
)


def _steps(text: str) -> list[str]:
    """Split the step part of a subject into its items, e.g. "Adoption of the legislative act, and Approval
    of the joint statements" -> ["Adoption of the legislative act", "Approval of the joint statements"]."""
    starts = [m.start() for m in STEP_RE.finditer(text)]
    out: list[str] = []
    for a, b in zip(starts, starts[1:] + [len(text)], strict=False):
        item = re.sub(r"[\s,;]+(?:and)?$", "", text[a:b].strip(" -–‒=■,;")).strip(" -–‒=■,;")
        if item:
            out.append(item)
    return out


def _parse_subject(meta: NoteMeta) -> None:
    s = _VOTING_RESULT_PREFIX.sub("", meta.subject)
    meeting = re.search(
        r"(\d{3,5}\s*(?:st|nd|rd|th)\s+meeting\s+of\s+the\s+COUNCIL\s+OF\s+THE\s+EUROPEAN\s+UNION)(.*)$",
        s,
        re.I,
    )
    written = re.search(r"Outcome\s+of\s+the\s+written\s+procedure\s+completed\s+on\s+(.+?)\s*$", s, re.I)
    # "Outcome of the written procedure initiated by CM 2163/21": no completion date in the note (ST 7108/21)
    initiated = None if written else re.search(
        r"Outcome\s+of\s+the\s+written\s+procedure\s+initiated\s+by\s+CM\s*\d+/\d+", s, re.I
    )
    # Items listed after the written-procedure line, e.g. "... completed on 16 March 2021 = Adoption of the
    # Council's position at first reading and of the statement of the Council's reasons".
    after_written: list[str] = []
    if written:
        d = DATE_RE.search(written.group(1))
        if d:
            after_written = _steps(written.group(1)[d.end() :])
    elif initiated:
        after_written = _steps(s[initiated.end() :])
    cut = None
    if meeting:
        meta.meeting = re.sub(
            r"\s+", " ", meeting.group(1)
        )  # verbatim, e.g. "4024th meeting of the COUNCIL ..."
        rest = meeting.group(2).strip()
        # "(Configuration), 21 May 2024, Brussels" / "(Configuration), Brussels, 27.05.2025" /
        # "Configuration Council 22 and 23 May 2023, Brussels"
        date = DATE_RE.search(rest)
        if date:
            meta.meeting_dates = parse_dates(date.group(0))
        if rest.startswith("("):
            depth = 0
            for i, ch in enumerate(rest):
                depth += {"(": 1, ")": -1}.get(ch, 0)
                if depth == 0:
                    meta.configuration = rest[1:i].strip() or None
                    break
            else:  # unbalanced parentheses in the source: keep the text up to the date, verbatim
                end = date.start() if date else len(rest)
                meta.configuration = rest[1:end].strip(" ,") or None
        elif date:
            meta.configuration = rest[: date.start()].strip(" ,") or None
        cut = meeting.start()
    if written:
        meta.written_procedure = True
        d = parse_dates(written.group(1))
        meta.written_procedure_date = d[0] if d else None
        cut = written.start() if cut is None else min(cut, written.start())
    elif initiated:
        meta.written_procedure = True
        cut = initiated.start() if cut is None else min(cut, initiated.start())
    head = s[:cut].strip(" -–‒=■") if cut is not None else s
    # The title ends where the first item voted on begins; every later item is part of the step.
    first = STEP_RE.search(head)
    steps = after_written
    if first and first.start() > 0:
        meta.title = head[: first.start()].strip(" -–‒=■,")
        steps = _steps(head[first.start() :]) + after_written
    else:
        meta.title = head or None
    meta.step = "; ".join(steps) or None


STATEMENTS_HEADING_RE = re.compile(
    r"(?:Draft\s+)?(?:Joint\s+)?(?:Statements?|Declarations?|Explanations?\s+of\s+votes?)", re.I
)
# The first line of a statement's heading: "Statement by …", "Joint declaration …", "Explanation of vote by …",
# "Explanation by Hungary of its vote", "Draft Joint Statement by the Council, …" (ST 14020/20)
STATEMENT_HEAD_RE = re.compile(
    r"^(?:Draft\s+)?(?:Joint\s+)?(?:Statements?|Declarations?|Explanations?\s+of\s+votes?|Explanations?\s+by)\b",
    re.I,
)


def parse_statements(pages: list[str]) -> list[str]:
    """Titles of statements / declarations / explanations of vote printed in the note's annexes, in order. A title
    printed again for another text ("Statement by the Commission" twice, ST 14020/20) is numbered: "… (2)"."""
    out: list[str] = []
    seen: dict[str, int] = {}
    head = STATEMENT_HEAD_RE
    for page in pages[1:]:
        lines = page.splitlines()
        i = 0
        while i < len(lines):
            ln = lines[i]
            if _indent(ln) >= 3 and head.match(ln.strip()) and len(ln.strip()) < 200:
                title = [ln.strip()]
                j = i + 1
                while j < len(lines) and lines[j].strip() and _indent(lines[j]) >= 3 and len(title) < 4:
                    if head.match(lines[j].strip()):
                        break
                    title.append(lines[j].strip())
                    j += 1
                t = re.sub(r"\s+", " ", " ".join(title))
                # the annex heading alone ("STATEMENTS" above "Statement by Spain", ST 7085/20) is not a statement
                if not STATEMENTS_HEADING_RE.fullmatch(t):
                    seen[t] = seen.get(t, 0) + 1
                    out.append(t if seen[t] == 1 else f"{t} ({seen[t]})")
                i = j
                continue
            i += 1
    return out


# =============================================================== assembly
@dataclass
class DocVersion:
    work: str
    doc_id: str  # "ST-10199-2024-INIT"
    base: str  # "ST-10199-2024"
    suffix: str  # "INIT" | "REV_1" | "COR_1"
    date: str
    title: str
    events: list[str] = field(default_factory=list)  # Council adoption-event dates found in Cellar (ISO)


def _versions_from_rows(rows: list[dict[str, str]]) -> dict[str, list[DocVersion]]:
    by_work: dict[str, DocVersion] = {}
    for r in rows:
        m = re.match(r"consil:(ST)_(\d+)_(\d{4})_(INIT|REV_\d+|COR_\d+)$", r["docid"])
        if not m or not VOTING_RESULT_TITLE_RE.match(r.get("title", "")):
            continue
        v = by_work.get(r["work"])
        if v is None:
            suffix = m.group(4)
            v = DocVersion(
                work=r["work"],
                doc_id=f"ST-{m.group(2)}-{m.group(3)}-{suffix.replace('_', '-')}",
                base=f"ST-{m.group(2)}-{m.group(3)}",
                suffix=suffix,
                date=r["date"][:10],
                title=re.sub(r"\s+", " ", r["title"]).strip(),
            )
            by_work[r["work"]] = v
        d = _council_event_date(r)
        if d and d not in v.events:
            v.events.append(d)
    groups: dict[str, list[DocVersion]] = {}
    for v in by_work.values():
        groups.setdefault(v.base, []).append(v)
    for vs in groups.values():
        vs.sort(key=lambda v: (v.date, _suffix_rank(v.suffix)))
    return groups


def _suffix_rank(s: str) -> tuple[int, int]:
    kind, _, n = s.partition("_")
    return ({"INIT": 0, "REV": 1, "COR": 2}.get(kind, 3), int(n or 0))


def _council_event_date(row: dict[str, str]) -> str | None:
    """Date of the Council procedure event a note is attached to (Cellar event or procedure-event URI)."""
    ev = row.get("event", "")
    if row.get("evdate") and row.get("evtype", "").endswith("byCONSIL"):
        return row["evdate"][:10]
    m = re.search(r"/procedure-event/[^.]+\.(\d{4}-\d{2}-\d{2})_[A-Za-z0-9_]*byCONSIL$", ev)
    return m.group(1) if m else None


def _event_date(event_dates: list[str], candidates: list[str]) -> str | None:
    """The single Council event date that falls on one of the meeting days, if any."""
    dates = {d for d in event_dates if d in candidates}
    return dates.pop() if len(dates) == 1 else None


@dataclass
class Parsed:
    version: DocVersion
    pages: list[str]
    meta: NoteMeta
    sheet: Sheet | None  # the note's voting sheet, when exactly one was read in full
    sheet_error: str | None
    # Every sheet read in full, by page number (more than one: several votes recorded in one note).
    sheets: list[tuple[int, Sheet]] = field(default_factory=list)
    # Sheets whose grid, final result and voting rule were read but some Member State slots were not.
    partial: list[tuple[int, SheetError]] = field(default_factory=list)
    # Pages that looked like a voting sheet but whose layout was not recognised.
    unrecognised: list[int] = field(default_factory=list)


def parse_document(v: DocVersion, pdf: bytes) -> Parsed:
    pages = pdf_text_pages(pdf)
    meta = parse_note(pages[0] if pages else "")
    sheets: list[tuple[int, Sheet]] = []
    partial: list[tuple[int, SheetError]] = []
    unrecognised: list[int] = []
    errors: list[str] = []
    for i, text in enumerate(pages[1:6], start=2):
        body = re.sub(r"\s+", " ", text).strip()
        if len(body) > 300:  # a text page (statements etc.), not the image annex
            continue
        try:
            sheets.append((i, analyse_sheet(render_page(pdf, i))))
        except SheetError as e:
            errors.append(f"p{i}: {e}")
            if e.partial is not None:
                partial.append((i, e))
            else:
                unrecognised.append(i)
    sheet = None
    err = "; ".join(errors) or ("no voting sheet" if not sheets else None)
    if len(sheets) == 1:
        sheet, err = sheets[0][1], None
    elif len(sheets) > 1:
        err = "several voting sheets in one note"
    return Parsed(v, pages, meta, sheet, err, sheets, partial, unrecognised)


def slot_country(column: str, row: int, vote_date: str) -> str | None:
    """Member State of a voting-sheet slot on `vote_date` (None: the empty 28th slot after the UK left)."""
    if column == "left":
        return LEFT_COLUMN[row]
    if row < len(RIGHT_COLUMN):
        return RIGHT_COLUMN[row]
    return "GB" if vote_date < UK_LEFT_DATE else None


def _names(codes: list[str]) -> str:
    names = [MEMBER_STATE_NAMES.get(c, c) for c in codes]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _pages(nums: list[int]) -> str:
    return ("page " if len(nums) == 1 else "pages ") + _names([str(n) for n in nums])


def _sheet_fallback(p: Parsed, vote_date: str) -> tuple[str, str, str]:
    """Voting rule, outcome and a plain-language reason for missing positions when a note has no single
    fully read voting sheet. Rule and outcome are kept only where every sheet that could be read agrees on
    them (this vote is one of them); individual positions are never taken from such notes."""
    candidates = [s for _, s in p.sheets] + [e.partial for _, e in p.partial if e.partial is not None]
    rules = {s.rule for s in candidates}
    outcomes = {s.outcome for s in candidates}
    rule = rules.pop() if len(rules) == 1 else "unknown"
    outcome = outcomes.pop() if len(outcomes) == 1 else "unknown"
    if p.unrecognised:  # an unread sheet could disagree with the others
        rule, outcome = "unknown", "unknown"
    shown = "so no individual positions are shown for this vote."
    if len(p.sheets) > 1:
        pages = _pages([n for n, _ in p.sheets])
        note = (
            f"The voting-result document contains {len(p.sheets)} voting sheets ({pages}) and we could not "
            f"establish automatically which of them records this vote, {shown}"
        )
    elif p.partial:
        page, err = p.partial[0]
        states = [c for col, row in err.unreadable if (c := slot_country(col, row, vote_date))]
        if len(states) == 1:
            what = f"{_names(states)}'s vote"
        else:
            what = f"the votes of {_names(states)}" if states else "every Member State's vote"
        note = f"We could not read {what} from the published voting sheet ({_pages([page])}), {shown}"
    elif p.unrecognised:
        note = (
            f"We could not read the published voting sheet ({_pages(p.unrecognised)}) automatically because "
            f"its layout was not recognised, {shown}"
        )
    else:
        note = f"We found no voting sheet in the published voting-result document, {shown}"
    return rule, outcome, note


def _merge_meta(metas: list[NoteMeta]) -> NoteMeta:
    """Field by field, the latest version (REV/COR) that states a value wins; corrigenda often restate
    only part of the note (e.g. a corrected interinstitutional file number or subject)."""
    out = NoteMeta()
    for name in NoteMeta.__dataclass_fields__:
        for m in reversed(metas):
            value = getattr(m, name)
            if value:
                setattr(out, name, value)
                break
    return out


def build_vote(parsed: list[Parsed], retrieved_at: str) -> tuple[CouncilVote | None, str | None]:
    """Combine the versions of one note (INIT/REV/COR) into a CouncilVote. Returns (vote, problem)."""
    nullified = {s for p in parsed for s in p.meta.nullified}
    valid = [p for p in parsed if p.version.suffix not in nullified]
    if not valid:
        return None, "all versions declared null and void"
    meta_src = valid[-1]
    meta = _merge_meta([p.meta for p in valid])
    with_sheet = [p for p in valid if p.sheet is not None]
    sheet_src = with_sheet[-1] if with_sheet else None

    if meta.written_procedure_date:
        vote_date = meta.written_procedure_date
    elif len(meta.meeting_dates) == 1:
        vote_date = meta.meeting_dates[0]
    elif meta.meeting_dates:
        events = [e for p in valid for e in p.version.events]
        vote_date = _event_date(events, meta.meeting_dates) or meta.meeting_dates[0]
    elif meta.written_procedure and len(ev := {e for p in valid for e in p.version.events if e <= p.version.date}) == 1:
        # a written procedure the note does not date: the Council event Cellar attaches the note to (ST 7108/21:
        # ADP_R1_POS_byCONSIL 16 March 2021, note of 17 March)
        vote_date = ev.pop()
    else:
        vote_date = valid[0].version.date
    if vote_date < MIN_VOTE_DATE:
        return None, None

    problem = None
    positions: dict[str, CouncilPosition] = {}
    positions_note: str | None = None
    rule, outcome = "unknown", "unknown"
    fallback_src: Parsed | None = None
    if sheet_src is not None and sheet_src.sheet is not None:
        sheet = sheet_src.sheet
        rule, outcome = sheet.rule, sheet.outcome
        try:
            positions = sheet_positions(sheet, vote_date)
        except SheetError as e:
            problem = f"{sheet_src.version.doc_id}: {e}"
            positions_note = (
                "The layout of the published voting sheet does not match the Council's membership on that date, "
                "so no individual positions are shown for this vote."
            )
        if positions and rule != "unknown" and outcome != "unknown":
            year = int(vote_date[:4])
            checks = [assess(positions, rule, ocp, year=year) for ocp in (True, False)]
            verdicts = {c.adopted_by_rule for c in checks if c is not None}
            if None not in verdicts and (outcome == "adopted") not in verdicts:
                problem = f"{sheet_src.version.doc_id}: read positions contradict the published final result"
                positions = {}
                positions_note = (
                    "The positions we read from the published voting sheet do not agree with its final result, "
                    "so no individual positions are shown for this vote."
                )
    else:
        problem = (
            "; ".join(f"{p.version.doc_id}: {p.sheet_error}" for p in valid if p.sheet_error) or "no sheet"
        )
        with_sheets = [p for p in valid if p.sheets or p.partial or p.unrecognised]
        fallback_src = with_sheets[-1] if with_sheets else None
        rule, outcome, positions_note = _sheet_fallback(fallback_src or valid[-1], vote_date)

    src = sheet_src or fallback_src or meta_src
    # the statements printed in the latest version that prints any (a corrigendum may reprint only page 1)
    statements: list[str] = next((st for p in reversed(valid) if (st := parse_statements(p.pages))), [])
    title = meta.title or _VOTING_RESULT_PREFIX.sub("", src.version.title)
    vote = CouncilVote(
        id=src.version.base,
        date=vote_date,
        title=title,
        procedure_refs=meta.procedure_refs,
        council_doc=meta.council_doc,
        configuration=None if meta.written_procedure else meta.configuration,
        stage=meta.step,
        vote_on=vote_subject(title, meta.step),
        meeting=None if meta.written_procedure else meta.meeting,
        written_procedure=True if meta.written_procedure else (False if meta.meeting else None),
        voting_rule=rule,  # type: ignore[arg-type]
        act_type=_act_type(title),
        outcome=outcome,  # type: ignore[arg-type]
        positions=positions,
        positions_note=positions_note if not positions else None,
        statements=statements,
        source=SourceRef(
            institution="Council",
            url=DOC_URL.format(doc=src.version.doc_id),
            label=REGISTER_NOTE.format(num=st_number(src.version)),
            identifier=st_number(src.version),
            retrieved_at=retrieved_at,
            published=src.version.date,
        ),
    )
    return vote, problem


def st_number(v: DocVersion) -> str:
    """Council register number of a version: "ST 10199/24", "ST 14522/25 REV 1", "ST 15212/24 COR 1"."""
    _, num, year, *rest = v.doc_id.split("-")
    suffix = " ".join(rest)
    return f"ST {num}/{year[2:]}" + ("" if suffix == "INIT" else f" {suffix}")


COUNCIL_FIRST_READING_POSITION_RE = re.compile(
    r"Adoption\s+of\s+(?:the\s+|a\s+)?(?:Council(?:'s|’s)?\s+(?:first[\s-]+reading\s+)?position|position\s+of\s+the\s+Council)"
    r".*\bfirst[\s-]+reading\b|Adoption\s+of\s+the\s+Council(?:'s|’s)?\s+first[\s-]+reading\s+position",
    re.I,
)
ACT_ADOPTION_RE = re.compile(r"Adoption\s+of\s+(?:the\s+|a\s+)?legi\w*\s+act\b", re.I)


def vote_subject(title: str | None, step: str | None) -> CouncilVoteOn | None:
    """What the Council voted on, from the note's subject (title and the items listed after it).

    "first_reading_position": adoption of the Council's position at first reading (ordinary legislative
    procedure, Art. 294(5) TFEU), with or without its statement of reasons; the act is NOT adopted by this
    vote. "act": adoption of the act itself ("Adoption of the legislative act", or a bare "Adoption" of a
    regulation, directive or decision). "other": any other item (budget procedure, approval of a joint text,
    statement or letter, agreement in principle, consent, ...). None: the subject names no item.
    """
    t = title or ""
    items = [i.strip() for i in (step or "").split(";") if i.strip()]
    if re.match(r"\s*Position\s+of\s+the\s+Council\s+at\s+first\s+reading\b", t, re.I) or any(
        COUNCIL_FIRST_READING_POSITION_RE.match(i) for i in items
    ):
        return "first_reading_position"
    if not items:
        return None
    act = _act_type(t)
    if act is None and re.search(r"\bbudget\b", t, re.I):
        return "other"  # annual / amending budget procedure (Art. 314 TFEU), not an act's adoption
    if any(ACT_ADOPTION_RE.match(i) for i in items):
        return "act"
    if "Adoption" in items and act in ("regulation", "directive", "decision"):
        return "act"
    return "other"


def _act_type(title: str) -> str | None:
    t = title.upper()
    if t.startswith("POSITION OF THE COUNCIL"):
        return "council_position"
    for kw in ("REGULATION", "DIRECTIVE", "DECISION"):
        m = re.search(rf"\b{kw}\b", t)
        if m and m.start() < 40:
            return kw.lower()
    return None


# =============================================================== fetch
def list_versions(http: Http) -> dict[str, list[DocVersion]]:
    # Include notes dated slightly before MIN_VOTE_DATE (corrigenda refer back); filtered by vote date later.
    rows = http.sparql(SPARQL_VOTING_RESULTS % {"min_date": "2018-12-01"}, use_cache=False)
    return _versions_from_rows(rows)


class CouncilNoteState(Model):
    """Incremental-fetch index (data/snapshot/council/notes.json): what a note's Cellar metadata looked
    like when it was last processed, and which vote record it produced."""

    id: str  # base ST number, e.g. "ST-10199-2024"
    fingerprint: str  # sha256 of the parser version + every version's ST id, date, title, Council event dates
    versions: list[str] = Field(default_factory=list)  # ST ids of all versions (INIT/REV/COR) at that time
    vote_id: str | None = None  # None: no record (vote before MIN_VOTE_DATE, or no version available)
    problem: str | None = None


DEFERRED_FINGERPRINT = "deferred"  # a note left for the next run (time budget); never equals a real one


def note_fingerprint(versions: list[DocVersion]) -> str:
    payload = {
        "parser": PARSER_VERSION,
        "versions": [[v.doc_id, v.date, v.title, sorted(v.events)] for v in versions],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class _Result:
    base: str
    vote: CouncilVote | None
    problem: str | None
    state: CouncilNoteState | None  # None: transient failure, retry next run
    reused: bool = False
    deferred: bool = False  # not processed: time budget reached (previous record kept, retried next run)


def process_note(
    http: Http,
    base: str,
    versions: list[DocVersion],
    prev: CouncilNoteState | None,
    prev_vote: CouncilVote | None,
    retrieved: str,
    *,
    force: bool = False,
    deadline: float | None = None,
) -> _Result:
    """Read one note (all its versions) unless its Cellar metadata and the parser are unchanged since it was
    last processed (`force` re-reads it regardless). After `deadline` (monotonic) no download is started: the
    note keeps its previous record and state entry, marked DEFERRED_FINGERPRINT so the next run reads it."""
    fp = note_fingerprint(versions)
    if not force and prev and prev.fingerprint == fp and (prev.vote_id is None or prev_vote is not None):
        return _Result(base, prev_vote, prev.problem, prev, reused=True)
    if past(deadline):
        # Keep the note's previous entry (so its vote stays linked) with a fingerprint that forces a re-read.
        keep = prev.model_copy(update={"fingerprint": DEFERRED_FINGERPRINT}) if prev else None
        return _Result(base, prev_vote, None, keep, deferred=True)
    parsed = []
    for v in versions:
        if past(deadline):
            keep = prev.model_copy(update={"fingerprint": DEFERRED_FINGERPRINT}) if prev else None
            return _Result(base, prev_vote, None, keep, deferred=True)
        try:
            pdf = http.get(DOC_URL.format(doc=v.doc_id))
        except HttpError as e:
            if e.status == 404:  # withdrawn version (e.g. declared null and void)
                log.warning("council: %s not in the register (404)", v.doc_id)
                continue
            # Transient: keep the previous record (if any) and retry next run.
            return _Result(base, prev_vote, f"download failed ({e.status}); previous record kept", None)
        try:
            parsed.append(parse_document(v, pdf))
        except (subprocess.SubprocessError, ValueError) as e:
            log.warning("council: %s unreadable: %s", v.doc_id, e)
    state = CouncilNoteState(id=base, fingerprint=fp, versions=[v.doc_id for v in versions])
    if not parsed:
        state.problem = "no version could be downloaded/read"
        return _Result(base, None, state.problem, state)
    try:
        vote, problem = build_vote(parsed, retrieved)
    except ValueError as e:  # pydantic validation etc.
        state.problem = f"invalid record: {e}"
        return _Result(base, None, state.problem, state)
    state.vote_id, state.problem = (vote.id if vote else None), problem
    return _Result(base, vote, problem, state)


def reprocess(http: Http, bases: list[str]) -> dict[str, str | None]:
    """Re-read only the given notes now and replace their records in the snapshot (votes.json, notes.json);
    every other note is left exactly as it is. For targeted corrections after a parser change, without a
    full fetch. Notes that fail transiently keep their previous records. Returns {note: problem}."""
    groups = list_versions(http)
    unknown = [b for b in bases if b not in groups]
    if unknown:
        raise ValueError(f"not in the Cellar listing: {', '.join(unknown)}")
    states = {st.id: st for st in read_records(SOURCE_ID, "notes", CouncilNoteState)}
    votes = {v.id: v for v in read_records(SOURCE_ID, "votes", CouncilVote)}
    retrieved = now_iso()

    def work(base: str) -> _Result:
        prev = states.get(base)
        prev_vote = votes.get(prev.vote_id) if prev and prev.vote_id else None
        return process_note(http, base, groups[base], prev, prev_vote, retrieved, force=True)

    out: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(work, bases))
    for r in results:
        out[r.base] = r.problem
        if r.state is None:  # transient failure: keep the previous records
            continue
        prev = states.get(r.base)
        if prev and prev.vote_id:
            votes.pop(prev.vote_id, None)
        if r.vote is not None:
            votes[r.vote.id] = r.vote
        states[r.base] = r.state
    write_records(SOURCE_ID, "votes", votes.values(), key=lambda r: (r.date, r.id))  # type: ignore[attr-defined]
    write_records(SOURCE_ID, "notes", states.values(), key=lambda r: r.id)  # type: ignore[attr-defined]
    return out


def fetch(http: Http) -> SourceStatus:
    attempted = now_iso()
    if not poppler_available():
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note="poppler-utils (pdftoppm, pdftotext) not installed; needed to read the Council voting-result PDFs.",
        )
    groups = list_versions(http)
    bases = sorted(groups)
    prev_states = {st.id: st for st in read_records(SOURCE_ID, "notes", CouncilNoteState)}
    prev_votes = {v.id: v for v in read_records(SOURCE_ID, "votes", CouncilVote)}
    if prev_states and len(bases) < 0.9 * len(prev_states):
        # A truncated Cellar answer must not shrink the snapshot.
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note=f"Cellar listed only {len(bases)} voting-result notes (previously {len(prev_states)}); kept snapshot.",
        )
    retrieved = now_iso()
    deadline = fetch_deadline()

    def work(base: str) -> _Result:
        prev = prev_states.get(base)
        prev_vote = prev_votes.get(prev.vote_id) if prev and prev.vote_id else None
        return process_note(http, base, groups[base], prev, prev_vote, retrieved, deadline=deadline)

    votes: list[CouncilVote] = []
    states: list[CouncilNoteState] = []
    problems: list[str] = []
    reused = transient = deferred = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, r in enumerate(ex.map(work, bases), start=1):
            if r.vote is not None:
                votes.append(r.vote)
            if r.state is not None:
                states.append(r.state)
            elif not r.deferred:
                transient += 1
            deferred += r.deferred
            reused += r.reused
            if r.problem:
                problems.append(f"{r.base}: {r.problem}")
                if not r.reused:
                    log.info("council: %s: %s", r.base, r.problem)
            if i % 100 == 0:
                log.info("council: %d/%d notes processed (%d unchanged, reused)", i, len(bases), reused)

    if not votes:
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note=f"No voting results could be read ({len(bases)} notes listed in Cellar). "
            + "; ".join(problems[:5]),
        )
    write_records(SOURCE_ID, "votes", votes, key=lambda r: (r.date, r.id))  # type: ignore[attr-defined]
    write_records(SOURCE_ID, "notes", states, key=lambda r: r.id)  # type: ignore[attr-defined]
    with_positions = sum(1 for v in votes if v.positions)
    by_rule: dict[str, int] = {}
    for v in votes:
        by_rule[v.voting_rule] = by_rule.get(v.voting_rule, 0) + 1
    note = (
        f"{len(votes)} Council voting results since {MIN_VOTE_DATE} from GSC 'Voting result' notes "
        f"(Cellar list + data.consilium.europa.eu PDFs); {with_positions} with per-country positions read from "
        f"the annexed voting sheet; rules {by_rule}. {len(bases) - reused} notes (re)processed, {reused} unchanged "
        f"and reused; {transient} transient download failures. {len(problems)} notes with problems"
        + (f", e.g. {'; '.join(problems[:3])}" if problems else "")
        + (
            f". {deferred} notes not processed (time budget reached; previous records kept, resumes next run)"
            if deferred
            else ""
        )
        + ". The Council's open-data datasets were discontinued (2025) and its web voting-results pages "
        "are bot-protected."
    )
    return SourceStatus(
        source=SOURCE_ID,
        status="ok" if with_positions >= 0.95 * len(votes) and not transient and not deferred else "partial",
        fetched_at=retrieved,
        attempted_at=attempted,
        records={"votes": len(votes), "votes_with_positions": with_positions},
        note=note[:1500],
    )
