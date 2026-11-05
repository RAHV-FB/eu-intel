"""Atom 1.0 feeds generated from the public activity list.

    public/data/feeds/updates.xml            all recent activity
    public/data/feeds/<topic>.xml            activity on dossiers in that topic
    public/data/feeds/dossiers/<id>.xml      one legislative file: its latest steps, votes and status changes

Links point to the app routes under SITE_URL (default https://rahv-fb.github.io/eu-intel/): a Parliament vote to
its vote page, another item to its file's page; an item with no page on the site (e.g. a Council vote on no
tracked file) links to its official source document.
All text is XML-escaped; entry ids are stable tag URIs derived from the activity id. They do not depend on
SITE_URL: an id must not change when the feed moves (RFC 4287, 4.2.6), e.g. to a custom domain. An entry has the same id
in every feed it is in.

Entries name the file by its full title (activity headlines shorten it), and say the file's status and next step as
the data records them. A status change and the step that gave the status (pipeline/analysis/changes.py: the same file
and day, the record it cites) are one entry, with the status change's id, which feeds published before as the status
change's own entry: a reader that has both sees no new entry.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape, quoteattr

from pipeline.analysis import activity, changes

FEED_LIMIT = 100
# a file's own feed: its latest entries, of any date (the 1,587 files' feeds took 13.3 MB with 12 entries each, each
# stating the file's status and next step; 10, of which the newest states them, take about 8 MB)
FILE_FEED_LIMIT = 10
TITLE = "EU Legislative Intelligence"
# the authority of every feed and entry id (RFC 4151 tag URI): the site's host when the feeds were first
# published, kept when the site moves
TAG_BASE = "tag:rahv-fb.github.io,2026:eu-intel"
# next steps that say nothing (build.UNKNOWN_STEPS)
NO_NEXT_STEP = {"Not available.", "Not determined from the recorded events."}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]  # fmt: skip
# characters XML 1.0 does not allow in a document (a control character in a source's title would make the feed unreadable)
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _x(s: Any) -> str:
    return escape(_NOT_XML.sub("", str(s)))


def _xa(s: Any) -> str:
    return quoteattr(_NOT_XML.sub("", str(s)))


def _web_url(u: Any) -> str | None:
    """A source's address if it is a web address (http or https, with a host), else None: a feed reader opens an entry's
    links as they are, so a javascript: or data: address from a source must not become one (the site applies the same
    rule, src/lib/format.ts safeUrl)."""
    if not isinstance(u, str):
        return None
    try:
        p = urlsplit(u)  # strips the spaces and control characters a browser ignores around a URL, as a browser does
    except ValueError:
        return None
    return u.strip() if p.scheme in ("http", "https") and p.hostname else None


def _long_date(d: str) -> str:
    try:
        x = date.fromisoformat(d[:10])
    except ValueError:
        return d
    return f"{x.day} {_MONTHS[x.month - 1]} {x.year}"


def _ts(item: dict) -> str:
    return item.get("detected_at") or f"{item['date']}T00:00:00Z"


def _route(item: dict) -> str:
    # a Parliament vote opens its own page, which links its file: two motions voted on one file that day are two
    # entries with two links (195775 and 195807, 2025/0429(COD), 9 July 2026). The trailing slash is the address of
    # the page that is served (scripts/prerender-routes.mjs); without it GitHub Pages answers with a redirect.
    if item.get("kind") == "ep_vote" and item.get("vote_id"):
        return f"votes/{quote(item['vote_id'])}/"
    if item.get("dossier_id"):
        return f"legislation/{quote(item['dossier_id'])}/"
    if item.get("vote_id"):
        return f"votes/{quote(item['vote_id'])}/"
    return ""


def entry_title(item: dict, step: dict | None, file: dict | None) -> str:
    """The entry's title: the headline with the file's full title; a status change told with its step: the step's
    headline and the new status ("…: Entered into force — status now “In force”")."""
    title, timeline = (file or {}).get("title"), (file or {}).get("timeline")
    parts = changes.status_parts(item) if step is not None else None
    if step is None or parts is None:
        return changes.full_headline(item, title, timeline)
    return f"{changes.full_headline(step, title, timeline)} — status now “{parts[0]}”"


def entry_summary(item: dict, step: dict | None, file: dict | None, as_of: str | None, state: bool = True) -> str:
    """What happened on which day, the status it gave the file (a status change), and (`state`) the file's status and
    next step as the data records them on `as_of`: "4 November 2026: Entered into force. Status now “In force”
    (previously “Signed, awaiting publication”). Next step as recorded on 5 November 2026: …"."""
    told = step or item
    what = told.get("event") or changes.event_of(told, (file or {}).get("title"), (file or {}).get("timeline")) or told["title"]
    lines = [f"{_long_date(told['date'])}: {what.rstrip('.')}."]
    parts = changes.status_parts(item)
    if parts and step is not None:
        now, was = parts
        lines.append(f"Status now “{now}”" + (f" (previously “{was}”)." if was else "."))
    if file and state:
        status, nxt = file.get("status"), file.get("next")
        recorded = f" as recorded on {_long_date(as_of)}" if as_of else ""
        if status and not (parts and parts[0] == status):
            lines.append(f"Status{recorded}: “{status}”.")
            recorded = ""
        if nxt and nxt not in NO_NEXT_STEP:
            lines.append(f"Next step{recorded}: {nxt.rstrip('.')}.")
    if item.get("detected_at") is None:
        lines.append("(Recorded in the official source; detection time not tracked.)")
    return " ".join(lines)


