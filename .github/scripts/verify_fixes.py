#!/usr/bin/env python3
"""Verify Scout-reported APK fixes are available in Alpine package repos.

Docker Scout marks a CVE as "fixed" when any Alpine release contains a patched
package version.  This can flag fixes that only exist in Alpine edge or a newer
release branch, causing pointless rebuild loops when the image pins an older
Alpine version whose repos have not backported the patch yet.

This module fetches the real APKINDEX for the target Alpine version and checks
whether the fixed package versions actually exist there.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ALPINE_REPOS = ("main", "community")
ALPINE_MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
ARCH_MAP = {
    "linux/amd64": "x86_64",
    "linux/arm64": "aarch64",
    "amd64": "x86_64",
    "arm64": "aarch64",
    "x86_64": "x86_64",
    "aarch64": "aarch64",
}


@dataclass(frozen=True)
class ApkFix:
    """A single CVE fix reported by Scout for an Alpine APK package."""
    cve_id: str
    package: str
    installed_version: str
    fixed_version: str


@dataclass
class VerifyResult:
    """Outcome of verifying Scout-reported fixes against Alpine repos."""
    available: list[ApkFix] = field(default_factory=list)
    phantom: list[ApkFix] = field(default_factory=list)
    skipped_non_apk: int = 0
    repo_versions: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# APKINDEX fetching & parsing
# ---------------------------------------------------------------------------

def fetch_apk_index(alpine_version: str, arch: str) -> dict[str, str]:
    """Fetch available package versions from Alpine main+community repos.

    Returns ``{package_name: version}`` for every package in the index.
    """
    apk_arch = ARCH_MAP.get(arch, arch)
    packages: dict[str, str] = {}

    for repo in ALPINE_REPOS:
        url = f"{ALPINE_MIRROR}/v{alpine_version}/{repo}/{apk_arch}/APKINDEX.tar.gz"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
        except Exception as exc:
            print(f"WARNING: could not fetch {url}: {exc}", file=sys.stderr)
            continue

        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name == "APKINDEX":
                    content = tar.extractfile(member)
                    if content is None:
                        continue
                    _parse_apkindex(content.read().decode("utf-8"), packages)

    return packages


def _parse_apkindex(text: str, packages: dict[str, str]) -> None:
    """Parse APKINDEX text format into a package dict (mutates *packages*)."""
    name: str | None = None
    version: str | None = None
    for line in text.splitlines():
        if line.startswith("P:"):
            name = line[2:]
        elif line.startswith("V:"):
            version = line[2:]
        elif line == "":
            if name and version:
                packages[name] = version
            name = None
            version = None
    if name and version:
        packages[name] = version


# ---------------------------------------------------------------------------
# Scout report parsing
# ---------------------------------------------------------------------------

_PURL_RE = re.compile(
    r"pkg:apk/alpine/(?P<name>[^@]+)@(?P<ver>[^?\"'\s]+)"
)
_FIXED_HTML_RE = re.compile(
    r"Fixed version</td>\s*<td>\s*<code>([^<]+)</code>"
)
_FIXED_TERM_RE = re.compile(
    r"Fixed version\s+:\s+(\S+)"
)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b")


def parse_report_fixes(report_text: str) -> list[ApkFix]:
    """Extract APK CVE fixes from a Scout markdown (HTML) or terminal report.

    Groups CVE + fixed-version entries under their preceding APK purl.  Non-APK
    packages (cargo, pip, …) are silently ignored.
    """
    fixes: list[ApkFix] = []
    # Split the text at each APK purl occurrence to get per-package blocks
    parts = _PURL_RE.split(report_text)

    # parts layout: [pre, name1, ver1, block1, name2, ver2, block2, ...]
    # _PURL_RE has two groups, so matches produce (name, ver) pairs between blocks
    idx = 1
    while idx + 2 < len(parts):
        pkg_name = parts[idx]
        pkg_ver = parts[idx + 1]
        block = parts[idx + 2]
        idx += 3

        # Truncate block at any non-APK purl so we don't absorb unrelated CVEs.
        non_apk = re.search(r"pkg:(?!apk/alpine/)\w+/", block)
        if non_apk:
            block = block[:non_apk.start()]

        # Collect all fixed versions from this block (stop at next purl)
        fixed_versions: list[str] = _FIXED_HTML_RE.findall(block)
        if not fixed_versions:
            fixed_versions = _FIXED_TERM_RE.findall(block)

        cve_ids = list(dict.fromkeys(_CVE_RE.findall(block)))

        if not fixed_versions:
            continue

        # Pair CVEs with their fixed versions; they appear in order
        for i, cve_id in enumerate(cve_ids):
            fixed = fixed_versions[i] if i < len(fixed_versions) else fixed_versions[-1]
            fixes.append(ApkFix(
                cve_id=cve_id,
                package=pkg_name,
                installed_version=pkg_ver,
                fixed_version=fixed,
            ))

    return fixes


# ---------------------------------------------------------------------------
# Alpine version comparison
# ---------------------------------------------------------------------------

def _parse_alpine_version(v: str) -> tuple:
    """Parse an Alpine package version string for comparison.

    Handles versions like ``3.5.9-r1``, ``2.54.1-r0``, ``1.2.6_pre3-r0``.
    Returns a tuple suitable for ``<`` / ``>=`` comparison.
    """
    epoch = 0
    if ":" in v:
        epoch_str, v = v.split(":", 1)
        epoch = int(epoch_str)

    revision = 0
    if "-r" in v:
        v, rev_str = v.rsplit("-r", 1)
        try:
            revision = int(rev_str)
        except ValueError:
            pass

    segments: list[tuple[int, int | str]] = []
    for part in re.split(r"[._]", v):
        try:
            segments.append((0, int(part)))
        except ValueError:
            segments.append((1, part))

    return (epoch, segments, revision)


def _fix_is_available(repo_version: str, fixed_version: str) -> bool:
    """True when the repo version is at least the fixed version."""
    return _parse_alpine_version(repo_version) >= _parse_alpine_version(fixed_version)


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------

def verify_report(
    report_path: Path,
    alpine_version: str,
    arch: str,
    apk_index: dict[str, str] | None = None,
) -> VerifyResult:
    """Read a Scout report and verify its APK fixes against Alpine repos."""
    text = report_path.read_text()
    return verify_text(text, alpine_version, arch, apk_index)


def verify_text(
    report_text: str,
    alpine_version: str,
    arch: str,
    apk_index: dict[str, str] | None = None,
) -> VerifyResult:
    """Verify Scout report text against Alpine repos."""
    fixes = parse_report_fixes(report_text)

    # Count non-APK CVEs (everything in the report minus APK-sourced CVEs)
    all_cves = set(_CVE_RE.findall(report_text))
    apk_cves = {f.cve_id for f in fixes}
    skipped = len(all_cves - apk_cves)

    if not fixes:
        return VerifyResult(skipped_non_apk=skipped)

    if apk_index is None:
        apk_index = fetch_apk_index(alpine_version, arch)

    result = VerifyResult(skipped_non_apk=skipped)

    # Deduplicate by (package, fixed_version) to avoid redundant lookups
    seen: set[tuple[str, str]] = set()
    for fix in fixes:
        key = (fix.package, fix.fixed_version)
        repo_ver = apk_index.get(fix.package)
        if repo_ver and fix.package not in result.repo_versions:
            result.repo_versions[fix.package] = repo_ver

        if repo_ver and _fix_is_available(repo_ver, fix.fixed_version):
            result.available.append(fix)
        else:
            result.phantom.append(fix)

    return result


# ---------------------------------------------------------------------------
# CLI for local testing
# ---------------------------------------------------------------------------

def _run_scout_scan(image: str, platform: str) -> str:
    """Run Docker Scout and return the markdown report text."""
    result = subprocess.run(
        [
            "docker", "scout", "cves", image,
            "--platform", platform,
            "--only-fixed", "--only-severity", "high,critical",
            "--format", "markdown",
        ],
        capture_output=True, text=True, timeout=600,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify whether Scout-reported fixes are in Alpine repos",
    )
    parser.add_argument("image", nargs="?", help="Docker image reference (e.g. mxmd/php:8.4-mssql-cli)")
    parser.add_argument("--alpine-version", required=True, help="Alpine release (e.g. 3.24)")
    parser.add_argument("--platform", default="linux/amd64", help="Target platform")
    parser.add_argument("--report", type=Path, help="Existing Scout markdown report (skips live scan)")
    args = parser.parse_args()

    if args.report:
        report_text = args.report.read_text()
    elif args.image:
        print(f"Scanning {args.image} ({args.platform}) …", flush=True)
        report_text = _run_scout_scan(args.image, args.platform)
        if not report_text.strip():
            print("Scout returned no output — image may have no vulnerabilities.")
            return 0
    else:
        parser.error("provide either an image reference or --report")
        return 1

    print(f"Fetching APKINDEX for Alpine v{args.alpine_version} ({args.platform}) …", flush=True)
    apk_index = fetch_apk_index(args.alpine_version, args.platform)
    if not apk_index:
        print("ERROR: could not fetch APKINDEX", file=sys.stderr)
        return 1
    print(f"  {len(apk_index)} packages in index")

    result = verify_text(report_text, args.alpine_version, args.platform, apk_index)

    if result.phantom:
        print(f"\nPhantom fixes — not in Alpine v{args.alpine_version} repos ({len(result.phantom)}):")
        by_pkg: dict[str, list[ApkFix]] = {}
        for fix in result.phantom:
            by_pkg.setdefault(fix.package, []).append(fix)
        for pkg, fixes in sorted(by_pkg.items()):
            repo_ver = result.repo_versions.get(pkg, "(not in index)")
            cves = ", ".join(f.cve_id for f in fixes)
            print(f"  {pkg} {fixes[0].installed_version} -> {fixes[0].fixed_version}"
                  f"  (repo has {repo_ver})  [{cves}]")

    if result.available:
        print(f"\nTruly fixable — available in Alpine v{args.alpine_version} repos ({len(result.available)}):")
        by_pkg = {}
        for fix in result.available:
            by_pkg.setdefault(fix.package, []).append(fix)
        for pkg, fixes in sorted(by_pkg.items()):
            repo_ver = result.repo_versions.get(pkg, "?")
            cves = ", ".join(f.cve_id for f in fixes)
            print(f"  {pkg} {fixes[0].installed_version} -> {repo_ver}  [{cves}]")

    if result.skipped_non_apk:
        print(f"\nSkipped {result.skipped_non_apk} non-APK CVE(s)")

    has_real_fixes = bool(result.available)
    print(f"\nVerdict: rebuild {'RECOMMENDED' if has_real_fixes else 'NOT NEEDED'}")
    return 2 if has_real_fixes else 0


if __name__ == "__main__":
    raise SystemExit(main())
