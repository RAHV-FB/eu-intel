"""The implementation tracker (docs/ASSESSMENT_2026-11.md, plan item 2.5): where each Member State stands on each
directive, and a feed per Member State.

    public/data/transposition.json        the directives of the site's files whose general transposition deadline
                                          falls in the tracker's window, each with every Member State's status as the
                                          directive's own page gives it (Builder.implementation_table): the measures
                                          notified, the latest notification and the open infringement cases
    public/data/feeds/countries/<CC>.xml  one Atom feed per Member State: the national measures it notified for those
                                          directives, the Commission's infringement decisions on it, and the
                                          transposition deadlines reached of the directives that bind it

The window is the last 3 years and the next 12 months, on the reader's date (the page applies it; the build writes a
month more at each end, so that a page read some days after the build still has every directive of its window).
Three years back reach past the point at which the European Council counts a directive as long overdue (2 years, the
Single Market Scoreboard's "zero tolerance" target) to when most non-communication cases have been closed or referred
to the Court of Justice (the Commission's indicative target is 12 months; such cases took 15.2 months on average in
December 2025, by the Scoreboard). Twelve months ahead cover the year in which Member States usually prepare and
notify their measures.

The data says what each record says, no more: a notified measure is what a Member State told the Commission, not proof
of complete or correct transposition; "no measures found" is a gap in the dataset, not a finding; an infringement
decision is a step of the Commission's procedure, not a ruling. Nothing here ranks or scores a Member State, and no
count is added up across Member States or directives into a score.

Feed entries keep the conventions of pipeline/analysis/feeds.py: its escaping, and stable tag-URI ids under TAG_BASE
that never depend on SITE_URL. An entry's `updated` is the date of the event it reports, not of the build. The
infringement register gives only each case's latest decision, so an entry is one case at one stage on one date: a new
decision is a new entry (and the previous one leaves the feed with the data).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from pipeline.analysis.feeds import FEED_LIMIT, TAG_BASE, TITLE, _long_date, _x, _xa
from pipeline.models.countries import MEMBER_STATES

YEARS_BACK = 3
MONTHS_AHEAD = 12
MARGIN_DAYS = 31  # written beyond each end of the window: the page applies the window on the reader's date
NOT_BINDING = ("not_participating", "not_required")  # opt-outs (Protocols 21 and 22) and the directive's exemptions
NIM_URL = "https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:{celex}"
MEASURE_TITLES = 3  # national measures named in an entry's summary
TITLE_MAX = 160


def _shift_months(d: date, months: int) -> date:
    """The same day `months` later (earlier when negative), or the month's last day when it has no such day."""
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def window(today: str, margin_days: int = 0) -> tuple[str, str]:
    """The first and last deadline of the tracker's window on `today`: YEARS_BACK years ago to MONTHS_AHEAD months
    ahead, widened by `margin_days` at each end."""
    t = date.fromisoformat(today)
    lo = _shift_months(t, -12 * YEARS_BACK) - timedelta(days=margin_days)
    hi = _shift_months(t, MONTHS_AHEAD) + timedelta(days=margin_days)
    return lo.isoformat(), hi.isoformat()


def _case(i: dict) -> dict:
    return {"id": i["id"], "stage": i["latest_stage"], "date": i["latest_decision_date"],
            "non_communication": i["non_communication"], "url": i["source"]["url"]}  # fmt: skip


def tracker_data(b: Any) -> dict:
    """transposition.json: the directives in the window (with its margin) on the build's date, by deadline."""
    lo, hi = window(b.today, MARGIN_DAYS)
    out = []
    for a in b.site_directives():
        info = b.directive_info(a)
        deadline = info["deadline"]
        if not deadline or not lo <= deadline <= hi:
            continue
        table = b.implementation_table(a)  # the statuses of the directive's own page
        unknown = set(table.get("participation_unknown") or [])
        countries = []
        for c in table["countries"]:
            row: dict[str, Any] = {"country": c["country"], "status": c["status"], "measures": c["measures"]}
            if c.get("latest_notification"):
                row["latest_notification"] = c["latest_notification"]
            cases = [_case(i) for i in c["infringements"] if i["status"] == "open"]
            if cases:
                row["cases"] = cases
            # Denmark or Ireland without measures, where no record says whether the directive binds it
            if c["country"] in unknown and not c["measures"]:
                row["participation_unknown"] = True
            countries.append(row)
        summary = b.dossier_summary.get(info["dossier_id"] or "") or {}
        out.append({**info, "topics": list(summary.get("topics") or []), "countries": countries})
    out.sort(key=lambda d: (d["deadline"], d["celex"]))
    return {"built_on": b.today, "window": {"years_back": YEARS_BACK, "months_ahead": MONTHS_AHEAD}, "directives": out}


