"""What applies when, where: the dates fixed in EU law from which an act enters into force, applies (in general or for
some provisions), must be transposed, or from which the national measures transposing a directive apply.

    public/data/applies.json                                AppliesData (src/types/data.ts), for /legislation/applies
    public/data/feeds/applies/all.xml, all.ics              every date
    public/data/feeds/applies/topics/<topic>.xml, .ics      the dates of the files on one topic
    public/data/feeds/applies/countries/<code>.xml, .ics    the dates of the acts that bind one Member State, and of
                                                            those for which the data cannot tell whether they do

Rows. One per act, date and kind (`entry_into_force`, `applies`, `transposition_deadline`, `national_application`).
The dates are the build's own, as the file's page states them (Builder.timeline): an act's entry into force and further
application dates as EUR-Lex records them, or as data/curated/act_dates.yaml checked them against the act's text, with
the provisions each covers; a directive's transposition dates as pipeline/analysis/transposition.py classifies them,
with the articles EUR-Lex names. Nothing is re-derived here. Left out: a transposition date whose role the data do not
establish ("other"), never shown as a deadline; a date EUR-Lex records for after the end of the act's validity; a date
more than 31 days before the build (the page lists what started to apply in the 30 days before the reader's date, and
the data is read for a week or more after it is built).

Where (`where`). Each Member State is bound, not bound (with the reason the data give) or not known:
- a regulation is binding in its entirety and directly applicable in all Member States, and a directive binds each
  Member State to which it is addressed (Article 288 TFEU), except: a Member State its recitals (a directive's,
  data/snapshot/optouts) or the Council's latest voting result with positions record as not taking part in its
  adoption (Protocols No 21 and 22: Denmark, Ireland), unless a Commission decision confirms it took part later
  (Protocol No 21, Article 4); a Member State a directive's own text does not require to transpose it
  (data/curated/transposition.yaml `exemption`). Whether Denmark and Ireland are bound is not known when no record in
  the data settles it (Builder.participation_recorded: a directive whose recitals could not be read, an act without a
  Council voting result with positions), and nor is any Member State's for a regulation implementing enhanced
  cooperation (Article 20(4) TEU) that no such result covers;
- a decision binds those to whom it is addressed, where it names any (Article 288 TFEU), which the data do not record:
  not known, except for a Member State recorded as not taking part.
The site never says "all Member States" unless all 27 are bound on this reading.

Feeds. The Atom feeds list the dates of the next 90 days after the build (the build's date included: a deadline is
still ahead on its day), soonest first, so that a reader subscribed to "what applies next quarter" sees an entry
appear when its date comes within 90 days of a build. Its id is a tag URI of the act, kind and date, which never
depends on SITE_URL (pipeline/analysis/feeds.py TAG_BASE) and is the same in every feed. Its `updated` (and
`published`) is that moment: the day 90 days before its date, or, if later, the day the act was published (its date,
when no publication is recorded) or its dates were last checked against its text (act_dates.yaml `reviewed`). It does
not change from one build to the next, as the build time would, which would mark every entry as changed each day the
site is rebuilt; and a new entry does not carry the date of an act published years ago, which a feed reader could
sort out of sight. A feed's `updated` is the latest of its entries', or the day after the date of the latest entry that
left it; with neither, the latest of its acts' publications.

The calendars (iCalendar, RFC 5545; pipeline/analysis/ical.py) list every date of the rows, those of the 31 days
before the build too, so that an event does not vanish from a subscribed calendar the day after it, as whole-day
events. An event's UID is built like the Atom id (stable, the same in every calendar, independent of SITE_URL), and its
DTSTAMP, the last revision of its information (RFC 5545, 3.8.7.2, for a calendar without a METHOD), is the act's
publication or the check of its dates, whichever is later: it too does not change from one build to the next.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from pipeline.analysis import ical
from pipeline.analysis.activity import short_title
from pipeline.analysis.feeds import TAG_BASE, TITLE, _long_date, _x, _xa
from pipeline.analysis.transposition import application_start, article_label
from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.models.countries import MEMBER_STATES
from pipeline.models.entities import DirectiveOptOut, LegalAct

PAST_DAYS = 31  # rows from this many days before the build
QUARTER_DAYS = 90  # the Atom feeds: the dates of the next 90 days
KINDS = ("entry_into_force", "applies", "transposition_deadline", "national_application")
# The Member States that may not take part in a measure under the Treaties' protocols (No 21: Ireland, No 22: Denmark)
OPT_OUT_STATES = ("DK", "IE")
PROTOCOL = {"DK": "22", "IE": "21"}
ENHANCED_COOPERATION_RE = re.compile(r"\bimplementing enhanced cooperation\b", re.I)
# The authority of the tag URIs (feeds.TAG_BASE: "tag:rahv-fb.github.io,2026:eu-intel"): the host of the calendar UIDs
UID_HOST = TAG_BASE.split(":")[1].split(",")[0]
FEED_DIR = "feeds/applies"
# The first build of these feeds: a feed's `updated` when nothing else dates it
FIRST_BUILT = "2026-11-05"
DECISION_NOTE = (
    "A decision binds those to whom it is addressed, where it names any (Article 288 TFEU); our data do not record "
    "whom this one names."
)
ENHANCED_NOTE = (
    "It implements enhanced cooperation, so it binds only the Member States taking part in it (Article 20(4) TEU); "
    "no Council voting result in our data says which they are."
)


# ------------------------------------------------------------------------------------------- rows
def headline(kind: str, partial: bool, further: bool = False) -> str:
    """What happens on the date, as the file's timeline says it while the date is ahead (src/lib/format.ts stepTitle
    gives the past tense): "Some provisions start to apply", "Deadline for Member States to transpose the directive"."""
    if kind == "entry_into_force":
        return "Enters into force"
    if kind == "applies":
        return "Some provisions start to apply" if partial else (
            "Further provisions start to apply" if further else "Rules start to apply")  # fmt: skip
    if kind == "transposition_deadline":
        return "Transposition deadline for specific provisions" if partial else (
            "Deadline for Member States to transpose the directive")  # fmt: skip
    return "Application date for national measures on specific provisions" if partial else (
        "Application date for the national measures")  # fmt: skip


def _valid_until(a: LegalAct) -> str | None:
    """The end of the act's validity, unless it is earlier than the act itself (a retroactive repeal, after which every
    date of the act falls): as Builder.timeline marks dates after it (build.mark_after_end_of_validity)."""
    eov = a.end_of_validity
    return eov if eov and eov >= (a.date_document or a.date_publication or "") else None


def _source(a: LegalAct, cur: dict | None, d: str) -> dict:
    """A row's source, as the file's timeline gives the step: the text the date was checked against (data/curated/
    act_dates.yaml, with the day of the check), else the act's EUR-Lex record."""
    from pipeline.build import _squash, act_date_source

    cite = act_date_source(cur, d) if cur else None
    if not cite:
        return a.source.model_dump(mode="json")
    own = cite is (cur.get("sources") or [None])[0]  # the act's own text, not an amending act or a corrigendum
    checked = f" (checked {_long_date(cur['reviewed'])})" if cur.get("reviewed") else ""
    return {"institution": "EUR-Lex", "url": cite.get("url"), "label": f"{_squash(cite.get('label'))}{checked}",
            "identifier": cite.get("celex") or (a.celex if own else None), "retrieved_at": None, "published": None}  # fmt: skip


