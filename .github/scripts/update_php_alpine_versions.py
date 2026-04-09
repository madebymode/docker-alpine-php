#!/usr/bin/env python3
"""Update tracked PHP Alpine base versions from Docker official-images metadata."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/docker-library/official-images/refs/heads/master/library/php"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_GLOBS = ("cli/*/.env", "fpm/*/.env")

TAG_PATTERN = re.compile(
    r"^(?P<php>\d+\.\d+\.\d+)-(?P<type>cli|fpm)-alpine(?P<alpine>\d+\.\d+)$"
)
VERSION_PATTERN = re.compile(r"^(?P<major>\d+\.\d+)\.(?P<patch>\d+)$")


@dataclass(frozen=True)
class EnvTarget:
    path: Path
    image_type: str
    php_version: str
    php_version_major: str
    alpine_version: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Read official-images metadata from a local file instead of fetching upstream.",
    )
    return parser.parse_args()


def fetch_source(input_file: Path | None) -> str:
    if input_file is not None:
        return input_file.read_text()

    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        return response.read().decode("utf-8")


def load_targets() -> list[EnvTarget]:
    targets: list[EnvTarget] = []
    for pattern in ENV_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            values = parse_env_file(path)
            image_type = path.parent.parent.name
            targets.append(
                EnvTarget(
                    path=path,
                    image_type=image_type,
                    php_version=values["PHP_VERSION"],
                    php_version_major=values["PHP_VERSION_MAJOR"],
                    alpine_version=values["ALPINE_VERSION"],
                )
            )
    return targets


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

    required = {"PHP_VERSION", "PHP_VERSION_MAJOR", "ALPINE_VERSION"}
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"{path}: missing required keys: {', '.join(missing)}")

    return values


def parse_official_tags(content: str) -> dict[tuple[str, str, str], str]:
    latest: dict[tuple[str, str, str], tuple[int, int, int]] = {}

    for line in content.splitlines():
        if not line.startswith("Tags: "):
            continue

        tags = [tag.strip() for tag in line.removeprefix("Tags: ").split(",")]
        for tag in tags:
            match = TAG_PATTERN.fullmatch(tag)
            if not match:
                continue

            php_version = match.group("php")
            version_match = VERSION_PATTERN.fullmatch(php_version)
            if version_match is None:
                continue

            major = version_match.group("major")
            key = (major, match.group("type"), match.group("alpine"))
            candidate = tuple(int(part) for part in php_version.split("."))

            if key not in latest or candidate > latest[key]:
                latest[key] = candidate

    return {key: ".".join(str(part) for part in version) for key, version in latest.items()}


def replace_env_value(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    return pattern.sub(f"{key}={value}", content, count=1)


def update_target(target: EnvTarget, latest_versions: dict[tuple[str, str, str], str]) -> tuple[bool, str]:
    key = (target.php_version_major, target.image_type, target.alpine_version)
    latest_version = latest_versions.get(key)
    descriptor = f"{target.php_version_major}-{target.image_type}-alpine{target.alpine_version}"

    if latest_version is None:
        return False, f"[skip] {target.path.relative_to(REPO_ROOT)}: no upstream stable tag for {descriptor}"

    if latest_version == target.php_version:
        return False, f"[ok] {target.path.relative_to(REPO_ROOT)}: {target.php_version} is current for {descriptor}"

    content = target.path.read_text()
    updated = replace_env_value(content, "PHP_VERSION", latest_version)
    target.path.write_text(updated)
    return True, (
        f"[update] {target.path.relative_to(REPO_ROOT)}: "
        f"{target.php_version} -> {latest_version} for {descriptor}"
    )


def main() -> int:
    args = parse_args()

    try:
        source = fetch_source(args.input_file)
        targets = load_targets()
        latest_versions = parse_official_tags(source)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not targets:
        print("ERROR: no tracked .env files found", file=sys.stderr)
        return 1

    updated = 0
    for target in targets:
        changed, message = update_target(target, latest_versions)
        print(message)
        if changed:
            updated += 1

    if updated:
        print(f"\nUpdated {updated} file(s).")
    else:
        print("\nNo updates required.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
