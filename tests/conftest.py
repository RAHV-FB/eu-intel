"""Shared pytest configuration.

- Offline by default: tests not marked ``@pytest.mark.network`` cannot open non-loopback connections or
  resolve remote host names, so CI never depends on (or hammers) official EU endpoints. Run the live
  checks explicitly with ``pytest -m network``.
- In CI (``CI`` env var set) the session fails if any test modified the committed snapshot under
  ``data/snapshot/``; tests that exercise writers must monkeypatch ``pipeline.snapshot.SNAPSHOT`` to
  ``tmp_path``.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAPSHOT_DIR = ROOT / "data" / "snapshot"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


class NetworkAccessInOfflineTest(RuntimeError):
    pass


def _is_local(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    return isinstance(host, str) and (host in _LOCAL_HOSTS or host.startswith("127."))


@pytest.fixture(autouse=True)
def _offline_unless_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("network"):
        return
    # A local forward proxy would otherwise make remote requests look like loopback connections.
    proxies = set()
    for var in _PROXY_VARS:
        if os.environ.get(var):
            u = urlsplit(os.environ[var])
            proxies.add(u.port)
            monkeypatch.delenv(var)
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def refuse(target: object) -> NetworkAccessInOfflineTest:
        return NetworkAccessInOfflineTest(
            f"{request.node.nodeid} tried to reach {target!r}; offline tests must use fixtures "
            "(or mark the test @pytest.mark.network)"
        )

    def allowed(self: socket.socket, address: object) -> bool:
        if self.family == getattr(socket, "AF_UNIX", None):
            return True
        return isinstance(address, tuple) and _is_local(address[0]) and address[1] not in proxies

    def connect(self: socket.socket, address: object) -> None:
        if allowed(self, address):
            return real_connect(self, address)
        raise refuse(address)

    def connect_ex(self: socket.socket, address: object) -> int:
        if allowed(self, address):
            return real_connect_ex(self, address)
        raise refuse(address)

    def getaddrinfo(host: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if host is None or _is_local(host):
            return real_getaddrinfo(host, *args, **kwargs)
        raise refuse(host)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def fixtures_dir() -> Path:
    """tests/fixtures/ (per-source subdirectories of trimmed real API responses)."""
    return FIXTURES


# ---------------------------------------------------------------- committed-snapshot guard (CI only)

_snapshot_state: dict[str, tuple[int, int]] | None = None


def _snapshot_fingerprint() -> dict[str, tuple[int, int]]:
    if not SNAPSHOT_DIR.is_dir():
        return {}
    return {
        p.relative_to(SNAPSHOT_DIR).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in SNAPSHOT_DIR.rglob("*")
        if p.is_file()
    }


def pytest_sessionstart(session: pytest.Session) -> None:
    global _snapshot_state
    if os.environ.get("CI"):
        _snapshot_state = _snapshot_fingerprint()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _snapshot_state is None:
        return
    after = _snapshot_fingerprint()
    changed = sorted(k for k in set(_snapshot_state) | set(after) if _snapshot_state.get(k) != after.get(k))
    if changed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        msg = "tests modified the committed snapshot (data/snapshot/): " + ", ".join(changed[:10])
        if reporter:
            reporter.write_line(f"ERROR: {msg}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