# ----------------------------------------------------------------------------------------- feeds
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "none"


def _about(info: dict) -> str:
    """What a title adds to a directive's number: the names its file is known by, else the start of its title."""
    return f" ({', '.join(info['names'])})" if info.get("names") else f": {_cut(info['title'], 90)}"


def _cut(text: str, n: int = TITLE_MAX) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    head = text[:n]
    return head[: head.rfind(" ")].rstrip(",;:(") + "…" if " " in head else head[: n - 1] + "…"


def _page(site: str, info: dict, code: str) -> str:
    """The directive's table on its file's page, with the Member State's row highlighted; EUR-Lex's list of national
    measures when the directive has no page here."""
    if info.get("dossier_id"):
        return f"{site}legislation/{quote(info['dossier_id'])}/?country={code}#national"
    return NIM_URL.format(celex=info["celex"])


def country_entries(b: Any, code: str, site: str, infos: dict[str, dict] | None = None) -> list[dict]:
    """Every entry of one Member State's feed, newest first (the feed keeps FEED_LIMIT). `infos`: Builder.directive_info
    of each of the site's directives, by CELEX (computed here when not given)."""
    name = MEMBER_STATES[code]
    entries: list[dict] = []
    directives = b.site_directives()
    infos = infos if infos is not None else {a.celex: b.directive_info(a) for a in directives}
    # national measures notified for the site's directives: one entry per directive per notification date
    for a in directives:
        info = infos[a.celex]
        by_day: dict[str, list] = defaultdict(list)
        for m in b.measures_by.get((a.celex, code), []):
            if m.notified and m.notified <= b.today:  # a notification dated after the build is not reported
                by_day[m.notified].append(m)
        for day, ms in by_day.items():
            n = len(ms)
            titles = sorted({_cut(m.title, 150) for m in ms if m.title})
            listed = "; ".join(f"“{t}”" for t in titles[:MEASURE_TITLES])
            more = f" and {len(titles) - MEASURE_TITLES} more" if len(titles) > MEASURE_TITLES else ""
            entries.append({
                "id": f"{TAG_BASE}/countries/{code}/measures/{a.celex}/{day}",
                "date": day, "kind": "measures",
                "title": f"{name} notified {n} national measure{'s' if n > 1 else ''} for {info['act']}{_about(info)}",
                "summary": (f"{_long_date(day)}: {name} notified the Commission of {n} national "
                            f"measure{'s' if n > 1 else ''} for {info['act']}, {_cut(info['title'])}, as EUR-Lex lists "
                            f"{'them' if n > 1 else 'it'}{': ' + listed + more if listed else ''}. A notified measure "
                            "is what the Member State told the Commission; it does not show that transposition is "
                            "complete or correct."),
                "link": _page(site, info, code), "via": NIM_URL.format(celex=a.celex),
            })  # fmt: skip
    # the Commission's infringement decisions: each case at its latest stage, as the register publishes it
    for ic in b.infr_by_country.get(code, []):
        if not ic.latest_stage or not ic.latest_decision_date or ic.latest_decision_date > b.today:
            continue
        stage = " ".join(ic.latest_stage.split())
        on = next((infos[c] for c in sorted({*(ic.legal_basis or []), *([ic.celex] if ic.celex else [])})
                   if c in infos and infos[c].get("dossier_id")), None)  # fmt: skip
        status = {"open": " The register lists the case as open.",
                  "closed": " The register lists the case as closed."}.get(ic.status, "")  # fmt: skip
        nc = " It concerns a failure to notify transposition measures." if ic.non_communication else ""
        entries.append({
            "id": f"{TAG_BASE}/countries/{code}/infringements/{quote(ic.id, safe='')}/{_slug(stage)}/"
                  f"{ic.latest_decision_date}",
            "date": ic.latest_decision_date, "kind": "infringement",
            "title": f"{stage}: {_cut(ic.title)} ({ic.id})" if ic.title != ic.id else f"{stage}: {ic.id}",
            "summary": (f"{_long_date(ic.latest_decision_date)}: the Commission's decision in infringement case "
                        f"{ic.id}, “{stage}”, as its register of infringement decisions publishes it.{nc}{status} "
                        "A decision in an infringement case is a step of the Commission's procedure, not a ruling of "
                        "the Court of Justice."),
            "link": ic.source.url, "related": _page(site, on, code) if on else None,
        })  # fmt: skip
    # transposition deadlines reached, for the directives that bind the Member State
    for a in directives:
        info = infos[a.celex]
        deadline = info["deadline"]
        if not deadline or deadline > b.today:
            continue
        status = b.transposition_status(a.celex, code, deadline)
        if status in NOT_BINDING:
            continue
        # Denmark or Ireland without measures, where no record says whether the directive binds it (as the table says)
        unknown = (code in ("DK", "IE") and not b.measures_by.get((a.celex, code))
                   and not b.participation_recorded(a.celex, code))  # fmt: skip
        entries.append({
            "id": f"{TAG_BASE}/countries/{code}/deadlines/{a.celex}/{deadline}",
            "date": deadline, "kind": "deadline",
            "title": f"Transposition deadline: {info['act']}{_about(info)}",
            "summary": (f"{_long_date(deadline)}: the deadline for transposing {info['act']}, {_cut(info['title'])}, "
                        f"into national law. The directive's page lists the national measures {name} has notified "
                        "to the Commission and any infringement case."
                        + (f" Our sources do not record whether the directive binds {name} (Protocols No 21 and 22)."
                           if unknown else "")),
            "link": _page(site, info, code), "via": NIM_URL.format(celex=a.celex),
        })  # fmt: skip
    entries.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return entries


