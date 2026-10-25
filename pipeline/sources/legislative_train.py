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
through the shared, throttled, caching ``Http`` client. File pages are re-read incrementally and
failures keep the stored records (see "crawling" below).

The site's bot filter answers HTTP 202 (an empty JavaScript challenge) to user agents that are not
in the common "product/version" browser or tool form, including the pipeline's default one. We
therefore send the same honest bot identification in the conventional crawler form
``Mozilla/5.0 (compatible; <bot>/<version>; +<info url>)``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urljoin

import lxml.html

from pipeline.http import USER_AGENT, Http, HttpError
from pipeline.models.entities import SourceRef, SourceStatus, TrainFile
from pipeline.snapshot import (
    fetch_deadline,
    now_iso,
    past,
    read_records,
    read_state,
    write_records,
    write_state,
)

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


@dataclass
class ThemeHint:
    status: str | None  # the file's current status as shown on the theme page's timeline
    recently_updated: bool  # the theme page marks the file "Recently updated carriage"


def parse_theme_hints(html: str) -> dict[str, ThemeHint]:
    """{absolute file URL: ThemeHint} for the files of a theme page's timetable. The timeline's last
    carriage shows the current status (equal to the file page's status on all 71 files compared on
    2026-10-22)."""
    doc = lxml.html.fromstring(html)
    out: dict[str, ThemeHint] = {}
    for li in doc.xpath("//li[contains(concat(' ', normalize-space(@class), ' '), ' timetable ')]"):
        links = [a for a in li.xpath(".//h3//a[@href]") if _FILE_HREF_RE.match(a.get("href", "").strip())]
        if not links:
            continue
        notes = [_text(p) for p in li.xpath(".//p[contains(@class,'notification')]")]
        last = notes[-1] if notes else ""
        status = last.split(":", 1)[1].strip() if last.startswith("Status:") else None
        recent = bool(li.xpath(".//h3//*[contains(@class,'icon-update')]"))
        out.setdefault(urljoin(BASE, links[0].get("href").strip()), ThemeHint(status or None, recent))
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
#
# Incremental re-reading. On 2026-10-22 every file of the current Commission term carried the same
# "Information updated as of" date (the site updates them in a monthly batch), while files of earlier terms
# keep the date of their last update (e.g. 2019-11-20, 2024-12-15). A stored record is therefore reused
# without reading its file page when all of these hold:
# - the theme page shows the same status for it and does not mark it "Recently updated",
# - its "Information updated as of" date is older than ACTIVE_DAYS,
# - it is not in this week's share of the RECHECK_WEEKS rotation (each quiet file is re-read every
#   RECHECK_WEEKS weeks anyway), and it was not left pending by the previous run.
# EU_INTEL_FULL_REFRESH=1 re-reads every file page.
#
# Failure safety. A file page or theme page that cannot be read keeps the stored records (by URL, or by
# file slug for a file that moved to another theme); a schedule page that cannot be read falls back to the
# theme list of the previous run (_state.json). After fetch_deadline() no new page is requested; the files
# not read are carried forward and listed as pending in _state.json, so the next run starts with them.
# files.json is not written if it would lose more than MAX_SHRINK of its records.
ACTIVE_DAYS = 90
RECHECK_WEEKS = 4
MAX_SHRINK = 0.05


def _today() -> date:  # monkeypatched in tests
    return datetime.now(UTC).date()


def _get(http: Http, url: str) -> str:
    return http.get(url, headers=HEADERS).decode("utf-8", errors="replace")


def recheck_slot(slug: str) -> int:
    """The week (modulo RECHECK_WEEKS) in which a quiet file is re-read; stable across runs."""
    return int(hashlib.sha256(slug.encode()).hexdigest()[:8], 16) % RECHECK_WEEKS


