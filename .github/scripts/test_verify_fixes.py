import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_fixes


SAMPLE_APKINDEX = """\
C:Q1abc123
P:openssl
V:3.5.9-r0
A:x86_64
T:Toolkit for Transport Layer Security (TLS)

C:Q1def456
P:git
V:2.54.1-r0
A:x86_64
T:Distributed version control system

C:Q1ghi789
P:musl
V:1.2.6-r3
A:x86_64
T:the musl c library

C:Q1jkl012
P:curl
V:8.12.1-r0
A:x86_64
T:URL retrieval utility

"""

SAMPLE_SCOUT_MARKDOWN = """\
<h2>Vulnerabilities of <code>mxmd/php:8.4-mssql-cli</code></h2>
<table>
<tr><td valign="top">
<details><summary><strong>openssl</strong> <code>3.5.9-r0</code> (apk)</summary>
<small><code>pkg:apk/alpine/openssl@3.5.9-r0?os_name=alpine&os_version=3.24</code></small><br/>
<a href="https://scout.docker.com/v/CVE-2026-95691"><img alt="high : CVE-2026-95691"/></a>
<table>
<tr><td>Fixed version</td><td><code>3.5.9-r1</code></td></tr>
</table>
<a href="https://scout.docker.com/v/CVE-2026-95692"><img alt="high : CVE-2026-95692"/></a>
<table>
<tr><td>Fixed version</td><td><code>3.5.9-r1</code></td></tr>
</table>
</details></td></tr>

<tr><td valign="top">
<details><summary><strong>git</strong> <code>2.54.1-r0</code> (apk)</summary>
<small><code>pkg:apk/alpine/git@2.54.1-r0?os_name=alpine&os_version=3.24</code></small><br/>
<a href="https://scout.docker.com/v/CVE-2026-111760"><img alt="high : CVE-2026-111760"/></a>
<table>
<tr><td>Fixed version</td><td><code>2.56.1-r0</code></td></tr>
</table>
</details></td></tr>

<tr><td valign="top">
<details><summary><strong>musl</strong> <code>1.2.6-r3</code> (apk)</summary>
<small><code>pkg:apk/alpine/musl@1.2.6-r3?os_name=alpine&os_version=3.24</code></small><br/>
<a href="https://scout.docker.com/v/CVE-2026-107891"><img alt="high : CVE-2026-107891"/></a>
<table>
<tr><td>Fixed version</td><td><code>1.2.6-r6</code></td></tr>
</table>
</details></td></tr>
</table>
"""

SAMPLE_SCOUT_TERMINAL = """\
   0C     4H     0M     0L  openssl 3.5.9-r0
pkg:apk/alpine/openssl@3.5.9-r0?os_name=alpine&os_version=3.24

    ✗ HIGH CVE-2026-95691
      Affected range : <3.5.9-r1
      Fixed version  : 3.5.9-r1

    ✗ HIGH CVE-2026-95692
      Affected range : <3.5.9-r1
      Fixed version  : 3.5.9-r1

   0C     1H     0M     0L  musl 1.2.6-r3
pkg:apk/alpine/musl@1.2.6-r3?os_name=alpine&os_version=3.24

    ✗ HIGH CVE-2026-107891
      Affected range : <1.2.6-r6
      Fixed version  : 1.2.6-r6
"""

# APKINDEX where openssl HAS been patched but git and musl have NOT
PARTIAL_FIX_INDEX = {
    "openssl": "3.5.9-r1",
    "git": "2.54.1-r0",
    "musl": "1.2.6-r3",
    "curl": "8.12.1-r0",
}

# APKINDEX where nothing has been patched (matches the installed versions)
NO_FIX_INDEX = {
    "openssl": "3.5.9-r0",
    "git": "2.54.1-r0",
    "musl": "1.2.6-r3",
}

# APKINDEX where everything has been patched
ALL_FIXED_INDEX = {
    "openssl": "3.5.9-r1",
    "git": "2.56.1-r0",
    "musl": "1.2.6-r6",
}


