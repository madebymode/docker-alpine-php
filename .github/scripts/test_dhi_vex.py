import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dhi_vex


BASE = "dhi.io/php:8.5-alpine3.24-fpm@sha256:" + "a" * 64
IMAGE = "mxmd/php:test@sha256:" + "b" * 64
PACKAGE = "pkg:apk/alpine/libcurl@8.22.0-r1?arch=x86_64&distro=alpine-3.24&upstream=curl"


def provenance():
    return {platform: {"SLSA": {"buildDefinition": {
        "externalParameters": {"request": {"args": {"build-arg:RUNTIME_BASE_REF": BASE, "build-arg:BUILDER_BASE_REF": BASE.replace("-fpm@", "-dev@")}}},
        "resolvedDependencies": [{"uri": f"pkg:docker/dhi.io/php@8.5-alpine3.24-{variant}?platform=linux%2Famd64", "digest": {"sha256": "a" * 64}} for variant in ("fpm", "dev")],
    }, "runDetails": {"metadata": {"finishedOn": "2026-10-25T16:50:00Z"}}}} for platform in dhi_vex.PLATFORMS}


def sbom(checksum="c" * 64, identity=PACKAGE):
    return {
        "packages": [{"SPDXID": "package", "externalRefs": [{"referenceType": "purl", "referenceLocator": identity}]}],
        "files": [{"SPDXID": "file", "fileName": "usr/lib/libcurl.so.4.8.0", "checksums": [{"algorithm": "SHA256", "checksumValue": checksum}]}],
        "relationships": [{"spdxElementId": "package", "relatedSpdxElement": "file", "relationshipType": "CONTAINS"}],
    }


def vex():
    return {"@context": dhi_vex.PREDICATE, "@id": "urn:uuid:9f346144-5f0a-4765-a3ea-c55132a9084a", "timestamp": "2026-10-22T08:59:52Z", "version": 1,
            "author": "Docker Hardened Images <dhi@docker.com>", "statements": [{
        "vulnerability": {"name": "CVE-2026-92392"}, "status": "not_affected",
        "justification": "inline_mitigations_already_exist",
        "products": [{"@id": "pkg:apk/alpine/libcurl"}],
    }]}


