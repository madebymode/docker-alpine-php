import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scan_docker_images as scanner


class ScanImagesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reports = self.root / "reports"
        self.digest = "sha256:" + "a" * 64
        self.statuses = {}
        self.commands = []
        self.environment = patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(self.root / "summary")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.vex = {
            platform: {"vex": str(self.root / f"{platform.split('/')[1]}.vex.json")}
            for platform in scanner.PLATFORMS
        }
        self.prepare = patch.object(scanner.dhi_vex, "prepare", return_value=self.vex).start()
        self.publish = patch.object(scanner.dhi_vex, "publish").start()
        self.addCleanup(patch.stopall)

    def add_image(self, kind, version, extra=""):
        directory = self.root / kind / version
        directory.mkdir(parents=True)
        (directory / "Dockerfile").touch()
        (directory / ".env").write_text(
            f"PHP_VERSION=8.5.10\nPHP_VERSION_MAJOR=8.5\nALPINE_VERSION=3.24\n{extra}"
        )
        return directory / ".env"

    def docker(self, command, **kwargs):
        self.commands.append(command)
        if command[1] == "buildx":
            return subprocess.CompletedProcess(command, 0, self.digest + "\n", "")
        platform = command[command.index("--platform") + 1]
        reference = command[3]
        status = self.statuses.get((reference, platform), 0)
        if isinstance(status, Exception):
            raise status
        Path(command[command.index("--output") + 1]).write_text("Scout report\n")
        return subprocess.CompletedProcess(command, status, "Scan output\n", "")

    def scan(self, image_type="all"):
        with patch.object(scanner.subprocess, "run", side_effect=self.docker), contextlib.redirect_stdout(io.StringIO()):
            return scanner.scan_images(self.root, self.reports, image_type)

    def test_rolling_and_custom_tags(self):
        plain = self.add_image("cli", "8.5")
        mssql = self.add_image("fpm", "8.5-mssql")
        hardened = self.add_image("fpm-hardened", "8.5", "IMAGE_REPO=example/php\nIMAGE_TAG=fpm-hardened-8.5\n")
        self.assertEqual(scanner.image_reference(plain), "mxmd/php:8.5-cli")
        self.assertEqual(scanner.image_reference(mssql), "mxmd/php:8.5-mssql-fpm")
        self.assertEqual(scanner.image_reference(hardened), "example/php:fpm-hardened-8.5")

    def test_no_fixable_findings_skips_rebuild(self):
        self.add_image("cli", "8.5")
        matrix, errors, cve_ids = self.scan()
        self.assertEqual((matrix, errors), ([], []))
        scans = [command for command in self.commands if command[1] == "scout"]
        self.assertEqual(len(scans), 2)
        for command in scans:
            self.assertIn("--only-fixed", command)
            self.assertIn("--exit-code", command)
            self.assertEqual(command[3], f"registry://mxmd/php:8.5-cli@{self.digest}")

    def test_arm64_fix_selects_only_affected_image(self):
        self.add_image("cli", "8.5")
        self.add_image("fpm", "8.5")
        reference = f"registry://mxmd/php:8.5-fpm@{self.digest}"
        self.statuses[(reference, "linux/arm64")] = 2
        self.assertEqual(self.scan(), ([{"type": "fpm", "version": "8.5"}], [], set()))

    def test_both_platforms_with_fixes_produce_one_build(self):
        self.add_image("fpm-hardened", "8.5", "IMAGE_TAG=fpm-hardened-8.5\n")
        self.add_image("cli", "8.5")
        reference = f"registry://mxmd/php:fpm-hardened-8.5@{self.digest}"
        for platform in scanner.PLATFORMS:
            self.statuses[(reference, platform)] = 2
        self.assertEqual(self.scan("fpm-hardened"), ([{"type": "fpm-hardened", "version": "8.5"}], [], set()))
        self.assertEqual(len(self.commands), 5)

    def test_vex_exclusions_do_not_retrigger_hardened_builds(self):
        for kind in scanner.IMAGE_TYPES:
            self.add_image(kind, "8.5")
        output = self.root / "outputs"

        def inherited_finding(command, **kwargs):
            result = self.docker(command, **kwargs)
            if command[1] == "scout":
                result.returncode = 0 if "--only-vex-affected" in command else 2
                report = Path(command[command.index("--output") + 1])
                report.write_text("CVE-2026-92392\n" if result.returncode == 2 else "")
            return result

        with (
            patch.object(scanner, "REPO_ROOT", self.root),
            patch.object(scanner.subprocess, "run", side_effect=inherited_finding),
            patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
            patch("sys.argv", ["scan", "--reports-dir", str(self.reports)]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(scanner.main(), 0)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(outputs["has_fixes"], "true")
        self.assertEqual(outputs["cve_list"], "CVE-2026-92392")
        self.assertEqual(json.loads(outputs["matrix"]), [
            {"type": "cli", "version": "8.5"},
            {"type": "fpm", "version": "8.5"},
        ])
        scans = [command for command in self.commands if command[1] == "scout"]
        self.assertEqual(len(scans), 6)
        for command in scans:
            self.assertNotIn("--ignore-base", command)
            self.assertEqual("--only-vex-affected" in command, "fpm-hardened" in command[3])
            if "fpm-hardened" in command[3]:
                platform = command[command.index("--platform") + 1]
                self.assertEqual(command[command.index("--vex-location") + 1], self.vex[platform]["vex"])

    def test_only_excluded_cves_emit_no_rebuild_and_no_release_cves(self):
        self.add_image("fpm-hardened", "8.5")
        output = self.root / "outputs"
        with (
            patch.object(scanner, "REPO_ROOT", self.root),
            patch.object(scanner.subprocess, "run", side_effect=self.docker),
            patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
            patch("sys.argv", ["scan", "--reports-dir", str(self.reports), "--publish-vex"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(scanner.main(), 0)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(outputs["has_fixes"], "false")
        self.assertEqual(outputs["matrix"], "[]")
        self.assertEqual(outputs["cve_list"], "")
        self.publish.assert_called_once()

    def test_vex_verification_or_publication_failure_blocks_rebuild_outputs(self):
        self.add_image("fpm-hardened", "8.5")
        for operation in (self.prepare, self.publish):
            with self.subTest(operation=operation):
                operation.side_effect = ValueError("invalid VEX")
                matrix, errors, cve_ids = scanner.scan_images(self.root, self.reports, "all", True)
                self.assertEqual(matrix, [])
                self.assertTrue(errors)
                self.assertEqual(cve_ids, set())
                operation.side_effect = None
        self.assertFalse(any(command[1] == "scout" for command in self.commands))

    def test_unassessed_base_cves_are_reported_without_rebuilding_the_same_pin(self):
        self.add_image("fpm-hardened", "8.5")
        self.prepare.return_value = {platform: {"vex": ""} for platform in scanner.PLATFORMS}

        def base_finding(command, **kwargs):
            result = self.docker(command, **kwargs)
            if command[1] == "scout":
                result.returncode = 0 if "--ignore-base" in command else 2
                Path(command[command.index("--output") + 1]).write_text("" if result.returncode == 0 else "CVE-2026-92392")
            return result

        with patch.object(scanner.subprocess, "run", side_effect=base_finding):
            matrix, errors, cve_ids = scanner.scan_images(self.root, self.reports, "all")
        self.assertEqual((matrix, errors, cve_ids), ([], [], set()))
        self.assertIn("CVE-2026-92392", (self.reports / "fpm-hardened-8.5-amd64.md").read_text())
        self.assertIn("waiting for a DHI digest update", (self.reports / "summary.md").read_text())
        self.assertTrue(all("--vex-location" not in command for command in self.commands))

    def test_scanner_failure_blocks_workflow_outputs(self):
        self.add_image("cli", "8.5")
        reference = f"registry://mxmd/php:8.5-cli@{self.digest}"
        self.statuses[(reference, "linux/amd64")] = 2
        self.statuses[(reference, "linux/arm64")] = 1
        output = self.root / "outputs"
        with (
            patch.object(scanner, "REPO_ROOT", self.root),
            patch.object(scanner.subprocess, "run", side_effect=self.docker),
            patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
            patch("sys.argv", ["scan", "--reports-dir", str(self.reports)]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(scanner.main(), 1)
        self.assertFalse(output.exists())
        self.assertIn("Scans were incomplete", (self.reports / "summary.md").read_text())

    def test_registry_failure_is_reported(self):
        self.add_image("cli", "8.5")
        with patch.object(scanner.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "docker", stderr="denied")):
            matrix, errors, cve_ids = scanner.scan_images(self.root, self.reports, "all")
        self.assertEqual(matrix, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual((self.reports / "cli-8.5-resolve.log").read_text(), "denied")

    def test_timeout_is_not_treated_as_clean(self):
        self.add_image("cli", "8.5")
        reference = f"registry://mxmd/php:8.5-cli@{self.digest}"
        self.statuses[(reference, "linux/amd64")] = subprocess.TimeoutExpired("docker", 600)
        matrix, errors, cve_ids = self.scan()
        self.assertEqual(matrix, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("timed out", errors[0])

    def test_success_emits_selective_build_matrix(self):
        self.add_image("cli", "8.5")
        reference = f"registry://mxmd/php:8.5-cli@{self.digest}"
        self.statuses[(reference, "linux/amd64")] = 2
        output = self.root / "outputs"
        with (
            patch.object(scanner, "REPO_ROOT", self.root),
            patch.object(scanner.subprocess, "run", side_effect=self.docker),
            patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
            patch("sys.argv", ["scan", "--reports-dir", str(self.reports)]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(scanner.main(), 0)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(outputs["has_fixes"], "true")
        self.assertEqual(json.loads(outputs["matrix"]), [{"type": "cli", "version": "8.5"}])


if __name__ == "__main__":
    unittest.main()
