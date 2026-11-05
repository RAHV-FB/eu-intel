"""The open dataset (pipeline/analysis/opendata.py) on the TEST-ONLY build fixture (tests/fixtures/build): its CSV
tables, their documentation in datapackage.json, the crosswalk, and the release package."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from pipeline.analysis import opendata
from pipeline.build import build
from pipeline.contract import Contract
from pipeline.validate import check as validate_check

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "build"
TODAY = "2026-10-22"


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("opendata")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    o = base / "public"
    assert build(out=o, snapshot=base / "snapshot", curated=FIX / "curated", state=base / "state", today=TODAY,
                 strict=True) == 0  # fmt: skip
    return o


def rows(out: Path, table: str) -> list[dict[str, str]]:
    text = (out / "open" / f"{table}.csv").read_bytes().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def header(out: Path, table: str) -> list[str]:
    return next(csv.reader(io.StringIO((out / "open" / f"{table}.csv").read_text(encoding="utf-8"), newline="")))


def package(out: Path) -> dict:
    return json.loads((out / "open" / "datapackage.json").read_text(encoding="utf-8"))


def load(out: Path, rel: str):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def copy_open(out: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "open"
    shutil.copytree(out / "open", dest)
    return dest


def rewrite(open_dir: Path, table: str, edit) -> None:
    """Edit a table's rows (a list of lists, the header first) and keep datapackage.json's size, hash and row count
    in step, so that only the edit is wrong."""
    path = open_dir / f"{table}.csv"
    records = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))
    edit(records)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(records)
    raw = buf.getvalue().encode("utf-8")
    path.write_bytes(raw)
    dp = json.loads((open_dir / "datapackage.json").read_text(encoding="utf-8"))
    import hashlib

    r = next(r for r in dp["resources"] if r["name"] == table)
    r.update(bytes=len(raw), hash="sha256:" + hashlib.sha256(raw).hexdigest(), rows=len(records) - 1)
    (open_dir / "datapackage.json").write_text(json.dumps(dp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the files


def test_every_table_is_written_with_a_readme_and_a_descriptor(out: Path):
    names = [t.name for t in opendata.tables()]
    assert names == ["files", "acts", "ep_votes", "council_votes", "council_positions", "transposition",
                     "national_measures", "infringements", "crosswalk"]  # fmt: skip
    written = sorted(p.name for p in (out / "open").iterdir())
    assert written == sorted([*(f"{n}.csv" for n in names), "datapackage.json", "README.md"])
    assert opendata.check(out / "open") == []
    readme = (out / "open" / "README.md").read_text(encoding="utf-8")
    for n in names:
        assert f"[`{n}.csv`]({n}.csv)" in readme
    assert "CC BY 4.0" in readme and "Licence and attribution" in readme


def test_the_csv_files_are_rfc_4180_utf_8_with_one_header_row(out: Path):
    for t in opendata.tables():
        raw = (out / "open" / t.path).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), t.path  # no byte-order mark in the dataset's files
        assert raw.endswith(b"\r\n") and b"\n" not in raw.replace(b"\r\n", b""), t.path  # CRLF only (no line break in a value here)
        assert header(out, t.name) == t.columns
    # values with a comma, a double quote, a line break and several values, as RFC 4180 writes them
    got = opendata.to_csv(["a", "b", "c", "d", "e"], [
        {"a": 'He said "no", then left', "b": "line\nbreak", "c": None, "d": True, "e": ["2025-01-01", "2026-01-01"]},
        {"a": "plain", "b": "", "c": 3, "d": False, "e": []},
    ])  # fmt: skip
    assert got == (b'a,b,c,d,e\r\n"He said ""no"", then left","line\nbreak",,true,2025-01-01;2026-01-01\r\n'
                   b"plain,,3,false,\r\n")  # fmt: skip
    assert list(csv.reader(io.StringIO(got.decode(), newline="")))[1] == [
        'He said "no", then left', "line\nbreak", "", "true", "2025-01-01;2026-01-01"
    ]
    with pytest.raises(ValueError, match="do not match"):  # a row with a field the table does not have
        opendata.to_csv(["a"], [{"a": 1, "z": 2}])


def test_the_datapackage_fields_match_the_csv_headers(out: Path):
    dp = package(out)
    assert dp["profile"] == "tabular-data-package" and dp["licenses"] == [opendata.LICENSE]
    assert dp["licenses"][0]["name"] == "CC-BY-4.0" and "CC BY 4.0" in dp["attribution"]
    for r in dp["resources"]:
        assert r["profile"] == "tabular-data-resource" and r["path"] == f"{r['name']}.csv" and r["format"] == "csv"
        assert [f["name"] for f in r["schema"]["fields"]] == header(out, r["name"])
        assert r["rows"] == len(rows(out, r["name"]))
        for f in r["schema"]["fields"]:  # every field has a type and says what it holds, in a sentence
            assert f["type"] in ("string", "integer", "boolean", "date"), (r["name"], f)
            assert f["description"].endswith(".") and len(f["description"].split()) >= 3, (r["name"], f)
        assert r["sources"] and all(s["title"] and s["path"].startswith("https://") for s in r["sources"])
    # the sources with their attribution, from the site's own statement of each source's terms
    meta = load(out, "meta.json")
    assert [(s["id"], s["attribution"]) for s in dp["sources"]] == [(s["id"], s["licence"]) for s in meta["sources"]]
    # the descriptor is what the public data contract says it is (src/types/data.ts DataPackage)
    assert Contract.load().check_value(dp, "DataPackage") == []


def test_primary_and_foreign_keys_are_declared_where_real_and_hold(out: Path):
    keys = {r["name"]: (r["schema"]["primaryKey"], r["schema"]["foreignKeys"]) for r in package(out)["resources"]}
    assert keys["files"] == (["id"], [])
    assert keys["acts"] == (["celex"], [{"fields": ["file_id"], "reference": {"resource": "files", "fields": ["id"]}}])
    assert keys["council_positions"][0] == ["vote_id", "country"]
    assert keys["transposition"] == (["celex", "country"], [
        {"fields": ["celex"], "reference": {"resource": "acts", "fields": ["celex"]}},
        {"fields": ["file_id"], "reference": {"resource": "files", "fields": ["id"]}},
    ])  # fmt: skip
    assert keys["national_measures"][1] == [{"fields": ["directive"], "reference": {"resource": "acts", "fields": ["celex"]}}]
    assert keys["infringements"] == (["id"], [])  # its celex may name an act outside the dataset: no foreign key
    for r in package(out)["resources"]:
        data = rows(out, r["name"])
        pk = [tuple(x[k] for k in r["schema"]["primaryKey"]) for x in data]
        assert len(pk) == len(set(pk)), r["name"]
        for fk in r["schema"]["foreignKeys"]:
            target = {x[fk["reference"]["fields"][0]] for x in rows(out, fk["reference"]["resource"])}
            assert {x[fk["fields"][0]] for x in data if x[fk["fields"][0]]} <= target, (r["name"], fk)


def test_every_identifier_in_the_crosswalk_exists_in_its_table(out: Path):
    cw = rows(out, "crosswalk")
    assert {x["link"] for x in cw} == {"procedure_act", "vote_procedure", "council_vote_procedure",
                                        "act_national_measure", "infringement_act"}  # fmt: skip (no ELI, no Council document in the fixture)
    listed = {kind: {x[field] for x in rows(out, table)} for kind, (table, field) in opendata.CROSSWALK_IDS.items()}
    for x in cw:
        assert x["from_id"] in listed[x["from_type"]], x
        assert x["to_id"] in listed[x["to_type"]], x
        assert x["source"] and all(s in opendata.CROSSWALK_SOURCES for s in x["source"].split(";")), x
    # each link once, with every record that establishes it: the procedure the act names (EUR-Lex) and the act the
    # procedure file lists (Legislative Observatory)
    assert len({tuple(x[k] for k in ("from_type", "from_id", "link", "to_type", "to_id")) for x in cw}) == len(cw)
    act = {x["to_id"]: x["source"] for x in cw if x["link"] == "procedure_act"}
    assert act == {"32099R0001": "EUR-Lex", "32099L0003": "EUR-Lex", "32099L0009": "EUR-Lex;Legislative Observatory"}
    assert ("ep_vote", "V1", "procedure", "2099/0001(COD)") in {(x["from_type"], x["from_id"], x["to_type"], x["to_id"]) for x in cw}
    assert {(x["from_id"], x["to_id"]) for x in cw if x["link"] == "act_national_measure"} == {
        ("32099L0003", "M1"), ("32099L0003", "M2")}  # fmt: skip
    assert {(x["from_id"], x["to_id"]) for x in cw if x["link"] == "infringement_act"} == {("INFR(2099)0001", "32099L0003")}


def test_the_tables_say_what_the_built_files_say(out: Path):
    assert [x["id"] for x in rows(out, "files")] == sorted(d["id"] for d in load(out, "dossiers/index.json"))
    assert {x["id"] for x in rows(out, "ep_votes")} == {v["id"] for v in load(out, "votes/index.json")}
    assert {x["id"] for x in rows(out, "council_votes")} == {c["id"] for c in load(out, "council/index.json")}
    d1 = {x["id"]: x for x in rows(out, "files")}["2099-0001"]
    detail = load(out, "dossiers/2099-0001.json")
    assert (d1["title"], d1["stage"], d1["status_label"], d1["celex"]) == (
        detail["title"], detail["stage"], detail["status_label"], ";".join(detail["celex"]))
    assert d1["url"] == "https://rahv-fb.github.io/eu-intel/legislation/2099-0001/" and d1["featured"] == "true"
    # the Council's positions in long form, counted on the vote's row
    c1 = {x["id"]: x for x in rows(out, "council_votes")}["C1"]
    positions = [x for x in rows(out, "council_positions") if x["vote_id"] == "C1"]
    assert len(positions) == 27 and (c1["states_for"], c1["states_against"], c1["states_abstain"]) == ("25", "1", "1")
    assert {x["country"]: x["position_label"] for x in positions}["PL"] == "Abstained"
    # transposition: one row per directive and Member State, as the file's table gives it; the measures counted are the
    # rows of national_measures.csv
    tr = rows(out, "transposition")
    table = load(out, "dossiers/2099-0003.json")["implementation"]
    mine = [x for x in tr if x["celex"] == "32099L0003"]
    assert len(mine) == 27 and [(x["country"], x["status"], int(x["measures"])) for x in mine] == [
        (c["country"], c["status"], c["measures"]) for c in table["countries"]]  # fmt: skip
    measures = rows(out, "national_measures")
    for x in tr:
        assert int(x["measures"]) == sum(1 for m in measures if (m["directive"], m["country"]) == (x["celex"], x["country"]))
    countries = {x["country"]: x for x in mine}
    assert countries["DE"]["status_label"] == "Measures notified" and countries["AT"]["status"] == "none_found"
    # the infringement cases of the country pages
    cases = {i["id"] for c in load(out, "countries/index.json") for i in load(out, f"countries/{c['code']}.json")["infringements"]}
    assert {x["id"] for x in rows(out, "infringements")} == cases


def test_enumerations_and_labels_are_the_sites(out: Path):
    contract = Contract.load()
    fields = {(r["name"], f["name"]): f for r in package(out)["resources"] for f in r["schema"]["fields"]}

    def literals(name: str) -> list[str]:
        return [x[1] for x in contract.alternatives(("ref", name)) if x[0] == "lit"]

    assert fields[("files", "stage")]["constraints"]["enum"] == literals("LifecycleStage")
    assert fields[("transposition", "status")]["constraints"]["enum"] == literals("TranspositionStatus")
    assert fields[("council_positions", "position")]["constraints"]["enum"] == literals("CouncilPosition")
    assert fields[("ep_votes", "outcome")]["constraints"]["enum"] == literals("VoteOutcome")
    assert fields[("council_votes", "voting_rule")]["constraints"]["enum"] == ["qmv", "unanimity", "simple_majority", "unknown"]
    assert fields[("ep_votes", "outcome_basis")]["constraints"]["enum"] == ["published", "minutes", "derived"]
    # the labels are the site's: src/features/legislation/labels.ts and src/features/votes/labels.ts
    labels = (ROOT / "src" / "features" / "legislation" / "labels.ts").read_text(encoding="utf-8")
    block = re.search(r"TRANSPOSITION_LABEL: Record<TranspositionStatus, string> = \{(.*?)\};", labels, re.S).group(1)
    assert dict(re.findall(r"(\w+): '([^']*)'", block)) == opendata.TRANSPOSITION_LABEL
    votes = (ROOT / "src" / "features" / "votes" / "labels.ts").read_text(encoding="utf-8")
    block = re.search(r"POSITION_LABEL: Record<BallotPosition, string> = \{(.*?)\};", votes, re.S).group(1)
    assert dict(re.findall(r"(\w+): '([^']*)'", block)) | {"not_participating": "Not participating"} == opendata.POSITION_LABEL
    # a field of several dates is a string of ISO dates: Frictionless 1.0 has no list type
    dates = fields[("acts", "application_dates")]
    assert dates["type"] == "string" and dates["constraints"]["pattern"] == opendata.DATE_LIST
    assert {x["application_dates"] for x in rows(out, "acts")} >= {"2025-06-01;2027-01-01"}


def test_the_caveats_of_the_data_are_in_the_field_descriptions(out: Path):
    fields = {(r["name"], f["name"]): f["description"] for r in package(out)["resources"] for f in r["schema"]["fields"]}
    status = fields[("transposition", "status")]
    assert "`none_found`: no measures found in the available dataset" in status
    assert "not proof of non-transposition" in status
    assert "does not show that transposition is complete or correct" in status
    assert "not a measure of transposition" in fields[("transposition", "measures")]
    measures = next(r for r in package(out)["resources"] if r["name"] == "national_measures")["description"]
    assert "not an assessment" in measures
    assert "not an abstention" in fields[("council_positions", "position")]
    assert "not of a law" in fields[("ep_votes", "outcome")]
    assert "does not adopt the act" in fields[("council_votes", "vote_on")]
    readme = (out / "open" / "README.md").read_text(encoding="utf-8")
    assert "not that the country has not transposed the" in readme and "not an assessment" in readme


def test_the_legislative_train_label_is_withdrawn_with_its_copy(out: Path):
    blocked = {x["id"]: x for x in rows(out, "files")}["2099-0002"]
    assert (blocked["officially_blocked"], blocked["blocked_label"]) == ("true", "Blocked")
    meta = load(out, "meta.json")
    train = next(s for s in meta["sources"] if s["id"] == "train")
    fetched = train["fetched_at"][:10]
    from datetime import date, timedelta

    day = date.fromisoformat(fetched)
    assert opendata._labels_current(meta, "train", (day + timedelta(days=41)).isoformat())
    assert not opendata._labels_current(meta, "train", (day + timedelta(days=42)).isoformat())  # its end: past 42 days
    assert not opendata._labels_current({"sources": [{**train, "fetched_at": None}]}, "train", fetched)


# ---------------------------------------------------------------- determinism and the release


def test_the_content_hash_covers_rows_and_schema_but_not_the_day_or_the_retrieval(out: Path):
    dp = package(out)
    h = opendata.content_hash(dp)
    later = copy.deepcopy(dp)
    later.update(as_of="2026-12-01", snapshot_at="2026-12-01T05:00:00Z", core_data_at="2026-12-01T05:00:00Z")
    later["sources"][0]["retrieved_at"] = "2026-12-01T05:00:00Z"
    assert opendata.content_hash(later) == h
    changed = copy.deepcopy(dp)
    changed["resources"][0]["hash"] = "sha256:" + "0" * 64  # a row changed
    assert opendata.content_hash(changed) != h
    described = copy.deepcopy(dp)
    described["resources"][0]["schema"]["fields"][0]["description"] += " More."
    assert opendata.content_hash(described) != h


def test_the_release_package_is_a_zip_of_the_dataset_with_notes_that_carry_its_hash(out: Path, tmp_path: Path):
    zip1 = opendata.package(out / "open", tmp_path / "a", "data-2026-10-22", "a" * 40)
    zip2 = opendata.package(out / "open", tmp_path / "b", "data-2026-10-22")
    assert zip1.name == "eu-intel-data-2026-10-22.zip" and zip1.read_bytes() == zip2.read_bytes()  # deterministic
    with zipfile.ZipFile(zip1) as z:
        names = z.namelist()
        assert names[:2] == ["eu-intel-data-2026-10-22/README.md", "eu-intel-data-2026-10-22/datapackage.json"]
        assert sorted(names[2:]) == sorted(f"eu-intel-data-2026-10-22/{t.path}" for t in opendata.tables())
        assert z.read("eu-intel-data-2026-10-22/files.csv") == (out / "open" / "files.csv").read_bytes()
    assert (tmp_path / "a" / "datapackage.json").read_bytes() == (out / "open" / "datapackage.json").read_bytes()
    notes = (tmp_path / "a" / "notes.md").read_text(encoding="utf-8")
    h = opendata.content_hash(package(out))
    assert notes.rstrip().endswith(f"<!-- {opendata.HASH_MARKER}: {h} -->")
    assert "**Data current to**" in notes and "**Statuses as of** 22 October 2026" in notes and "a" * 40 in notes
    for r in package(out)["resources"]:
        assert f"| `{r['path']}` | {r['rows']:,} | {r['title']} |" in notes
    with pytest.raises(ValueError, match="not a data release tag"):
        opendata.package(out / "open", tmp_path / "c", "v1.0")
    assert opendata.main(["content-hash"], out / "open") == 0


def test_the_cli_refuses_an_inconsistent_dataset(out: Path, tmp_path: Path, capsys):
    o = copy_open(out, tmp_path)
    (o / "acts.csv").write_bytes((o / "acts.csv").read_bytes() + b"x\r\n")
    assert opendata.main(["content-hash"], o) == 1
    assert "acts.csv: its size or SHA-256 differs from datapackage.json" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("table", "edit", "problem"),
    [
        ("files", lambda r: r[0].__setitem__(1, "reference"), "files.csv: header"),
        ("acts", lambda r: r.append(r[1]), "acts.csv: primary key ['celex'] is not unique"),
        ("acts", lambda r: r[1].__setitem__(r[0].index("file_id"), "2099-9999"), "acts.csv: file_id ['2099-9999'] not in files.id"),
        ("ep_votes", lambda r: r[1].__setitem__(r[0].index("for"), "many"), "ep_votes.csv line 2, for: 'many' is not a integer"),
        ("files", lambda r: r[1].__setitem__(r[0].index("stage"), "passed"), "files.csv line 2, stage: 'passed' is not one of its values"),
        ("files", lambda r: r[1].__setitem__(r[0].index("title"), ""), "files.csv line 2, title: required value missing"),
        ("crosswalk", lambda r: r.append(["procedure", "2099/0777(COD)", "procedure_act", "celex", "32099R0001", "EUR-Lex"]),
         "crosswalk.csv: 1 from_id not in their table (e.g. [('procedure', '2099/0777(COD)')])"),
    ],
)
def test_the_check_finds_what_does_not_match_the_descriptor(out: Path, tmp_path: Path, table, edit, problem):
    o = copy_open(out, tmp_path)
    rewrite(o, table, edit)
    problems = opendata.check(o)
    assert any(p.startswith(problem) for p in problems), problems


def test_validate_built_fails_on_an_open_dataset_that_does_not_match_its_descriptor(out: Path, tmp_path: Path):
    pub = tmp_path / "public"
    shutil.copytree(out, pub)
    assert validate_check(FIX, public=pub, today=TODAY, built=True).errors == []
    rewrite(pub / "open", "council_positions", lambda r: r[1].__setitem__(2, "veto"))
    rep = validate_check(FIX, public=pub, today=TODAY, built=True)
    assert rep.errors == ["public open/council_positions.csv line 2, position: 'veto' is not one of its values"]
    assert rep.errors_by_check == {"open-data": 1}
    (pub / "open" / "datapackage.json").unlink()  # a build without the dataset is incomplete
    assert validate_check(FIX, public=pub, today=TODAY, built=True).errors == [
        "public/data/open/datapackage.json is missing (run `python -m pipeline build`)"
    ]
