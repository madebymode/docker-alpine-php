#!/usr/bin/env python3
"""Select published PHP images for rebuilding when Docker Scout finds fixable CVEs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from update_php_alpine_versions import parse_env_file
import dhi_vex

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE_TYPES = ("cli", "fpm", "fpm-hardened")
PLATFORMS = ("linux/amd64", "linux/arm64")


def image_reference(env_file: Path) -> str:
    values = parse_env_file(env_file)
    repository = values.get("IMAGE_REPO") or "mxmd/php"
    tag = values.get("IMAGE_TAG")
    if not tag:
        variant = "-mssql" if env_file.parent.name.endswith("-mssql") else ""
        tag = f'{values["PHP_VERSION_MAJOR"]}{variant}-{env_file.parent.parent.name}'
    return f"{repository}:{tag}"


def extract_cve_ids(report: Path) -> set[str]:
    if not report.is_file():
        return set()
    return set(re.findall(r'\bCVE-\d{4}-\d{4,}\b', report.read_text()))


def scan_images(repo_root: Path, reports_dir: Path, image_type: str, publish_vex: bool = False) -> tuple[list[dict[str, str]], list[str], set[str]]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    matrix: list[dict[str, str]] = []
    errors: list[str] = []
    cve_ids: set[str] = set()
    summary = ["| Image | Platform | Result |", "| --- | --- | --- |"]
    scanned = 0

    for kind in IMAGE_TYPES:
        if image_type != "all" and kind != image_type:
            continue
        for env_file in sorted((repo_root / kind).glob("*/.env")):
            if not (env_file.parent / "Dockerfile").is_file():
                continue
            scanned += 1
            version = env_file.parent.name
            reference = image_reference(env_file)
            prefix = f"{kind}-{version}"
            try:
                resolved = subprocess.run(
                    ["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"],
                    capture_output=True, text=True, check=True, timeout=120,
                )
                digest = resolved.stdout.strip()
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                    raise ValueError(f"Invalid manifest digest: {digest!r}")
            except (subprocess.SubprocessError, ValueError) as exc:
                detail = getattr(exc, "stderr", None) or str(exc)
                (reports_dir / f"{prefix}-resolve.log").write_text(str(detail))
                errors.append(f"Could not resolve {reference}; see {prefix}-resolve.log")
                summary.append(f"| `{reference}` | both | Registry lookup failed |")
                continue

            vex = {}
            if kind == "fpm-hardened":
                try:
                    vex_dir = reports_dir / f"{prefix}-vex"
                    vex = dhi_vex.prepare(f"{reference}@{digest}", vex_dir)
                    if publish_vex:
                        dhi_vex.publish(vex, vex_dir)
                except (subprocess.SubprocessError, ValueError, KeyError, StopIteration, OSError) as exc:
                    errors.append(f"VEX preparation/publication failed for {reference}: {exc}; see {prefix}-vex/")
                    summary.append(f"| `{reference}@{digest}` | both | VEX failed; rebuild decisions skipped |")
                    continue

            fixable = False
            # Both architectures must be scanned from the same immutable manifest.
            for platform in PLATFORMS:
                report = reports_dir / f'{prefix}-{platform.split("/")[1]}.md'
                command = [
                    "docker", "scout", "cves", f"registry://{reference}@{digest}",
                    "--platform", platform, "--only-fixed",
                    "--only-severity", "high,critical", "--exit-code",
                    "--format", "markdown", "--output", str(report),
                ]
                if kind == "fpm-hardened":
                    if vex[platform]["vex"]:
                        command.extend(["--vex-location", vex[platform]["vex"]])
                    command.extend(["--only-vex-affected",
                                    "--vex-author", "<.*@docker.com>", "--vex-author", "^https://github[.]com/madebymode$"])
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
                    report.with_suffix(".log").write_text(result.stdout + result.stderr)
                    decision_report = report
                    base_only = False
                    if result.returncode == 2 and kind == "fpm-hardened":
                        # Keep base CVEs in the audit report. Rebuilding the same
                        # pinned DHI cannot fix them; the digest updater owns that.
                        decision_report = report.with_name(report.stem + "-rebuild.md")
                        rebuild_command = command.copy()
                        rebuild_command[rebuild_command.index("--output") + 1] = str(decision_report)
                        rebuild_command.append("--ignore-base")
                        result = subprocess.run(rebuild_command, capture_output=True, text=True, timeout=600)
                        decision_report.with_suffix(".log").write_text(result.stdout + result.stderr)
                        base_only = result.returncode == 0
                    if result.returncode == 0:
                        status = "Base CVEs remain visible; waiting for a DHI digest update" if base_only else "No fixable CVEs"
                    elif result.returncode == 2:
                        status = "Fixes available; rebuild requested"
                        fixable = True
                        cve_ids.update(extract_cve_ids(decision_report))
                    else:
                        status = f"Scan failed (exit {result.returncode})"
                        errors.append(f"{reference} ({platform}): {status}; see {decision_report.with_suffix('.log').name}")
                except subprocess.TimeoutExpired:
                    status = "Scan timed out"
                    errors.append(f"{reference} ({platform}): {status}")
                summary.append(f"| `{reference}@{digest}` | {platform} | {status} |")
                print(f"{reference} ({platform}): {status}", flush=True)
            if fixable:
                matrix.append({"type": kind, "version": version})

    if not scanned:
        errors.append("No buildable image directories matched the scan scope")
    if errors:
        summary.extend(["", "Scans were incomplete. Automatic rebuilds are skipped for this run."])
    summary_text = "\n".join(summary) + "\n"
    (reports_dir / "summary.md").write_text(summary_text)
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a") as output:
            output.write(summary_text)
    return matrix, errors, cve_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-type", choices=("all", *IMAGE_TYPES), default="all")
    parser.add_argument("--reports-dir", type=Path, default=Path("scout-reports"))
    parser.add_argument("--publish-vex", action="store_true", help="Refresh hardened-image VEX attestations without rebuilding")
    args = parser.parse_args()
    matrix, errors, cve_ids = scan_images(REPO_ROOT, args.reports_dir, args.image_type, args.publish_vex)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    encoded = json.dumps(matrix, separators=(",", ":"))
    cve_list = ",".join(sorted(cve_ids))
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with open(output_file, "a") as output:
            output.write(f"matrix={encoded}\n")
            output.write(f"has_fixes={str(bool(matrix)).lower()}\n")
            output.write(f"cve_list={cve_list}\n")
    print(f"Rebuild matrix: {encoded}")
    if cve_list:
        print(f"CVEs with fixes: {cve_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