def act_rows(a: LegalAct, cur: dict | None, lo: str, recorded: dict | None = None) -> list[dict]:
    """The dates of one act from `lo` on, each with what it is: its entry into force; the dates from which it applies,
    in general, further, or for some provisions (with the provisions where data/curated/act_dates.yaml gives them); a
    directive's transposition deadlines and the dates from which its national measures apply (with the articles EUR-Lex
    names). `cur`: the act's act_dates.yaml entry; `recorded`: the dates EUR-Lex itself records for the act, which that
    entry replaced in the build ({"entry_into_force", "application", "partial_on_entry_into_force"}), to say whether
    EUR-Lex records a checked date. A row has no `where`, act or file yet (rows())."""
    from pipeline.build import _squash

    until = _valid_until(a)
    items = {x["date"]: x for x in (cur or {}).get("application") or [] if isinstance(x, dict)}
    out: list[dict] = []

    def add(d: str, kind: str, partial: bool = False, further: bool = False, provisions: str | None = None,
            articles: list[str] | None = None, exceptions: str | None = None) -> None:  # fmt: skip
        if d < lo or (until and d > until):
            return
        row: dict[str, Any] = {"date": d, "kind": kind, "partial": partial, "title": headline(kind, partial, further)}
        if further:
            row["further"] = True
        row |= {"provisions": provisions, "articles": articles or []}
        if exceptions:
            row["exceptions"] = exceptions
        if cur:
            rec = recorded or {}
            if kind == "entry_into_force":
                eurlex = not recorded or rec.get("entry_into_force") == d
            elif kind == "applies":
                eurlex = not recorded or d in (rec.get("application") or []) or (
                    bool(rec.get("partial_on_entry_into_force")) and rec.get("entry_into_force") == d)  # fmt: skip
            else:  # act_dates.yaml does not change transposition dates
                eurlex = True
            row["checked"] = {"reviewed": cur.get("reviewed"), "eurlex": eurlex}
        row["source"] = _source(a, cur, d)
        out.append(row)

    eif = a.entry_into_force
    if eif:
        add(eif, "entry_into_force")
    # the entry into force is a date from which some provisions apply when the checked text says so (apply_act_dates
    # keeps it out of the further dates) or EUR-Lex marks it so
    on_eif = {eif} if eif and (eif in items or a.partial_on_entry_into_force) else set()
    general = [d for d in a.other_application_dates if d not in a.partial_application_dates]
    for d in sorted(set(a.other_application_dates) | on_eif):
        item = items.get(d)
        if item:
            add(d, "applies", bool(item.get("partial")), provisions=_squash(item.get("provisions")) or None)
        else:
            partial = d in a.partial_application_dates or d in on_eif
            # a date from which the act applies in general after an earlier one ("Further provisions start to apply",
            # as the timeline: Regulation (EU) 2023/2663, 28 November 2023 then 1 January 2024)
            add(d, "applies", partial, further=not partial and bool(general) and d > general[0])
    if a.act_type == "directive":
        dated = classify_transposition(a)
        start = application_start(a, dated)
        chk = a.transposition_checked
        for x in dated:
            if x.kind == "other":  # its role is not established: never shown as a deadline
                continue
            arts = [article_label(r) for r in x.articles]
            if x.kind in ("deadline", "further_deadline"):
                # what the text provides for some Member States beside the general deadline (checked)
                exc = chk.exceptions if chk and x.kind == "deadline" else None
                add(x.date, "transposition_deadline", x.kind == "further_deadline", articles=arts, exceptions=exc)
            else:
                exc = chk.application_exceptions if chk and x.date == chk.applies_from else None
                add(x.date, "national_application", bool(start) and x.date > start, articles=arts, exceptions=exc)
    return out


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _not_taking_part(rec: Any, country: str, a: LegalAct) -> dict[str, Any]:
    """Why a Member State is not bound, from the record that says it did not take part in the act's adoption: the
    directive's recital (with the protocol it cites) or the Council's voting result."""
    name = MEMBER_STATES[country]
    if isinstance(rec, DirectiveOptOut):
        q = next((q for q in rec.quotes if name in q), "")
        recital = re.match(r"\((\d+)\)", q)
        cited = re.findall(r"Protocol No (\d+)", q)
        own = PROTOCOL.get(country)  # a recital may cite both protocols ("... the United Kingdom and Ireland ...")
        protocol = own if own in cited else (cited[0] if cited else None)
        under = f"Under Protocol No {protocol}, " if protocol else ""
        where = f" (recital {recital[1]})" if recital else " (its recitals)"
        return {"reason": f"{under}{name} is not taking part in its adoption and is not bound by it{where}.",
                "url": a.eurlex_url}  # fmt: skip
    when = f" of {_long_date(rec.date)}" if getattr(rec, "date", None) else ""
    url = rec.source.url if getattr(rec, "source", None) else None
    return {"reason": f"The Council’s voting result{when} records {name} as not taking part.", "url": url}


