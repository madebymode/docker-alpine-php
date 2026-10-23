#!/usr/bin/env python3
"""Check AlmaLinux rpms/php for new security patch commits and update alma-patches.json."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALMA_PATCHES_FILE = REPO_ROOT / ".github" / "alma-patches.json"
GITEA_API = "https://git.almalinux.org/api/v1"
REPO = "rpms/php"

EOL_VERSIONS: dict[str, str] = {
    "7.2": "a8-stream-7.2",
    "7.3": "a8-stream-7.3",
    "7.4": "a8-stream-7.4",
    "8.0": "a8-stream-8.0",
    "8.1": "a9-stream-8.1",
}


def fetch_json(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode())


def get_branch_head(branch: str) -> str:
    data = fetch_json(f"{GITEA_API}/repos/{REPO}/branches/{branch}")
    return data["commit"]["id"]


def main() -> int:
    if ALMA_PATCHES_FILE.exists():
        patches: dict = json.loads(ALMA_PATCHES_FILE.read_text())
    else:
        patches = {}

    changed = False
    for version, branch in EOL_VERSIONS.items():
        try:
            commit = get_branch_head(branch)
        except Exception as exc:
            print(f"[error] {version} ({branch}): {exc}", file=sys.stderr)
            continue

        current = patches.get(version, {}).get("commit", "")
        if commit == current:
            print(f"[ok]     {version}: {commit[:12]}")
            continue

        print(f"[update] {version}: {current[:12] or 'none'} -> {commit[:12]}")
        patches[version] = {"branch": branch, "commit": commit}
        changed = True

    ALMA_PATCHES_FILE.write_text(json.dumps(patches, indent=2) + "\n")

    if changed:
        print("\nPatches updated.")
    else:
        print("\nNo updates.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