def atom(
    title: str,
    subtitle: str,
    feed_path: str,
    items: list[dict],
    site_url: str,
    fallback_updated: str,
    files: dict[str, dict] | None = None,
    page: str = "",
    as_of: str | None = None,
    limit: int = FEED_LIMIT,
    state_on_latest: bool = False,
) -> str:
    """One Atom feed. `files`: per file id its full `title`, `status` label and `next` step (text), for the entries'
    titles and summaries; `page`: the route of the feed's page on the site (its alternate link); `as_of`: the date the
    data records the statuses on; `state_on_latest`: only the newest entry states the file's status and next step (a
    file's own feed, whose entries are all about it)."""
    site = site_url if site_url.endswith("/") else site_url + "/"
    tag = TAG_BASE
    told = changes.told_together(items)[:limit]
    updated = max((_ts(i) for i, _ in told), default=fallback_updated)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{_x(title)}</title>",
        f"  <subtitle>{_x(subtitle)}</subtitle>",
        f"  <id>{_x(tag)}/{_x(feed_path)}</id>",
        f'  <link rel="self" type="application/atom+xml" href={_xa(site + "data/" + feed_path)}/>',
        f'  <link rel="alternate" type="text/html" href={_xa(site + page)}/>',
        f"  <updated>{_x(updated)}</updated>",
        f"  <author><name>{_x(TITLE)}</name><uri>{_x(site)}</uri></author>",
        f"  <generator>{_x(TITLE)} pipeline</generator>",
        "  <rights>Data © European Union (official EU sources); see the About page for reuse terms.</rights>",
    ]
    for n, (it, step) in enumerate(told):
        # an item with no page on the site (a Council vote on no tracked file) links to its official document
        route, src_url = _route(it), _web_url((it.get("source") or (step or {}).get("source") or {}).get("url"))
        link = site + route if route or not src_url else src_url
        file = (files or {}).get(it.get("dossier_id") or "")
        summary = entry_summary(it, step, file, as_of, state=not state_on_latest or n == 0)
        lines += [
            "  <entry>",
            f"    <title>{_x(entry_title(it, step, file))}</title>",
            f"    <id>{_x(tag)}/activity/{_x(quote(it['id'], safe=':-_.'))}</id>",
            f'    <link rel="alternate" type="text/html" href={_xa(link)}/>',
            f"    <updated>{_x(_ts(it))}</updated>",
            f"    <published>{_x(it['date'])}T00:00:00Z</published>",
            f"    <summary>{_x(summary)}</summary>",
            *(f"    <category term={_xa(k)}/>" for k in dict.fromkeys([it["kind"], *([step["kind"]] if step else [])])),
        ]
        if src_url:
            lines.append(f'    <link rel="via" href={_xa(src_url)}/>')
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def file_info(b: Any) -> dict[str, dict]:
    """Per file id: its full title, status label and next step, as the entries state them, and its timeline (to read a
    headline recorded under an earlier title of the file)."""
    out = {}
    for pid, det in (getattr(b, "dossier_detail", None) or {}).items():
        out[pid] = {"title": det.get("title"), "status": det.get("status_label"), "ref": det.get("ref"),
                    "next": (det.get("next_step") or {}).get("text"), "timeline": det.get("timeline")}  # fmt: skip
    return out