class VexTests(unittest.TestCase):
    def test_unchanged_packages_preserve_original_document(self):
        document = vex()
        original = copy.deepcopy(document)
        dhi_vex.validate_passthrough(document, sbom(), sbom())
        self.assertEqual(document, original)

    def test_changed_library_is_not_suppressed_even_with_same_version(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            dhi_vex.validate_passthrough(vex(), sbom(), sbom("d" * 64))

    def test_dhi_and_scout_purl_qualifiers_can_differ_with_identical_files(self):
        base = sbom(identity="pkg:apk/alpine/libcurl@8.22.0-r1?os_name=alpine&os_version=3.24")
        dhi_vex.validate_passthrough(vex(), base, sbom())
        with self.assertRaises(ValueError):
            dhi_vex.validate_passthrough(vex(), base, sbom("d" * 64))

    def test_added_or_upgraded_package_cannot_inherit_generic_exclusion(self):
        with self.assertRaises(ValueError):
            dhi_vex.validate_passthrough(vex(), sbom(), sbom(identity=PACKAGE.replace("8.22.0-r1", "8.22.0-r2")))

    def test_missing_file_evidence_is_not_accepted(self):
        for child in (sbom(""), {**sbom(), "relationships": []}):
            with self.assertRaises(ValueError):
                dhi_vex.validate_passthrough(vex(), sbom(), child)

    def test_source_package_alias_is_checked(self):
        document = vex()
        document["statements"][0]["products"] = [{"@id": "pkg:apk/alpine/curl@8.22.0-r1"}]
        with self.assertRaises(ValueError):
            dhi_vex.validate_passthrough(document, sbom(), sbom("d" * 64))

    def test_split_package_file_records_are_merged_but_conflicts_fail(self):
        document = sbom()
        package = copy.deepcopy(document["packages"][0])
        package["SPDXID"] = "package-two"
        document["packages"].append(package)
        file = copy.deepcopy(document["files"][0])
        file["SPDXID"] = "file-two"
        file["fileName"] = "usr/share/licenses/curl"
        document["files"].append(file)
        document["relationships"].append({"spdxElementId": "package-two", "relatedSpdxElement": "file-two", "relationshipType": "CONTAINS"})
        self.assertEqual(len(dhi_vex.package_inventory(document)[PACKAGE]), 2)
        file["fileName"] = "usr/lib/libcurl.so.4.8.0"
        file["checksums"][0]["checksumValue"] = "d" * 64
        with self.assertRaises(ValueError):
            dhi_vex.package_inventory(document)

    def test_unrelated_added_package_does_not_block_passthrough(self):
        child = sbom(identity=PACKAGE.replace("libcurl", "libzip").replace("upstream=curl", "upstream=libzip"))
        dhi_vex.validate_passthrough(vex(), sbom(), child)

    def test_base_is_taken_from_published_provenance(self):
        self.assertEqual(dhi_vex.recorded_base(provenance(), "linux/amd64"), BASE)
        unpinned = provenance()
        unpinned["linux/amd64"]["SLSA"]["buildDefinition"]["externalParameters"]["request"]["args"]["build-arg:RUNTIME_BASE_REF"] = BASE.split("@")[0]
        with self.assertRaises(ValueError):
            dhi_vex.recorded_base(unpinned, "linux/amd64")
        missing = provenance()
        missing["linux/amd64"]["SLSA"]["buildDefinition"]["resolvedDependencies"] = []
        with self.assertRaises(ValueError):
            dhi_vex.recorded_base(missing, "linux/amd64")

    def test_prepare_verifies_both_platforms_before_publication(self):
        document = vex()
        manifest = {"manifests": [{"digest": "sha256:" + value * 64, "platform": {"os": "linux", "architecture": arch}} for arch, value in (("amd64", "c"), ("arm64", "d"))]}
        calls = []

        def docker(arguments, directory, name):
            calls.append(arguments)
            if name.endswith("-scout-publish"):
                return ""
            if name == "provenance":
                return json.dumps(provenance())
            if name == "manifest":
                return json.dumps(manifest)
            if "--output" in arguments:
                Path(arguments[arguments.index("--output") + 1]).write_text(json.dumps(document if arguments[1] == "vex" else sbom()))
            return ""

        with tempfile.TemporaryDirectory() as temporary, patch.object(dhi_vex, "docker", side_effect=docker), patch.object(dhi_vex, "validate_and_attest", return_value=Path("validated.intoto.json")) as validate, patch.object(dhi_vex, "run", return_value="") as runner:
            directory = Path(temporary)
            bundle = dhi_vex.prepare(IMAGE, directory, BASE)
            self.assertEqual(len(bundle), 2)
            self.assertFalse(any("add" in call for call in calls))
            dhi_vex.publish(bundle, directory)
            self.assertEqual(validate.call_count, 2)
            publications = [call.args[0] for call in runner.call_args_list]
            self.assertEqual([call[-2] for call in publications], ["docker.io/mxmd/php@sha256:" + "c" * 64, "docker.io/mxmd/php@sha256:" + "d" * 64])
            registrations = [call for call in calls if call[:3] == ["scout", "attestation", "add"]]
            self.assertEqual(len(registrations), 2)
            self.assertTrue(all("--referrer" in call for call in registrations))
            retrievals = [call for call in calls if call[:3] == ["scout", "vex", "get"]]
            self.assertTrue(all("--verify" in call for call in retrievals))
            self.assertTrue(all("registry://" + BASE in call for call in retrievals))
            for source in bundle.values():
                child = json.loads(Path(source["vex"]).read_text())
                self.assertEqual(child["author"], dhi_vex.AUTHOR)
                self.assertEqual(child["statements"][0]["products"][0]["subcomponents"], [{"@id": PACKAGE}])
            for call in publications:
                self.assertIn("v1.1-referrers-api", call)
                self.assertEqual(call[-1], "validated.intoto.json:application/vnd.in-toto+json")
                self.assertNotIn("--predicate-type", call)

    def test_child_scope_author_and_content_id_are_correct_and_deterministic(self):
        document = vex()
        original = copy.deepcopy(document)
        child = dhi_vex.derive(document, sbom(), IMAGE, BASE, "2026-10-25T16:50:00Z", "2026-10-25T16:55:00Z")
        self.assertEqual(child, dhi_vex.derive(document, sbom(), IMAGE, BASE, "2026-10-25T16:50:00Z", "2026-10-25T16:55:00Z"))
        self.assertEqual(document, original)
        self.assertEqual(child["author"], dhi_vex.AUTHOR)
        self.assertTrue(child["@id"].startswith("urn:sha256:"))
        product = child["statements"][0]["products"][0]
        self.assertEqual(product["@id"], "pkg:docker/" + IMAGE.replace(":test@", "@"))
        self.assertEqual(product["hashes"], {"sha-256": "b" * 64})
        self.assertIn(document["@id"], child["statements"][0]["status_notes"])
        self.assertIn(document["author"], child["statements"][0]["status_notes"])
        document["statements"][0]["status"] = "under_investigation"
        document["statements"][0].pop("justification")
        revised = dhi_vex.derive(document, sbom(), IMAGE, BASE, "2026-10-25T16:50:00Z", "2026-10-25T16:55:00Z")
        self.assertNotEqual(child["@id"], revised["@id"])
        self.assertEqual(revised["statements"][0]["status"], "under_investigation")

    def test_no_upstream_vex_does_not_invent_an_exception_or_cross_platforms(self):
        manifest = {"manifests": [{"digest": "sha256:" + value * 64, "platform": {"os": "linux", "architecture": arch}} for arch, value in (("amd64", "c"), ("arm64", "d"))]}

        def docker(arguments, directory, name):
            if name == "provenance":
                return json.dumps(provenance())
            if name == "manifest":
                return json.dumps(manifest)
            if name == "arm64-vex-runtime":
                raise subprocess.CalledProcessError(1, arguments, stderr="no VEX attestations found for image")
            Path(arguments[arguments.index("--output") + 1]).write_text(json.dumps(vex() if arguments[1] == "vex" else sbom()))
            return ""

        with tempfile.TemporaryDirectory() as temporary, patch.object(dhi_vex, "docker", side_effect=docker), patch.object(dhi_vex, "validate_and_attest", return_value=Path("validated.intoto.json")):
            bundle = dhi_vex.prepare(IMAGE, Path(temporary))
        self.assertTrue(bundle["linux/amd64"]["vex"])
        self.assertEqual(bundle["linux/arm64"]["vex"], "")
        self.assertEqual(bundle["linux/arm64"]["attestation"], "")

    def test_strict_vexctl_validation_is_required_before_attesting(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(dhi_vex, "run", side_effect=subprocess.CalledProcessError(1, "vexctl")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                dhi_vex.validate_and_attest(Path("child.vex.json"), Path(temporary), "amd64")
            self.assertEqual(run.call_count, 1)
            self.assertIn("--strict", run.call_args.args[0])

    def test_scout_failure_is_never_treated_as_verified(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(dhi_vex.subprocess, "run", return_value=subprocess.CompletedProcess("docker", 1, "", "signature invalid")):
            with self.assertRaises(subprocess.CalledProcessError):
                dhi_vex.docker(["scout", "vex", "get"], Path(temporary), "verify")


if __name__ == "__main__":
    unittest.main()
