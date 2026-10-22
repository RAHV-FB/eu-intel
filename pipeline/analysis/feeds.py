"""Atom 1.0 feeds generated from the public activity list.

    public/data/feeds/updates.xml       all recent activity
    public/data/feeds/<topic>.xml       activity on dossiers in that topic

Links point to the app routes under SITE_URL (default https://rahv-fb.github.io/eu-intel/).
All text is XML-escaped; entry ids are stable tag URIs derived from the activity id.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse
from xml.sax.saxutils import escape, quoteattr

FEED_LIMIT = 100
TITLE = "EU Legislative Intelligence"


def _ts(item: dict) -> str:
    return item.get("detected_at") or f"{item['date']}T00:00:00Z"


def _route(item: dict) -> str:
    if item.get("dossier_id"):
        return f"legislation/{quote(item['dossier_id'])}"
    if item.get("vote_id"):
        return f"votes/{quote(item['vote_id'])}"
    return ""


def _tag_base(site_url: str) -> str:
    host = urlparse(site_url).netloc or "eu-intel"
    return f"tag:{host},2026:eu-intel"


def atom(title: str, subtitle: str, feed_path: str, items: list[dict], site_url: str, fallback_updated: str) -> str:
    site = site_url if site_url.endswith("/") else site_url + "/"
    tag = _tag_base(site)
    items = items[:FEED_LIMIT]
    updated = max((_ts(i) for i in items), default=fallback_updated)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(title)}</title>",
        f"  <subtitle>{escape(subtitle)}</subtitle>",
        f"  <id>{escape(tag)}/{escape(feed_path)}</id>",
        f"  <link rel=\"self\" type=\"application/atom+xml\" href={quoteattr(site + 'data/' + feed_path)}/>",
        f"  <link rel=\"alternate\" type=\"text/html\" href={quoteattr(site)}/>",
        f"  <updated>{escape(updated)}</updated>",
        f"  <author><name>{escape(TITLE)}</name><uri>{escape(site)}</uri></author>",
        f"  <generator>{escape(TITLE)} pipeline</generator>",
        "  <rights>Data © European Union (official EU sources); see the About page for reuse terms.</rights>",
    ]
    for it in items:
        link = site + _route(it)
        summary = f"{it['date']}: {it['title']}"
        if it.get("detected_at") is None:
            summary += " (recorded in the official source; detection time not tracked)"
        lines += [
            "  <entry>",
            f"    <title>{escape(it['title'])}</title>",
            f"    <id>{escape(tag)}/activity/{escape(quote(it['id'], safe=':-_.'))}</id>",
            f"    <link rel=\"alternate\" type=\"text/html\" href={quoteattr(link)}/>",
            f"    <updated>{escape(_ts(it))}</updated>",
            f"    <published>{escape(it['date'])}T00:00:00Z</published>",
            f"    <summary>{escape(summary)}</summary>",
            f"    <category term={quoteattr(it['kind'])}/>",
        ]
        src = it.get("source") or {}
        if src.get("url"):
            lines.append(f"    <link rel=\"via\" href={quoteattr(src['url'])}/>")
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def build_feeds(b: Any, site_url: str) -> dict[str, str]:
    items: list[dict] = list(getattr(b, "activity_items", []))
    fallback = f"{b.today}T00:00:00Z"
    out = {
        "feeds/updates.xml": atom(
            f"{TITLE} – latest updates",
            "Recorded steps on EU legislation: proposals, votes, adoptions and publications.",
            "feeds/updates.xml",
            items,
            site_url,
            fallback,
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
        )
    return out