def where_of(a: LegalAct, b: Any) -> dict:
    """Which Member States the act binds, on the records of the data (see the module docstring)."""
    from pipeline.build import opt_in_info

    optout = getattr(b, "optouts", {}).get(a.celex)
    later: dict[str, dict] = {}  # took part after its adoption (Protocol No 21, Article 4)
    if optout is not None:
        for c, decision in optout.opted_in.items():
            later[c] = {"country": c, "label": "Commission decision",
                        "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{decision}"}  # fmt: skip
    for r in getattr(b.s, "regulation_opt_ins", None) or []:
        if r.celex == a.celex:
            info = opt_in_info(r)
            later[r.country] = {"country": r.country, "label": info["label"], "url": info["url"]}
    exemption = ((getattr(b, "transposition_checks", {}).get(a.celex) or {}).get("exemption") or {})
    exempt = set(exemption.get("countries") or []) if a.act_type == "directive" else set()
    enhanced = a.act_type == "regulation" and bool(ENHANCED_COOPERATION_RE.search(a.title or ""))
    addressees = a.act_type not in ("regulation", "directive")  # a decision binds its addressees, if it names any
    bound: list[str] = []
    not_bound: list[dict] = []
    unknown: list[str] = []
    for c in sorted(MEMBER_STATES):
        if c in later:
            bound.append(c)
            continue
        rec = b.not_participating(a.celex, c)
        if rec is not None:
            why = _not_taking_part(rec, c, a)
            if c == "DK" and a.act_type == "directive" and (note := b.schengen_note(a.celex, c)):
                why["reason"] += f" {note[0]}"  # a measure building upon the Schengen acquis (Protocol No 22, Art. 4)
                why["url"] = note[1] or why["url"]
            not_bound.append({"country": c, **why})
        elif c in exempt:
            note = b.not_required_note(a.celex) or exemption.get("provision") or "its own text"
            not_bound.append({"country": c, "reason": f"The directive does not require {MEMBER_STATES[c]} to transpose "
                              f"it ({note}).", "url": a.eurlex_url})  # fmt: skip
        elif addressees:
            unknown.append(c)
        elif b.participation_recorded(a.celex, c) or (c not in OPT_OUT_STATES and not enhanced):
            bound.append(c)
        else:
            unknown.append(c)
    out: dict[str, Any] = {"bound": bound, "not_bound": not_bound, "unknown": unknown}
    if addressees:
        out["note"] = DECISION_NOTE
    elif enhanced and len(unknown) == len(MEMBER_STATES):
        out["note"] = ENHANCED_NOTE
    if later:
        out["opted_in"] = [later[c] for c in sorted(later)]
    return out