class ApkIndexParsingTests(unittest.TestCase):
    def test_parse_apkindex(self):
        packages: dict[str, str] = {}
        verify_fixes._parse_apkindex(SAMPLE_APKINDEX, packages)
        self.assertEqual(packages["openssl"], "3.5.9-r0")
        self.assertEqual(packages["git"], "2.54.1-r0")
        self.assertEqual(packages["musl"], "1.2.6-r3")
        self.assertEqual(packages["curl"], "8.12.1-r0")
        self.assertEqual(len(packages), 4)

    def test_parse_apkindex_no_trailing_newline(self):
        text = "P:test-pkg\nV:1.0.0-r0\nA:x86_64"
        packages: dict[str, str] = {}
        verify_fixes._parse_apkindex(text, packages)
        self.assertEqual(packages["test-pkg"], "1.0.0-r0")

    def test_parse_apkindex_empty(self):
        packages: dict[str, str] = {}
        verify_fixes._parse_apkindex("", packages)
        self.assertEqual(packages, {})


class VersionComparisonTests(unittest.TestCase):
    def test_same_version(self):
        self.assertTrue(verify_fixes._fix_is_available("3.5.9-r1", "3.5.9-r1"))

    def test_newer_revision(self):
        self.assertTrue(verify_fixes._fix_is_available("3.5.9-r2", "3.5.9-r1"))

    def test_older_revision(self):
        self.assertFalse(verify_fixes._fix_is_available("3.5.9-r0", "3.5.9-r1"))

    def test_newer_minor(self):
        self.assertTrue(verify_fixes._fix_is_available("2.56.1-r0", "2.56.1-r0"))

    def test_older_minor(self):
        self.assertFalse(verify_fixes._fix_is_available("2.54.1-r0", "2.56.1-r0"))

    def test_major_version_jump(self):
        self.assertTrue(verify_fixes._fix_is_available("3.0.0-r0", "2.99.9-r9"))

    def test_revision_only_bump(self):
        self.assertFalse(verify_fixes._fix_is_available("1.2.6-r3", "1.2.6-r6"))
        self.assertTrue(verify_fixes._fix_is_available("1.2.6-r6", "1.2.6-r6"))
        self.assertTrue(verify_fixes._fix_is_available("1.2.6-r7", "1.2.6-r6"))

    def test_no_revision(self):
        self.assertTrue(verify_fixes._fix_is_available("1.0.0", "1.0.0"))
        self.assertFalse(verify_fixes._fix_is_available("1.0.0", "1.0.0-r1"))


class ReportParsingTests(unittest.TestCase):
    def test_parse_html_report(self):
        fixes = verify_fixes.parse_report_fixes(SAMPLE_SCOUT_MARKDOWN)
        self.assertEqual(len(fixes), 4)

        openssl_fixes = [f for f in fixes if f.package == "openssl"]
        self.assertEqual(len(openssl_fixes), 2)
        self.assertEqual(openssl_fixes[0].cve_id, "CVE-2026-95691")
        self.assertEqual(openssl_fixes[0].installed_version, "3.5.9-r0")
        self.assertEqual(openssl_fixes[0].fixed_version, "3.5.9-r1")

        git_fixes = [f for f in fixes if f.package == "git"]
        self.assertEqual(len(git_fixes), 1)
        self.assertEqual(git_fixes[0].cve_id, "CVE-2026-111760")
        self.assertEqual(git_fixes[0].fixed_version, "2.56.1-r0")

        musl_fixes = [f for f in fixes if f.package == "musl"]
        self.assertEqual(len(musl_fixes), 1)
        self.assertEqual(musl_fixes[0].cve_id, "CVE-2026-107891")
        self.assertEqual(musl_fixes[0].fixed_version, "1.2.6-r6")

    def test_parse_terminal_report(self):
        fixes = verify_fixes.parse_report_fixes(SAMPLE_SCOUT_TERMINAL)
        self.assertEqual(len(fixes), 3)
        packages = {f.package for f in fixes}
        self.assertEqual(packages, {"openssl", "musl"})

    def test_parse_empty_report(self):
        self.assertEqual(verify_fixes.parse_report_fixes(""), [])

    def test_non_apk_purls_ignored(self):
        text = """\
<small><code>pkg:cargo/libz-sys@1.1.12</code></small>
<a href="...CVE-2026-99999...">CVE-2026-99999</a>
<table><tr><td>Fixed version</td><td><code>1.1.31</code></td></tr></table>
"""
        fixes = verify_fixes.parse_report_fixes(text)
        self.assertEqual(fixes, [])


