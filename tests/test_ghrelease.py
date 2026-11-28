"""Tests for the checksum-verified GitHub-release installer.

Everything network-shaped is stubbed: the release lookup, the checksum
file, and the asset payload are in-memory (a real tar.gz is built in
the test). The promises pinned here: verified-or-refused, sha256
mismatch refusal, archive extraction, and the Linux-only boundary.
"""
from __future__ import annotations

import io
import json
import platform
import tarfile
from pathlib import Path

import pytest

from polycheck.tools import ghrelease


def _fake_release(assets: dict[str, bytes]):
    """A requests.Response stand-in via a simple object."""
    class _Resp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return json.loads(self._payload)

        @property
        def content(self):
            return self._payload

    release = {
        "tag_name": "v1.2.3",
        "assets": [
            {"name": name, "browser_download_url": f"https://dl/{name}"}
            for name in assets
        ],
    }
    return _Resp(json.dumps(release).encode())


def _payload_res(payload: bytes):
    class _Resp:
        def __init__(self, payload: bytes):
            self.content = payload

        def raise_for_status(self):
            return None

    return _Resp(payload)


def _tar_gz(binary_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=binary_name)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


@pytest.mark.skipif(platform.system() != "Linux", reason="verified installs are Linux-only in v1")
def test_verified_install_extracts_and_places_binary(
    tmp_path: Path, monkeypatch
):
    binary = b"#!/bin/sh\necho actionlint\n"
    asset = _tar_gz("actionlint", binary)
    sha = __import__("hashlib").sha256(asset).hexdigest()
    payload = {
        "release": _fake_release({
            "actionlint_1.2.3_linux_amd64.tar.gz": b"",
            "actionlint_1.2.3_checksums.txt": b"",
        }),
        "asset": _payload_res(asset),
        "checksum": _payload_res(
            f"{sha}  actionlint_1.2.3_linux_amd64.tar.gz\n".encode()
        ),
    }

    def fake_get(url, timeout=None):
        if "releases/latest" in url:
            return payload["release"]
        if url.endswith("checksums.txt"):
            return payload["checksum"]
        return payload["asset"]

    monkeypatch.setattr(ghrelease.requests, "get", fake_get)

    ok, message = ghrelease.install_github_release(
        "rhysd/actionlint",
        "actionlint_{version}_{os}_{arch}.tar.gz",
        "actionlint_{version}_checksums.txt",
        "actionlint",
        tmp_path / "bin",
    )

    assert ok, message
    installed = tmp_path / "bin" / "actionlint"
    assert installed.read_bytes() == binary
    assert installed.stat().st_mode & 0o111
    assert "sha256 verified" in message


@pytest.mark.skipif(platform.system() != "Linux", reason="verified installs are Linux-only in v1")
def test_checksum_mismatch_is_refused(tmp_path: Path, monkeypatch):
    asset = _tar_gz("actionlint", b"evil-bytes")
    payload = {
        "release": _fake_release({
            "actionlint_1.2.3_linux_amd64.tar.gz": b"",
            "actionlint_1.2.3_checksums.txt": b"",
        }),
        "asset": _payload_res(asset),
        "checksum": _payload_res(
            f"{'0' * 64}  actionlint_1.2.3_linux_amd64.tar.gz\n".encode()
        ),
    }

    def fake_get(url, timeout=None):
        if "releases/latest" in url:
            return payload["release"]
        if url.endswith("checksums.txt"):
            return payload["checksum"]
        return payload["asset"]

    monkeypatch.setattr(ghrelease.requests, "get", fake_get)

    ok, message = ghrelease.install_github_release(
        "rhysd/actionlint",
        "actionlint_{version}_{os}_{arch}.tar.gz",
        "actionlint_{version}_checksums.txt",
        "actionlint",
        tmp_path / "bin",
    )

    assert not ok
    assert "SHA-256 mismatch" in message
    assert not (tmp_path / "bin" / "actionlint").exists()


@pytest.mark.skipif(platform.system() != "Linux", reason="verified installs are Linux-only in v1")
def test_missing_checksum_file_is_refused(tmp_path: Path, monkeypatch):
    payload = {
        "release": _fake_release({"tool-linux-amd64": b""}),
        "asset": _payload_res(b"binary"),
    }

    def fake_get(url, timeout=None):
        if "releases/latest" in url:
            return payload["release"]
        return payload["asset"]

    monkeypatch.setattr(ghrelease.requests, "get", fake_get)

    ok, message = ghrelease.install_github_release(
        "example/tool", "tool-linux-amd64", None, "tool",
        tmp_path / "bin",
    )

    assert not ok
    assert "no checksum" in message
    assert "install manually" in message


def test_non_linux_is_refused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ghrelease.platform, "system", lambda: "Darwin")
    ok, message = ghrelease.install_github_release(
        "example/tool", "tool-{os}-{arch}", None, "tool", tmp_path / "bin"
    )
    assert not ok
    assert "Linux-only" in message


@pytest.mark.skipif(
    platform.system() != "Linux", reason="v1 verified installs are Linux-only"
)
def test_hadolint_and_actionlint_are_agent_installable_on_linux():
    from polycheck.tools.actionlint import ActionlintTool
    from polycheck.tools.hadolint import HadolintTool

    assert HadolintTool().can_auto_install() is True
    assert ActionlintTool().can_auto_install() is True
    assert HadolintTool().install_hint()
