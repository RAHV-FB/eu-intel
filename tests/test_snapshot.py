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