class VerifyTextTests(unittest.TestCase):
    def test_all_phantom_when_no_repo_updates(self):
        result = verify_fixes.verify_text(
            SAMPLE_SCOUT_MARKDOWN, "3.24", "linux/amd64", NO_FIX_INDEX,
        )
        self.assertEqual(len(result.available), 0)
        self.assertEqual(len(result.phantom), 4)

    def test_partial_fix_splits_correctly(self):
        result = verify_fixes.verify_text(
            SAMPLE_SCOUT_MARKDOWN, "3.24", "linux/amd64", PARTIAL_FIX_INDEX,
        )
        available_pkgs = {f.package for f in result.available}
        phantom_pkgs = {f.package for f in result.phantom}
        self.assertEqual(available_pkgs, {"openssl"})
        self.assertEqual(phantom_pkgs, {"git", "musl"})
        self.assertEqual(len(result.available), 2)  # 2 openssl CVEs
        self.assertEqual(len(result.phantom), 2)    # 1 git + 1 musl

    def test_all_fixed(self):
        result = verify_fixes.verify_text(
            SAMPLE_SCOUT_MARKDOWN, "3.24", "linux/amd64", ALL_FIXED_INDEX,
        )
        self.assertEqual(len(result.available), 4)
        self.assertEqual(len(result.phantom), 0)

    def test_repo_versions_captured(self):
        result = verify_fixes.verify_text(
            SAMPLE_SCOUT_MARKDOWN, "3.24", "linux/amd64", PARTIAL_FIX_INDEX,
        )
        self.assertEqual(result.repo_versions["openssl"], "3.5.9-r1")
        self.assertEqual(result.repo_versions["git"], "2.54.1-r0")

    def test_non_apk_cves_counted(self):
        mixed = SAMPLE_SCOUT_MARKDOWN + """\
<small><code>pkg:cargo/libz-sys@1.1.12</code></small>
<a href="...">CVE-2026-99999</a>
<table><tr><td>Fixed version</td><td><code>1.1.31</code></td></tr></table>
"""
        result = verify_fixes.verify_text(mixed, "3.24", "linux/amd64", NO_FIX_INDEX)
        self.assertEqual(result.skipped_non_apk, 1)

    def test_package_not_in_index_is_phantom(self):
        result = verify_fixes.verify_text(
            SAMPLE_SCOUT_MARKDOWN, "3.24", "linux/amd64", {"curl": "8.0-r0"},
        )
        self.assertEqual(len(result.phantom), 4)
        self.assertEqual(len(result.available), 0)


class VerifyReportFileTests(unittest.TestCase):
    def test_verify_report_reads_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(SAMPLE_SCOUT_MARKDOWN)
            f.flush()
            path = Path(f.name)
        try:
            result = verify_fixes.verify_report(path, "3.24", "linux/amd64", ALL_FIXED_INDEX)
            self.assertEqual(len(result.available), 4)
        finally:
            path.unlink()


class CLITests(unittest.TestCase):
    def test_cli_with_report_file_no_fixes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(SAMPLE_SCOUT_MARKDOWN)
            f.flush()
            path = Path(f.name)
        try:
            with patch.object(verify_fixes, "fetch_apk_index", return_value=NO_FIX_INDEX):
                with patch("sys.argv", ["verify", "--report", str(path), "--alpine-version", "3.24"]):
                    ret = verify_fixes.main()
            self.assertEqual(ret, 0)
        finally:
            path.unlink()

    def test_cli_with_report_file_has_fixes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(SAMPLE_SCOUT_MARKDOWN)
            f.flush()
            path = Path(f.name)
        try:
            with patch.object(verify_fixes, "fetch_apk_index", return_value=ALL_FIXED_INDEX):
                with patch("sys.argv", ["verify", "--report", str(path), "--alpine-version", "3.24"]):
                    ret = verify_fixes.main()
            self.assertEqual(ret, 2)
        finally:
            path.unlink()

    def test_cli_with_live_scan(self):
        scout_output = SAMPLE_SCOUT_MARKDOWN
        with (
            patch.object(verify_fixes, "_run_scout_scan", return_value=scout_output),
            patch.object(verify_fixes, "fetch_apk_index", return_value=NO_FIX_INDEX),
            patch("sys.argv", ["verify", "mxmd/php:8.4-mssql-cli", "--alpine-version", "3.24"]),
        ):
            ret = verify_fixes.main()
        self.assertEqual(ret, 0)


class ArchMapTests(unittest.TestCase):
    def test_platform_to_arch(self):
        self.assertEqual(verify_fixes.ARCH_MAP["linux/amd64"], "x86_64")
        self.assertEqual(verify_fixes.ARCH_MAP["linux/arm64"], "aarch64")
        self.assertEqual(verify_fixes.ARCH_MAP["amd64"], "x86_64")


if __name__ == "__main__":
    unittest.main()