def _atom(code: str, entries: list[dict], site: str, fallback_updated: str) -> str:
    name = MEMBER_STATES[code]
    path = f"feeds/countries/{code}.xml"
    shown = entries[:FEED_LIMIT]
    updated = max((f"{e['date']}T00:00:00Z" for e in shown), default=fallback_updated)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{_x(f'{name}: applying EU directives – {TITLE}')}</title>",
        f"  <subtitle>{_x(subtitle(name))}</subtitle>",
        f"  <id>{_x(TAG_BASE)}/{_x(path)}</id>",
        f'  <link rel="self" type="application/atom+xml" href={_xa(site + "data/" + path)}/>',
        f'  <link rel="alternate" type="text/html" href={_xa(f"{site}countries/{code}/")}/>',
        f"  <updated>{_x(updated)}</updated>",
        f"  <author><name>{_x(TITLE)}</name><uri>{_x(site)}</uri></author>",
        f"  <generator>{_x(TITLE)} pipeline</generator>",
        "  <rights>Data © European Union (official EU sources); see the About page for reuse terms.</rights>",
    ]
    for e in shown:
        lines += [
            "  <entry>",
            f"    <title>{_x(e['title'])}</title>",
            f"    <id>{_x(e['id'])}</id>",
            f'    <link rel="alternate" type="text/html" href={_xa(e["link"])}/>',
            f"    <updated>{_x(e['date'])}T00:00:00Z</updated>",
            f"    <published>{_x(e['date'])}T00:00:00Z</published>",
            f"    <summary>{_x(e['summary'])}</summary>",
            f"    <category term={_xa(e['kind'])}/>",
        ]
        if e.get("related"):
            lines.append(f'    <link rel="related" type="text/html" href={_xa(e["related"])}/>')
        if e.get("via"):
            lines.append(f'    <link rel="via" href={_xa(e["via"])}/>')
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def subtitle(name: str) -> str:
    return (f"National measures {name} notified to the Commission for the directives of the legislative files on "
            f"this site (as EUR-Lex lists them), the Commission's infringement decisions on {name} (each case's latest "
            f"decision, as its register publishes it) and the transposition deadlines of the directives that bind "
            f"{name}. A notified measure does not show that transposition is complete or correct; an infringement "
            "decision is not a court ruling.")  # fmt: skip


def country_feeds(b: Any, site_url: str) -> dict[str, str]:
    """feeds/countries/<CC>.xml for the 27 Member States: each its newest FEED_LIMIT entries."""
    site = site_url if site_url.endswith("/") else site_url + "/"
    fallback = f"{b.today}T00:00:00Z"
    infos = {a.celex: b.directive_info(a) for a in b.site_directives()}
    return {f"feeds/countries/{code}.xml": _atom(code, country_entries(b, code, site, infos), site, fallback)
            for code in sorted(MEMBER_STATES)}  # fmt: skip
