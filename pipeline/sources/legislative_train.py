"""European Parliament Legislative Train Schedule -> data/snapshot/train/files.json (list[TrainFile]).

Site: https://www.europarl.europa.eu/legislative-train/ (server-rendered HTML, no API).

Structure (verified 2026-10-22):
- Schedule index per Commission term: ``schedule?pov=EC_PRIORITIES&commission=<term>&reload=false``
  (the fragment the site's own "Commission" selector loads). It lists the "trains" (themes, i.e.
  the Commission's political priorities) with a count of files per status.
- Theme page ``theme-<slug>``: lists every file ("carriage") of that theme as a link
  ``/legislative-train/theme-<slug>/file-<file-slug>``.
- File page: sidebar "Metadata" with ``Status:`` (a badge), ``Procedure:`` (procedure reference,
  plain text; Parliament legislative-initiative files have ``Adopted INL report:`` instead),
  optionally ``Blocking institutions:`` (one or more badges, e.g. "COUNCIL"), and
  "Information updated as of DD/MM/YYYY." above the text.

A file carried over from one Commission term to the next is listed under a theme of each term,
with the same file slug, status and text (only the "In <theme>" heading differs). Files are
therefore de-duplicated by file slug; the most recent term's theme is kept.

The status is stored EXACTLY as published on the file page. The Train's own glossary ("Status"
tab on the schedule page) defines seven statuses, published on file pages as the values in
STATUS_VOCABULARY below. Its definition of "Blocked": no progress over at least the previous nine
months - a co-legislator has not formally started work more than nine months after tabling, or no
activity has been recorded in Council or Parliament for at least nine months; an announced
initiative not tabled more than nine months after its announced date is also "Blocked".

Crawl policy: only schedule index fragments, theme pages and file pages; sequential requests
through the shared, throttled, caching ``Http`` client.

The site's bot filter answers HTTP 202 (an empty JavaScript challenge) to user agents that are not
in the common "product/version" browser or tool form, including the pipeline's default one. We
therefore send the same honest bot identification in the conventional crawler form
``Mozilla/5.0 (compatible; <bot>/<version>; +<info url>)``.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin

import lxml.html

from pipeline.http import USER_AGENT, Http, HttpError
from pipeline.models.entities import SourceRef, SourceStatus, TrainFile
from pipeline.snapshot import now_iso, write_records

log = logging.getLogger("pipeline.sources.legislative_train")

SOURCE_ID = "train"
BASE = "https://www.europarl.europa.eu/legislative-train/"
# Commission terms offered by the schedule's "Commission" selector, most recent first.
COMMISSION_TERMS: tuple[str, ...] = ("2024-29", "2019-24", "2014-19")

# Status values exactly as they appear in the file-page "Status:" badge, as observed on all
# 1,492 file pages on 2026-10-22; the schedule glossary defines the same seven statuses.
STATUS_VOCABULARY: frozenset[str] = frozenset(
    {
        "Legislative initiatives",
        "Announced",
        "Tabled",
        "Blocked",
        "Close to adoption",
        "Adopted / Completed",
        "Withdrawn",
    }
)

# Column headers of the schedule's status-count table, in table order.
SCHEDULE_COLUMNS: tuple[str, ...] = (
    "Legislative initiatives",
    "Announced",
    "Tabled",
    "Blocked",
    "Close to adoption",
    "Adopted / Completed",
    "Withdrawn",
)

# Procedure references as printed on file pages, e.g. "2021/0106(COD)", "2020/2012(INL)"; a few
# pages print a two-letter type ("2023/2670(NA)"), kept as published.
_PROC_RE = re.compile(r"\b(\d{4})/(\d{4}[A-Z]?)\(([A-Z]{2,3})\)")
# Metadata fields that carry procedure references.
PROCEDURE_FIELDS: tuple[str, ...] = ("Procedure", "Adopted INL report")
_UPDATED_RE = re.compile(r"Information updated as of\s+(\d{1,2})/(\d{1,2})/(\d{4})")
_IN_THEME_RE = re.compile(r"^\s*In\s+[“\"](.*)[”\"]\s*$", re.S)
_FILE_HREF_RE = re.compile(r"^/legislative-train/(theme-[^/]+)/file-(.+)$")


def train_user_agent(base: str = USER_AGENT) -> str:
    """Pipeline identification in the conventional crawler form accepted by the site."""
    product = base.split(" ", 1)[0]
    m = re.search(r"\+(https?://[^\s)]+)", base)
    info = f"; +{m.group(1)}" if m else ""
    return f"Mozilla/5.0 (compatible; {product}{info})"


HEADERS = {"User-Agent": train_user_agent(), "Accept": "text/html,application/xhtml+xml"}


# --------------------------------------------------------------------------- parsing (pure)


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip()


@dataclass
class ThemeRow:
    slug: str  # "theme-a-european-green-deal"
    title: str  # as given in the schedule link title (upper case on the site)
    counts: dict[str, int] = field(default_factory=dict)  # schedule column -> number of files


def parse_schedule(html: str) -> list[ThemeRow]:
    """Parse a schedule fragment: themes and their per-status file counts.

    Sub-theme rows (2014-19 term) are separate rows with their own theme link.
    """
    doc = lxml.html.fromstring(html)
    rows: list[ThemeRow] = []
    seen: set[str] = set()
    for tr in doc.xpath("//table[@id='carriageTable']//tr[.//a[starts-with(@href,'theme-')]]"):
        a = tr.xpath(".//a[starts-with(@href,'theme-')]")[0]
        slug = a.get("href").strip()
        if slug in seen:
            continue
        seen.add(slug)
        nums = [
            int(_text(td)) for td in tr.xpath("./td[contains(@class,'tableValue')]") if _text(td).isdigit()
        ]
        counts = dict(zip(SCHEDULE_COLUMNS, nums, strict=False)) if len(nums) == len(SCHEDULE_COLUMNS) else {}
        rows.append(ThemeRow(slug=slug, title=(a.get("title") or _text(a)).strip(), counts=counts))
    return rows


def parse_theme(html: str) -> list[tuple[str, str]]:
    """Return the (absolute file URL, file title) pairs listed on a theme page, in page order."""
    doc = lxml.html.fromstring(html)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in doc.xpath("//a[contains(@href,'/file-')]"):
        href = (a.get("href") or "").strip()
        if not _FILE_HREF_RE.match(href) or href in seen:
            continue
        seen.add(href)
        out.append((urljoin(BASE, href), (a.get("title") or _text(a)).strip()))
    return out


def file_slug(url: str) -> str:
    return url.rsplit("/file-", 1)[-1]


@dataclass
class FilePage:
    title: str
    status: str | None
    procedure_refs: list[str]
    theme: str | None
    last_updated: str | None
    blocking_institution: str | None = None


def parse_file_page(html: str) -> FilePage:
    doc = lxml.html.fromstring(html)

    title = ""
    h2 = doc.xpath("//div[contains(@class,'flex-column')]/h2[contains(@class,'erpl_title-h2')]")
    if h2:
        title = _text(h2[0])
    if not title:
        og = doc.xpath("//meta[@property='og:title']/@content")
        if og:
            title = og[0].split(" | Legislative Train")[0].strip()

    theme = None
    for p in doc.xpath("//p[contains(@class,'erpl_title-h4') and contains(@class,'font-weight-light')]"):
        m = _IN_THEME_RE.match(_text(p))
        if m:
            theme = m.group(1).strip()
            break

    meta_items = doc.xpath("//h2[normalize-space()='Metadata']/following-sibling::ul[1]/li") or doc.xpath(
        "//ul/li[contains(@class,'d-flex')]"
    )

    def meta_value(label: str):
        for li in meta_items:
            ps = li.xpath("./p")
            if ps and _text(ps[0]).rstrip(":").strip().lower() == label.lower():
                return li
        return None

    status = None
    li = meta_value("Status")
    if li is not None:
        badge = li.xpath(".//span[contains(@class,'badge')]")
        status = _text(badge[0]) if badge else _text(li.xpath("./p")[-1])
        status = status or None

    refs: list[str] = []
    for label in PROCEDURE_FIELDS:
        li = meta_value(label)
        if li is None:
            continue
        value = " ".join(_text(p) for p in li.xpath("./p")[1:]) or _text(li)
        for y, n, t in _PROC_RE.findall(value):
            ref = f"{y}/{n}({t})"
            if ref not in refs:
                refs.append(ref)

    # "Blocking institutions:" badges, verbatim; several are joined with ", " in page order.
    blocking = None
    li = meta_value("Blocking institutions")
    if li is not None:
        names = [_text(a) for a in li.xpath(".//abbr")] or [_text(p) for p in li.xpath("./p")[1:]]
        blocking = ", ".join(n for n in names if n) or None

    last_updated = None
    m = _UPDATED_RE.search(doc.text_content())
    if m:
        d, mo, y = (int(x) for x in m.groups())
        last_updated = f"{y:04d}-{mo:02d}-{d:02d}"

    return FilePage(
        title=title,
        status=status,
        procedure_refs=refs,
        theme=theme,
        last_updated=last_updated,
        blocking_institution=blocking,
    )


def build_record(url: str, listed_title: str, page: FilePage, retrieved_at: str) -> TrainFile:
    title = page.title or listed_title
    return TrainFile(
        url=url,
        title=title,
        status=page.status or "",
        blocking_institution=page.blocking_institution,
        procedure_refs=page.procedure_refs,
        theme=page.theme,
        last_updated=page.last_updated,
        source=SourceRef(
            institution="LegislativeTrain",
            url=url,
            label=f"Legislative Train Schedule – {title}",
            identifier=file_slug(url),
            retrieved_at=retrieved_at,
            published=page.last_updated,
        ),
    )


# --------------------------------------------------------------------------------- crawling


def _get(http: Http, url: str) -> str:
    return http.get(url, headers=HEADERS).decode("utf-8", errors="replace")


def discover_files(
    http: Http, terms: Iterable[str] = COMMISSION_TERMS
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Return ({file slug: (url, listed title)}, notes). Most recent term wins for duplicates."""
    files: dict[str, tuple[str, str]] = {}
    notes: list[str] = []
    for term in terms:
        rows = parse_schedule(_get(http, f"{BASE}schedule?pov=EC_PRIORITIES&commission={term}&reload=false"))
        if not rows:
            raise RuntimeError(f"no themes found in Legislative Train schedule for {term}")
        for row in rows:
            listed = parse_theme(_get(http, BASE + row.slug))
            expected = sum(row.counts.values()) if row.counts else None
            if expected is not None and expected != len(listed):
                notes.append(f"{row.slug}: schedule counts {expected} files, theme page lists {len(listed)}")
            for url, title in listed:
                files.setdefault(file_slug(url), (url, title))
        log.info("train %s: %d themes, %d unique files so far", term, len(rows), len(files))
    return files, notes


