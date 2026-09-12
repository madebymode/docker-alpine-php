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


def scan_images(repo_root: Path, reports_dir: Path, image_type: str) -> tuple[list[dict[str, str]], list[str]]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    matrix: list[dict[str, str]] = []
    errors: list[str] = []
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

            fixable = False
            # Both architectures must be scanned from the same immutable manifest.
            for platform in PLATFORMS:
                report = reports_dir / f'{prefix}-{platform.split("/")[1]}.md'
                command = [
                    "docker", "scout", "cves", f"registry://{reference}@{digest}",
                    "--platform", platform, "--only-fixed", "--exit-code",
                    "--format", "markdown", "--output", str(report),
                ]
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
                    report.with_suffix(".log").write_text(result.stdout + result.stderr)
                    if result.returncode == 0:
                        status = "No fixable CVEs"
                    elif result.returncode == 2:
                        status = "Fixes available; rebuild requested"
                        fixable = True
                    else:
                        status = f"Scan failed (exit {result.returncode})"
                        errors.append(f"{reference} ({platform}): {status}; see {report.with_suffix('.log').name}")
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
    return matrix, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-type", choices=("all", *IMAGE_TYPES), default="all")
    parser.add_argument("--reports-dir", type=Path, default=Path("scout-reports"))
    args = parser.parse_args()
    matrix, errors = scan_images(REPO_ROOT, args.reports_dir, args.image_type)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    encoded = json.dumps(matrix, separators=(",", ":"))
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with open(output_file, "a") as output:
            output.write(f"matrix={encoded}\n")
            output.write(f"has_fixes={str(bool(matrix)).lower()}\n")
    print(f"Rebuild matrix: {encoded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