def _act_names(a: LegalAct, file_title: str, file_names: list[str]) -> list[str]:
    """The act's names besides the file's title: its own short title (in its official title), then the names its file
    is known by (known_as.names, only for a file of one act, whose names are the act's)."""
    from pipeline.build import act_short_name

    out: list[str] = []
    for n in [act_short_name(a.title), *file_names]:
        if n and n.casefold() != file_title.casefold() and n.casefold() not in {x.casefold() for x in out}:
            out.append(n)
    return out


def _act_label(a: LegalAct) -> str:
    """The act by its number as its title cites it ("Regulation (EU) 2024/1689"), as the file's timeline names it."""
    from pipeline.build import act_label, celex_act_label

    label = act_label(a)
    return label if label != a.celex else celex_act_label(a.celex) or f"{a.act_type.capitalize()} (CELEX {a.celex})"


KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


def rows(b: Any) -> dict:
    """applies.json: the rows of every file's acts, from 31 days before the build on, by date (on a day: entry into
    force, application, transposition deadline, national application; then by file title)."""
    lo = (date.fromisoformat(b.today) - timedelta(days=PAST_DAYS)).isoformat()
    recorded = getattr(b, "eurlex_dates", {}) or {}
    out: list[dict] = []
    for pid in b.dossier_ids:
        det = b.dossier_detail.get(pid)
        acts = b.dossier_acts.get(pid) or []
        if not det or not acts:
            continue
        names = ((det.get("known_as") or {}).get("names") or []) if len(acts) == 1 else []
        for a in acts:
            dated = act_rows(a, getattr(b, "act_dates", {}).get(a.celex), lo, recorded.get(a.celex))
            if not dated:
                continue
            act = {"celex": a.celex, "label": _act_label(a), "type": a.act_type,
                   "names": _act_names(a, det["title"], names), "url": a.eurlex_url}  # fmt: skip
            where = where_of(a, b)
            for r in dated:
                out.append({"id": f"{a.celex}/{r['kind']}/{r['date']}", **r, "act": act, "dossier_id": pid,
                            "dossier_title": det["title"], "topics": list(det.get("topics") or []), "where": where})  # fmt: skip
    out.sort(key=lambda r: (r["date"], KIND_ORDER[r["kind"]], r["dossier_title"].casefold(), r["act"]["celex"]))
    return {"from": lo, "rows": out}