def week_slot(today: date) -> int:
    return (today.toordinal() // 7) % RECHECK_WEEKS  # weeks start on Mondays


def needs_page(
    url: str, old: TrainFile | None, hint: ThemeHint | None, today: date, full: bool = False
) -> str | None:
    """Why the file page must be read this run; None = the stored record is reused as it is."""
    if full:
        return "full refresh"
    if old is None:
        return "new"
    if hint is None or hint.status is None:
        return "no status on the theme page"
    if hint.status != old.status:
        return "status changed"
    if hint.recently_updated:
        return "recently updated"
    if not old.last_updated or old.last_updated >= (today - timedelta(days=ACTIVE_DAYS)).isoformat():
        return "active"
    if recheck_slot(file_slug(url)) == week_slot(today):
        return "periodic re-check"
    return None


@dataclass
class Discovery:
    files: dict[str, tuple[str, str]] = field(default_factory=dict)  # file slug -> (url, listed title)
    hints: dict[str, ThemeHint] = field(default_factory=dict)  # url -> theme-page status
    carried: dict[str, TrainFile] = field(default_factory=dict)  # url -> stored record (theme page unread)
    themes: dict[str, list[str]] = field(default_factory=dict)  # Commission term -> theme slugs
    notes: list[str] = field(default_factory=list)  # index mismatches (informational)
    problems: list[str] = field(default_factory=list)  # pages that could not be read (run is partial)


def discover_files(
    http: Http,
    terms: Iterable[str] = COMMISSION_TERMS,
    previous: dict[str, TrainFile] | None = None,
    known_themes: dict[str, list[str]] | None = None,
    deadline: float | None = None,
) -> Discovery:
    """Files listed on the theme pages of every term. Most recent term wins for duplicates."""
    previous = previous or {}
    known_themes = known_themes or {}
    d = Discovery()
    for term in terms:
        try:
            rows = parse_schedule(
                _get(http, f"{BASE}schedule?pov=EC_PRIORITIES&commission={term}&reload=false")
            )
            if not rows:
                raise RuntimeError(f"no themes found in Legislative Train schedule for {term}")
            themes = [(r.slug, sum(r.counts.values()) if r.counts else None) for r in rows]
        except Exception as e:  # noqa: BLE001 - HTTP error, WAF or empty page
            stored = known_themes.get(term)
            if not stored:
                raise RuntimeError(f"Legislative Train schedule for {term} unavailable: {e}") from e
            d.problems.append(
                f"schedule {term} unavailable ({e}); used the {len(stored)} themes of the last run"
            )
            themes = [(slug, None) for slug in stored]
        d.themes[term] = [slug for slug, _ in themes]
        for slug, expected in themes:
            try:
                if past(deadline):
                    raise RuntimeError("time budget reached")
                html = _get(http, BASE + slug)
                listed = parse_theme(html)
                if not listed and expected != 0:
                    raise RuntimeError("theme page lists no files")
            except Exception as e:  # noqa: BLE001 - keep the theme's stored files
                kept = {u: r for u, r in previous.items() if u.startswith(f"{BASE}{slug}/file-")}
                d.problems.append(f"{slug}: {str(e)[:120]}; {len(kept)} stored files kept")
                for u, r in sorted(kept.items()):
                    if file_slug(u) not in d.files:
                        d.files[file_slug(u)] = (u, r.title)
                        d.carried[u] = r
                continue
            if expected is not None and expected != len(listed):
                d.notes.append(f"{slug}: schedule counts {expected} files, theme page lists {len(listed)}")
            d.hints.update(parse_theme_hints(html))
            for url, title in listed:
                d.files.setdefault(file_slug(url), (url, title))
        log.info("train %s: %d themes, %d unique files so far", term, len(themes), len(d.files))
    return d


def fetch(http: Http) -> SourceStatus:
    attempted = now_iso()
    deadline = fetch_deadline()
    today = _today()
    full = os.environ.get("EU_INTEL_FULL_REFRESH") == "1"
    state = read_state(SOURCE_ID)
    stored = read_records(SOURCE_ID, "files", TrainFile)
    previous = {r.url: r for r in stored}
    by_slug = {file_slug(r.url): r for r in stored}
    disc = discover_files(
        http, COMMISSION_TERMS, previous=previous, known_themes=state.get("themes"), deadline=deadline
    )
    pending_before = set(state.get("pending", []))

    records: dict[str, TrainFile] = {}
    errors: list[str] = []
    pending: list[str] = []
    reasons: Counter[str] = Counter()
    reused = 0
    # files left pending by the previous run first
    order = sorted(disc.files.items(), key=lambda kv: (kv[1][0] not in pending_before, kv[0]))
    for i, (slug, (url, listed_title)) in enumerate(order):
        if url in disc.carried:
            records[url] = disc.carried[url]
            continue
        old = previous.get(url) or by_slug.get(slug)
        why = (
            "pending"
            if url in pending_before
            else needs_page(url, previous.get(url), disc.hints.get(url), today, full)
        )
        if why is None and old is not None:
            records[old.url] = old
            reused += 1
            continue
        if past(deadline):
            pending.append(url)
            if old is not None:
                records[old.url] = old
            continue
        try:
            page = parse_file_page(_get(http, url))
            if not page.status:
                raise ValueError("no status found")
        except Exception as e:  # noqa: BLE001 - HTTP error, WAF or unreadable page: keep the stored record
            errors.append(f"{url}: {f'HTTP {e.status}' if isinstance(e, HttpError) else str(e)[:80]}")
            pending.append(url)
            if old is not None:
                records[old.url] = old
            continue
        records[url] = build_record(url, listed_title, page, now_iso())
        reasons[why or "new"] += 1
        if (i + 1) % 100 == 0:
            log.info("train: %d/%d files (%d pages read)", i + 1, len(order), sum(reasons.values()))

    if not records:
        raise RuntimeError(f"Legislative Train: no file pages parsed ({len(errors)} errors)")
    if stored and len(records) < (1 - MAX_SHRINK) * len(stored):
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note=(
                f"only {len(records)} files found (previously {len(stored)}); snapshot kept. "
                + "; ".join((disc.problems + errors)[:5])
            )[:1000],
        )

    out = list(records.values())
    unknown = sorted({r.status for r in out} - STATUS_VOCABULARY)
    counts = Counter(r.status for r in out)
    write_records(SOURCE_ID, "files", out, key=lambda r: r.url)
    write_state(SOURCE_ID, {"themes": disc.themes, "pending": sorted(pending)})

    fetched = sum(reasons.values())
    note_parts = [
        "statuses: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        f"{fetched} file pages read ({', '.join(f'{k} {v}' for k, v in sorted(reasons.items()))}), "
        f"{reused} unchanged files reused, {len(disc.carried)} kept from unreadable theme pages",
    ]
    if unknown:
        note_parts.append(f"statuses outside known vocabulary (stored as published): {unknown}")
    if errors:
        note_parts.append(f"{len(errors)} file pages unreadable (previous records kept), e.g. {errors[:3]}")
    if pending:
        note_parts.append(
            f"{len(pending)} files pending; resumes next run"
            + (" (time budget reached)" if past(deadline) else "")
        )
    if disc.problems:
        note_parts.append("index pages unreadable: " + "; ".join(disc.problems[:5]))
    if disc.notes:
        note_parts.append("index mismatches: " + "; ".join(disc.notes[:5]))
    partial = bool(errors or unknown or pending or disc.problems)
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if partial else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"files": len(out), "fetched_this_run": fetched, "reused": reused, "pending": len(pending)},
        note=" | ".join(note_parts)[:1000],
    )