def fetch(http: Http) -> SourceStatus:
    attempted = now_iso()
    files, notes = discover_files(http)
    records: list[TrainFile] = []
    errors: list[str] = []
    for i, (_slug, (url, listed_title)) in enumerate(sorted(files.items())):
        try:
            page = parse_file_page(_get(http, url))
        except HttpError as e:
            errors.append(f"{url}: HTTP {e.status}")
            continue
        if not page.status:
            errors.append(f"{url}: no status found")
            continue
        records.append(build_record(url, listed_title, page, now_iso()))
        if (i + 1) % 100 == 0:
            log.info("train: %d/%d file pages", i + 1, len(files))

    if not records:
        raise RuntimeError(f"Legislative Train: no file pages parsed ({len(errors)} errors)")

    unknown = sorted({r.status for r in records} - STATUS_VOCABULARY)
    counts = Counter(r.status for r in records)
    write_records(SOURCE_ID, "files", records, key=lambda r: r.url)

    note_parts = ["statuses: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))]
    if unknown:
        note_parts.append(f"statuses outside known vocabulary (stored as published): {unknown}")
    if errors:
        note_parts.append(f"{len(errors)} file pages skipped, e.g. {errors[:3]}")
    if notes:
        note_parts.append("index mismatches: " + "; ".join(notes[:5]))
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if (errors or unknown) else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"files": len(records)},
        note=" | ".join(note_parts)[:1000],
    )
