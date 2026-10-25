import json

from pipeline import snapshot
from pipeline.models.entities import SourceRef, TrainFile


def _rec(status: str, ts: str) -> TrainFile:
    src = SourceRef(institution="LegislativeTrain", url="https://example.invalid/a", retrieved_at=ts)
    return TrainFile(url="https://example.invalid/a", title="A", status=status, source=src)


def test_unchanged_records_keep_previous_retrieved_at(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    snapshot.write_records("t", "files", [_rec("Adopted", "2026-01-01T00:00:00Z")])
    snapshot.write_records("t", "files", [_rec("Adopted", "2026-02-01T00:00:00Z")])
    data = json.loads((tmp_path / "t" / "files.json").read_text())
    assert data[0]["source"]["retrieved_at"] == "2026-01-01T00:00:00Z"


def test_changed_records_get_new_retrieved_at(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    snapshot.write_records("t", "files", [_rec("Tabled", "2026-01-01T00:00:00Z")])
    snapshot.write_records("t", "files", [_rec("Adopted", "2026-02-01T00:00:00Z")])
    data = json.loads((tmp_path / "t" / "files.json").read_text())
    assert data[0]["status"] == "Adopted"
    assert data[0]["source"]["retrieved_at"] == "2026-02-01T00:00:00Z"


def test_upsert_and_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    snapshot.write_records("t", "files", [_rec("Tabled", "2026-01-01T00:00:00Z")])
    other = TrainFile(
        url="https://example.invalid/b",
        title="B",
        status="Blocked",
        source=SourceRef(
            institution="LegislativeTrain",
            url="https://example.invalid/b",
            retrieved_at="2026-01-02T00:00:00Z",
        ),
    )
    n = snapshot.upsert_records(
        "t", "files", TrainFile, [_rec("Adopted", "2026-02-01T00:00:00Z"), other], id_of=lambda r: r.url
    )
    assert n == 2
    recs = {r.url: r.status for r in snapshot.read_records("t", "files", TrainFile)}
    assert recs == {"https://example.invalid/a": "Adopted", "https://example.invalid/b": "Blocked"}
    snapshot.write_state("t", {"pending": ["x"]})
    assert snapshot.read_state("t") == {"pending": ["x"]}