# ------------------------------------------------------------------------------------------- wording
def where_text(w: dict) -> str:
    """Where, in one or two sentences: "All 27 Member States.", "25 Member States, not Denmark and Ireland. Denmark:
    Under Protocol No 22, …", "25 Member States; whether it binds Denmark and Ireland is not known from our data."
    Never "all" unless all 27 are bound."""
    bound, not_bound, unknown = w["bound"], w["not_bound"], w["unknown"]
    if len(bound) == len(MEMBER_STATES):
        return "All 27 Member States."
    parts = []
    if w.get("note"):  # whom it binds is not recorded (a decision's addressees): the note says so
        parts.append(w["note"])
    if bound:
        names = [MEMBER_STATES[c] for c in bound]
        lead = f"{len(bound)} Member States" if len(bound) > 5 else _join(names)
        if not_bound:
            lead += f", not {_join([MEMBER_STATES[x['country']] for x in not_bound])}"
        parts.append(lead + ".")
    for x in not_bound:
        parts.append(f"{MEMBER_STATES[x['country']]}: {x['reason']}")
    if unknown and not w.get("note"):
        parts.append(f"Whether it binds {_join([MEMBER_STATES[c] for c in unknown])} is not known from our data.")
    return " ".join(parts)


def _name(r: dict) -> str:
    """The file's title, shortened as in the file feeds, with the act's other names: "Artificial Intelligence Act (AI
    Act)"."""
    title = short_title(r["dossier_title"], 120)
    return f"{title} ({', '.join(r['act']['names'])})" if r["act"]["names"] else title


def _short_name(r: dict) -> str:
    """A calendar event's name, short enough to read in a month view: the file's title when it is short (a curated
    title: "Return Regulation"), else the act's shortest name ("AI Act"), else the title shortened."""
    title = r["dossier_title"]
    if len(title) <= 50:
        return title
    names = [n for n in r["act"]["names"] if len(n) <= 50]
    return min(names, key=len) if names else short_title(title, 60)


def what_applies(r: dict) -> str | None:
    """Which provisions the date concerns: checked against the act's text, or the articles EUR-Lex names."""
    if r.get("provisions"):
        return f"What applies: {r['provisions']}."
    if r["articles"]:
        return f"EUR-Lex names {', '.join(r['articles'])} for this date."
    if r["kind"] == "applies" and (r["partial"] or r.get("further")):
        return "EUR-Lex records the date, not which provisions apply from it: the act’s text says."
    return None


