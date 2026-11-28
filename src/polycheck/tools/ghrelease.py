"""Checksum-verified installs from GitHub release assets.

The consent class this module serves: a release download is
package-manager-equivalent ONLY when its published checksum verifies.
So the rule is **verified or refused** — if a release publishes a
checksum file, the binary is fetched, hashed, compared, and only then
installed to ``~/.local/bin``; if it does not, the install is refused
with the manual path instead of shipping an unverified binary. That is
the design decision behind removing unverified GitHub-release installs
(can_auto_install docstring, tools.base) — this module is the
checksum-gated way back in.

v1 is Linux-only for the adapters that use it (hadolint, actionlint):
their macOS names differ per release and brew covers macOS; refusals
say so explicitly rather than guessing asset names.
"""
from __future__ import annotations

import hashlib
import platform
import tarfile
from pathlib import Path

import requests

_GITHUB_API = "https://api.github.com"
_DEFAULT_TIMEOUT = 120


def _linux_slug() -> tuple[str, str]:
    """(arch-slug, machine) for the running interpreter, Linux-only."""
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)
    return arch, machine


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checksum_matches(checksum_bytes: bytes, asset_name: str, digest: str) -> bool:
    """Parse a `sha256sum`-style file (hex, space(s), filename)."""
    for line in checksum_bytes.decode("utf-8", errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == asset_name:
            return parts[0].strip().lower() == digest
    return False


def install_github_release(
    owner_repo: str,
    asset_template: str,
    checksum_template: str | None,
    binary_name: str,
    bin_dir: Path,
    timeout: int = _DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """Download, checksum-verify, and install one release binary.

    ``asset_template`` / ``checksum_template`` may contain ``{version}``
    (tag without leading ``v``) and ``{arch}`` (amd64/arm64). Returns
    ``(success, message)`` — the message is LLM-readable either way.
    """
    if platform.system() != "Linux":
        machine = platform.machine().lower()
        return False, (
            f"{binary_name}: verified GitHub-release install is Linux-only "
            f"in v1 (this is {platform.system()} {machine}) - install "
            "manually via your package manager (brew/scoop) or the "
            "project's releases page"
        )

    arch, _ = _linux_slug()
    try:
        release = requests.get(
            f"{_GITHUB_API}/repos/{owner_repo}/releases/latest",
            timeout=timeout,
        )
        release.raise_for_status()
        data = release.json()
    except requests.RequestException as exc:
        return False, f"{binary_name}: release lookup failed: {exc}"

    tag = str(data.get("tag_name", "")).lstrip("v")
    fmt = {"version": tag, "arch": arch, "os": "linux"}
    asset_name = asset_template.format(**fmt)

    assets = {
        a["name"]: a["browser_download_url"] for a in data.get("assets", [])
    }
    asset_url = assets.get(asset_name)
    if not asset_url:
        return False, (
            f"{binary_name}: no release asset '{asset_name}' in {tag} "
            f"(available: {', '.join(sorted(assets))[:200]})"
        )

    digest = None
    if checksum_template:
        checksum_name = checksum_template.format(**fmt)
        checksum_url = assets.get(checksum_name)
        if checksum_url:
            try:
                resp = requests.get(checksum_url, timeout=timeout)
                resp.raise_for_status()
                checksum_bytes = resp.content
            except requests.RequestException as exc:
                return False, f"{binary_name}: checksum download failed: {exc}"
        else:
            checksum_bytes = None
    else:
        checksum_bytes = None

    try:
        asset_resp = requests.get(asset_url, timeout=timeout)
        asset_resp.raise_for_status()
        payload = asset_resp.content
    except requests.RequestException as exc:
        return False, f"{binary_name}: asset download failed: {exc}"

    if checksum_bytes is not None:
        digest = _sha256(payload)
        if not _checksum_matches(checksum_bytes, asset_name, digest):
            return False, (
                f"{binary_name}: SHA-256 mismatch against {checksum_name} - "
                "refusing to install a possibly tampered binary"
            )
    else:
        return False, (
            f"{binary_name}: {tag} publishes no checksum for '{asset_name}' "
            "- refusing to install an unverified binary; install manually "
            f"from {asset_url}"
        )

    binary = payload
    if asset_name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
        try:
            with tarfile.open(fileobj=__import__("io").BytesIO(payload)) as tf:
                member = next(
                    (m for m in tf.getmembers()
                     if Path(m.name).name == binary_name), None
                )
                if member is None:
                    return False, (
                        f"{binary_name}: archive '{asset_name}' has no "
                        f"'{binary_name}' entry"
                    )
                stream = tf.extractfile(member)
                if stream is None:
                    return False, (
                        f"{binary_name}: archive entry '{binary_name}' is "
                        "not a regular file"
                    )
                binary = stream.read()
        except tarfile.TarError as exc:
            return False, f"{binary_name}: archive extraction failed: {exc}"

    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / binary_name
    target.write_bytes(binary)
    target.chmod(0o755)
    note = "sha256 verified" if checksum_bytes is not None else "unverified"
    return True, f"{binary_name} {tag} installed to {target} ({note})"
