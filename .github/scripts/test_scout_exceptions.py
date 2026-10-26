import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import dhi_vex
import scout_exceptions as scout
from test_dhi_vex import BASE, IMAGE, PACKAGE, sbom, vex

CVE = "CVE-2026-92392"
CANONICAL = "pkg:apk/alpine/curl@8.22.0-r1?os_name=alpine&os_version=3.24"


def document():
    return dhi_vex.derive(vex(), sbom(), IMAGE, BASE, "2026-10-25T16:50:00Z", "2026-10-26T16:00:00Z")


def exception(purl=CANONICAL, digest="sha256:" + "b" * 64):
    return {"id": "existing-id", "type": "FALSE_POSITIVE", "imageScopes": [{
        "hostName": "hub.docker.com", "repoName": "mxmd/php", "digest": digest,
        "packageScopes": [{"purl": purl}],
    }], "reason": {"justification": "INLINE_MITIGATIONS_ALREADY_EXIST"}}


def packages(excepted=False, purl=CANONICAL):
    return [{"purl": purl, "vulnerabilities": [{"sourceId": CVE, "isExcepted": excepted,
            "vulnerabilityExceptions": [{"id": "existing-id"}] if excepted else []}]}]


class ScoutExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.client = Mock()
        self.client.existing.return_value = []
        self.client.packages.side_effect = [packages(), packages(True)]
        self.client.query.return_value = {"addVulnerabilityException": {"exception": exception()}}

    def test_verified_source_alias_maps_to_exact_api_package(self):
        scout.publish(self.client, document(), IMAGE, self.directory)
        payload = self.client.query.call_args.args[1]["input"]
        self.assertEqual(payload["type"], "FALSE_POSITIVE")
        self.assertEqual(payload["justification"], "INLINE_MITIGATIONS_ALREADY_EXIST")
        self.assertEqual(payload["imageScopes"], [{"hostName": "hub.docker.com", "repoName": "mxmd/php",
            "digest": "sha256:" + "b" * 64, "packageScopes": [{"purlFields": {
                "type": "apk", "namespace": "alpine", "name": "curl", "version": "8.22.0-r1"}}]}])
        self.assertIn(BASE, payload["additionalDetails"])
        self.assertTrue(json.loads((self.directory / "scout-exceptions.json").read_text())[0]["isExcepted"])

    def test_rerun_reuses_matching_exception(self):
        self.client.existing.return_value = [exception()]
        scout.publish(self.client, document(), IMAGE, self.directory)
        self.client.query.assert_not_called()
        self.assertFalse(json.loads((self.directory / "scout-exceptions.json").read_text())[0]["created"])

    def test_different_version_or_platform_is_never_reused(self):
        self.client.existing.return_value = [exception(CANONICAL.replace("r1", "r0")), exception(digest="sha256:" + "c" * 64)]
        scout.publish(self.client, document(), IMAGE, self.directory)
        self.client.query.assert_called_once()

    def test_unassessed_r0_cannot_inherit_r1_exclusion(self):
        self.client.packages.side_effect = None
        self.client.packages.return_value = packages(purl=CANONICAL.replace("r1", "r0"))
        with self.assertRaisesRegex(ValueError, "absent"):
            scout.publish(self.client, document(), IMAGE, self.directory)
        self.client.query.assert_not_called()

    def test_other_vex_statuses_do_not_create_exceptions(self):
        for status in ("affected", "fixed", "under_investigation"):
            doc = document()
            doc["statements"][0]["status"] = status
            scout.publish(self.client, doc, IMAGE, self.directory)
        self.client.query.assert_not_called()
        self.client.packages.assert_not_called()

    def test_wrong_product_digest_is_rejected_before_api_calls(self):
        with self.assertRaisesRegex(ValueError, "platform digest"):
            scout.publish(self.client, document(), IMAGE.replace("b" * 64, "c" * 64), self.directory)
        self.client.query.assert_not_called()
        self.client.packages.assert_not_called()

    def test_duplicate_upstream_statements_create_one_exception(self):
        doc = document()
        doc["statements"].append(copy.deepcopy(doc["statements"][0]))
        scout.publish(self.client, doc, IMAGE, self.directory)
        self.client.query.assert_called_once()

    def test_conflicting_statuses_block_publication(self):
        doc = document()
        conflict = copy.deepcopy(doc["statements"][0])
        conflict["status"] = "affected"
        doc["statements"].append(conflict)
        with self.assertRaisesRegex(ValueError, "Conflicting VEX statuses"):
            scout.publish(self.client, doc, IMAGE, self.directory)
        self.client.query.assert_not_called()

    def test_creation_without_effective_suppression_fails(self):
        self.client.packages.side_effect = None
        self.client.packages.return_value = packages()
        with patch.object(scout.time, "sleep"), self.assertRaisesRegex(RuntimeError, "effective suppression"):
            scout.publish(self.client, document(), IMAGE, self.directory)

    def test_empty_index_is_not_a_success(self):
        self.client.packages.side_effect = None
        self.client.packages.return_value = []
        with patch.object(scout.time, "sleep"), self.assertRaisesRegex(RuntimeError, "not indexed"):
            scout.publish(self.client, document(), IMAGE, self.directory)
        self.client.query.assert_not_called()

    def test_http_200_graphql_errors_fail_without_saving_credentials(self):
        with patch.dict(os.environ, {"DOCKER_HUB_USERNAME": "test-user", "DOCKER_HUB_ACCESS_TOKEN": "test-secret"}), patch.object(scout, "http", side_effect=[
            {"access_token": "test-token"}, {"errors": [{"message": "denied"}], "data": {"vulnerabilityExceptions": None}},
        ]):
            client = scout.Client(self.directory)
            with self.assertRaisesRegex(RuntimeError, "GraphQL"):
                client.existing({"organization": "mxmd"}, "mxmd/php", "sha256:" + "b" * 64, CVE)
        evidence = "".join(path.read_text() for path in self.directory.iterdir())
        for secret in ("test-secret", "test-token", "test-user"):
            self.assertNotIn(secret, evidence)

    def test_lookup_paginates_from_one_with_scout_source_enum(self):
        client = scout.Client.__new__(scout.Client)
        client.query = Mock(side_effect=[
            {"vulnerabilityExceptions": {"items": [{"id": "one"}], "paging": {"totalCount": 2}}},
            {"vulnerabilityExceptions": {"items": [{"id": "two"}], "paging": {"totalCount": 2}}},
        ])
        self.assertEqual(len(client.existing({"organization": "mxmd"}, "mxmd/php", "sha256:" + "b" * 64, CVE)), 2)
        variables = [call.args[1]["q"] for call in client.query.call_args_list]
        self.assertEqual([value["paging"]["page"] for value in variables], [1, 2])
        self.assertTrue(all(value["filter"]["sourceType"] == "SCOUT" for value in variables))
        self.assertTrue(all("orgExceptionsOnly" not in value["filter"] for value in variables))

    def test_incomplete_lookup_cannot_duplicate_an_applied_manual_exception(self):
        current = packages(True)
        current[0]["vulnerabilities"][0]["vulnerabilityExceptions"][0]["sourceType"] = "MANUAL_EXCEPTION"
        self.client.packages.side_effect = None
        self.client.packages.return_value = current
        with self.assertRaisesRegex(RuntimeError, "refusing a duplicate"):
            scout.publish(self.client, document(), IMAGE, self.directory)
        self.client.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
