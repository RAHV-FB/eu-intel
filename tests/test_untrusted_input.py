"""What the sources send is untrusted input: an id becomes a file name, a spreadsheet is a zip of XML, a voting sheet is
a PDF rendered to an image. Each of these on crafted input."""

from __future__ import annotations

import io
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from pipeline.build import build

FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2025-01-20"


def craft(tmp_path: Path, edits: dict[str, list[tuple[str, str]]]) -> Path:
    """The fixture snapshot with text replacements applied to some of its files."""
    snap = tmp_path / "snapshot"
    shutil.copytree(FIX / "snapshot", snap)
    for rel, pairs in edits.items():
        p = snap / rel
        text = p.read_text(encoding="utf-8")
        for old, new in pairs:
            assert old in text, (rel, old)
            text = text.replace(old, new)
        p.write_text(text, encoding="utf-8")
    return snap


@pytest.mark.parametrize("bad", ["../../../escaped-vote", "../index"])
def test_an_id_from_a_source_cannot_write_outside_its_place_in_the_built_data(tmp_path, bad):
    # public/data/votes/<id>.json: an EP vote id "../../../x" wrote x.json three directories up (outside public/data),
    # "../index" over public/data/index.json; the build now stops instead
    snap = craft(tmp_path, {
        "ep_votes/votes.json": [('"id": "V1"', f'"id": "{bad}"')],
        "ep_votes/ballots.json": [('"vote_id": "V1"', f'"vote_id": "{bad}"')],
    })  # fmt: skip
    out = tmp_path / "a" / "b" / "public"
    with pytest.raises(ValueError, match="not a path inside"):
        build(out=out, snapshot=snap, curated=FIX / "curated", state=tmp_path / "state", today=TODAY, strict=False)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("escaped*")) == []
    assert not out.exists()  # nothing was swapped in


# ------------------------------------------------------------------------------- spreadsheets (a zip of XML)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SHEET = (f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row>'
         f'<row r="2"><c r="A2" t="s"><v>1</v></c></row></sheetData></worksheet>')  # fmt: skip


def xlsx(shared: str, sheet: str | bytes = SHEET) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return b.getvalue()


def test_a_spreadsheet_cannot_read_local_files_or_expand_entities():
    # the Commission's infringement export (implementation.py read_xlsx_rows) is parsed with lxml's default parser:
    # external entities (XXE) are not resolved, and an entity bomb stops at once (lxml >= 5.0; pyproject: lxml>=5.2)
    from lxml import etree

    from pipeline.sources.implementation import read_xlsx_rows

    good = f'<sst xmlns="{NS}"><si><t>Case</t></si><si><t>INFR(2024)2001</t></si></sst>'
    assert read_xlsx_rows(xlsx(good)) == [{"Case": "INFR(2024)2001"}]
    xxe = (f'<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
           f'<sst xmlns="{NS}"><si><t>Case</t></si><si><t>&x;</t></si></sst>')  # fmt: skip
    with pytest.raises(etree.XMLSyntaxError, match="Entity 'x' not defined"):
        read_xlsx_rows(xlsx(xxe))
    lol = ('<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY a "aaaaaaaaaa">'
           + "".join(f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(9))
           + f']><sst xmlns="{NS}"><si><t>Case</t></si><si><t>&j;</t></si></sst>')  # fmt: skip
    with pytest.raises(etree.XMLSyntaxError, match="amplification"):
        read_xlsx_rows(xlsx(lol))


def with_declared_size(z: bytes, name: str, size: int) -> bytes:
    """The zip with `name`'s uncompressed size in the central directory replaced (a zip that lies about it)."""
    b, key = bytearray(z), name.encode()
    at = next(i for i in range(len(b)) if b[i : i + 4] == b"PK\x01\x02" and b[i + 46 : i + 46 + len(key)] == key)
    b[at + 24 : at + 28] = struct.pack("<I", size)
    return bytes(b)


def test_a_spreadsheet_that_inflates_beyond_any_real_export_is_refused_before_it_is_inflated():
    # a member of 2 GB from 2 MB of zip was inflated whole into memory (z.read), then parsed: a source could exhaust the
    # runner's memory and stop every source after it in the run
    from pipeline.sources import implementation

    limit = implementation.XLSX_MEMBER_MAX
    spaces = b" " * (limit + 1)
    bomb = xlsx(f'<sst xmlns="{NS}"/>', spaces)
    assert len(bomb) < limit // 500  # about a thousandth of what it inflates to
    with pytest.raises(ValueError, match="larger than"):
        implementation.read_xlsx_rows(bomb)
    # a member that says it is small: zipfile inflates no more than it declares, and the checksum then fails
    lying = with_declared_size(bomb, "xl/worksheets/sheet1.xml", 1000)
    assert zipfile.ZipFile(io.BytesIO(lying)).getinfo("xl/worksheets/sheet1.xml").file_size == 1000
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        implementation.read_xlsx_rows(lying)