def description(r: dict) -> list[str]:
    """What a feed entry or calendar event says, sentence by sentence (the date is the entry's or the event's)."""
    act = r["act"]
    lines = [f"{r['title']}.", *([w] if (w := what_applies(r)) else []), *([r["exceptions"]] if r.get("exceptions") else [])]
    lines.append(f"Act: {act['label']}" + (f" ({', '.join(act['names'])})" if act["names"] else "") + ".")
    lines.append(f"Where: {where_text(r['where'])}")
    chk = r.get("checked")
    if chk and not chk["eurlex"]:
        lines.append("The date is the one the act’s text sets (checked"
                     + (f" {_long_date(chk['reviewed'])}" if chk.get("reviewed") else "")
                     + "); EUR-Lex does not record it.")  # fmt: skip
    elif chk:
        lines.append("Date checked against the act’s text" + (f" on {_long_date(chk['reviewed'])}." if chk.get("reviewed") else "."))
    else:
        lines.append("Date as EUR-Lex records it.")
    return lines


# ------------------------------------------------------------------------------------------- feeds
def stamp(r: dict, b: Any) -> str:
    """When a row's information was last revised: the act's publication (its date, when no publication is recorded),
    or the check of its dates against its text if later. Stable from one build to the next."""
    a = getattr(b, "act", {}).get(r["act"]["celex"])
    xs = [(a.date_publication or a.date_document) if a else None, (r.get("checked") or {}).get("reviewed")]
    return max((x for x in xs if x), default=FIRST_BUILT)


def entry_date(r: dict, b: Any) -> str:
    """When an entry came into the Atom feeds: its date came within 90 days, or, if later, its act was published or its
    dates checked (stamp)."""
    return max((date.fromisoformat(r["date"]) - timedelta(days=QUARTER_DAYS)).isoformat(), stamp(r, b))


def _page(site: str, r: dict) -> str:
    return f"{site}legislation/{quote(r['dossier_id'])}/"


def atom(title: str, subtitle: str, path: str, page: str, sel: list[dict], b: Any, site: str) -> str:
    """One Atom feed of the selection's rows dated in the next 90 days after the build (soonest first)."""
    today = b.today
    end = (date.fromisoformat(today) + timedelta(days=QUARTER_DAYS)).isoformat()
    entries = [r for r in sel if today <= r["date"] <= end]
    # left the feed: the day after the date of an entry that is now past
    left = [(date.fromisoformat(r["date"]) + timedelta(days=1)).isoformat() for r in sel if r["date"] < today]
    updated = max([entry_date(r, b) for r in entries] + left, default=None) or max(
        (stamp(r, b) for r in sel), default=FIRST_BUILT)  # fmt: skip
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{_x(title)}</title>",
        f"  <subtitle>{_x(subtitle)}</subtitle>",
        f"  <id>{_x(TAG_BASE)}/{_x(path)}</id>",
        f'  <link rel="self" type="application/atom+xml" href={_xa(site + "data/" + path)}/>',
        f'  <link rel="alternate" type="text/html" href={_xa(site + page)}/>',
        f"  <updated>{_x(updated)}T00:00:00Z</updated>",
        f"  <author><name>{_x(TITLE)}</name><uri>{_x(site)}</uri></author>",
        f"  <generator>{_x(TITLE)} pipeline</generator>",
        "  <rights>Data © European Union (official EU sources); see the About page for reuse terms.</rights>",
    ]
    for r in entries:
        when = entry_date(r, b)
        summary = " ".join([f"{_long_date(r['date'])}:", *description(r)])
        lines += [
            "  <entry>",
            f"    <title>{_x(_name(r))}: {_x(r['title'])} ({_x(_long_date(r['date']))})</title>",
            f"    <id>{_x(TAG_BASE)}/applies/{_x(r['id'])}</id>",
            f'    <link rel="alternate" type="text/html" href={_xa(_page(site, r))}/>',
            f"    <published>{when}T00:00:00Z</published>",
            f"    <updated>{when}T00:00:00Z</updated>",
            f"    <summary>{_x(summary)}</summary>",
            f"    <category term={_xa(r['kind'])}/>",
            *(f"    <category term={_xa(t)}/>" for t in r["topics"]),
        ]
        if (r.get("source") or {}).get("url"):
            lines.append(f'    <link rel="via" href={_xa(r["source"]["url"])}/>')
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def uid(r: dict) -> str:
    """A calendar event's UID: of the act, kind and date, the same in every calendar, independent of SITE_URL."""
    return f"eu-intel-applies-{r['act']['celex']}-{r['kind']}-{r['date']}@{UID_HOST}"