def file_items(b: Any) -> dict[str, list[dict]]:
    """Per file id, the activity items of its own feed: the changes recorded for it that the records still support
    (Builder.activity_recorded), and the items the snapshot gives for its steps, votes and Council votes of any date
    (activity.snapshot_entries), merged as for activity.json (activity.merge), newest first."""
    rec: dict[str, list[dict]] = defaultdict(list)
    for it in getattr(b, "activity_recorded", None) or []:
        if it.get("dossier_id"):
            rec[it["dossier_id"]].append(it)
    snap: dict[str, list[tuple[dict, list[str]]]] = defaultdict(list)
    for it, refs in activity.snapshot_entries(b, days=(date.fromisoformat(b.today) - date(1950, 1, 1)).days):
        if it.get("dossier_id"):
            snap[it["dossier_id"]].append((it, refs))
    # twice the entries a feed lists: a status change and its step are one entry
    return {pid: changes.annotate(activity.merge(rec[pid], snap[pid], b.today, limit=2 * FILE_FEED_LIMIT), b)
            for pid in b.dossier_ids}  # fmt: skip


def build_feeds(b: Any, site_url: str) -> dict[str, str]:
    items: list[dict] = list(getattr(b, "activity_items", []))
    fallback = f"{b.today}T00:00:00Z"
    files = file_info(b)
    out = {
        "feeds/updates.xml": atom(
            f"{TITLE} – latest updates",
            "Recorded steps on EU legislation: proposals, votes, adoptions and publications.",
            "feeds/updates.xml",
            items,
            site_url,
            fallback,
            files,
            "legislation/changes/",
            b.today,
        )
    }
    topics_of = {pid: set(d["topics"]) for pid, d in b.dossier_summary.items()}
    for t in b.topic_list:
        slug = t["slug"]
        sel = [i for i in items if i.get("dossier_id") and slug in topics_of.get(i["dossier_id"], ())]
        out[f"feeds/{slug}.xml"] = atom(
            f"{TITLE} – {t['label']}",
            t.get("description") or f"Updates on EU legislation about {t['label']}.",
            f"feeds/{slug}.xml",
            sel,
            site_url,
            fallback,
            files,
            f"legislation/changes/?topic={quote(slug)}",
            b.today,
        )
    for pid, its in file_items(b).items():
        f = files.get(pid) or {}
        name = activity.short_title(f.get("title") or pid, 120)
        out[f"feeds/dossiers/{pid}.xml"] = atom(
            f"{name} ({f.get('ref') or pid}) – {TITLE}",
            "Steps, votes and status changes recorded on this EU legislative file, from official records.",
            f"feeds/dossiers/{pid}.xml",
            its,
            site_url,
            fallback,
            files,
            f"legislation/{quote(pid)}/",
            b.today,
            FILE_FEED_LIMIT,
            state_on_latest=True,
        )
    return out