def calendar(name: str, about: str, sel: list[dict], b: Any, site: str) -> str:
    """One iCalendar file: a whole-day event for each row of the selection."""
    head = [("VERSION", "2.0"), ("PRODID", "-//EU Legislative Intelligence//When new rules apply//EN"),
            ("CALSCALE", "GREGORIAN"), ("X-WR-CALNAME", ical.text(name)), ("X-WR-CALDESC", ical.text(about)),
            ("REFRESH-INTERVAL;VALUE=DURATION", "P1D"), ("X-PUBLISHED-TTL", "P1D")]  # fmt: skip
    events = []
    for r in sel:
        text = "\n".join([*description(r), f"Source: {(r.get('source') or {}).get('label') or 'EUR-Lex'}"
                          f" {(r.get('source') or {}).get('url') or r['act']['url']}"])  # fmt: skip
        events.append([
            ("UID", uid(r)),
            ("DTSTAMP", ical.utc(stamp(r, b))),
            ("DTSTART;VALUE=DATE", ical.day(r["date"])),
            ("DTEND;VALUE=DATE", ical.next_day(r["date"])),
            ("SUMMARY", ical.text(f"{_short_name(r)}: {r['title']}")),
            ("DESCRIPTION", ical.text(text)),
            ("URL", _page(site, r)),
            ("TRANSP", "TRANSPARENT"),
        ])  # fmt: skip
    return ical.calendar(head, events)


def build_feeds(b: Any, data: dict, site_url: str) -> dict[str, str]:
    """The Atom feeds (next 90 days) and calendars (every row) for everything, each topic and each Member State."""
    site = site_url if site_url.endswith("/") else site_url + "/"
    rows_ = data["rows"]
    out: dict[str, str] = {}
    lead = "Dates fixed in EU law from which rules start to apply"
    # (key, page query, name, what the dates are of, rows)
    selections = [("all", "", "When new rules apply", "", rows_)]
    selections += [(f"topics/{t['slug']}", f"?topic={quote(t['slug'])}", f"When new rules apply: {t['label']}",
                    f", on {t['label']}", [r for r in rows_ if t["slug"] in r["topics"]])
                   for t in getattr(b, "topic_list", [])]  # fmt: skip
    selections += [(f"countries/{c}", f"?country={c}", f"When new rules apply in {name}", f" in {name}",
                    [r for r in rows_ if c in r["where"]["bound"] or c in r["where"]["unknown"]])
                   for c, name in sorted(MEMBER_STATES.items())]  # fmt: skip
    for key, query, name, scope, sel in selections:
        page = f"legislation/applies/{query}"
        out[f"{FEED_DIR}/{key}.xml"] = atom(
            f"{name}: the next 90 days – {TITLE}",
            f"{lead}{scope}, from official records (EUR-Lex): entry into force, application, transposition deadlines "
            "and the application of national measures, in the 90 days after each data build.",
            f"{FEED_DIR}/{key}.xml", page, sel, b, site,
        )  # fmt: skip
        out[f"{FEED_DIR}/{key}.ics"] = calendar(
            f"{name} ({TITLE})", f"{lead}{scope}, from official records (EUR-Lex). {site}{page}", sel, b, site
        )
    return out
