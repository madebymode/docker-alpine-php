"""Publish digest/package-scoped Scout exceptions from verified child OpenVEX.

The GraphQL mutation contract was introspected and tested against Docker Scout.
Keep the portable OpenVEX artifact too: organization exceptions are private policy.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote

API = "https://api.dso.docker.com/v1/graphql"
AUTH = "https://hub.docker.com/v2/auth/token"
FIELDS = """id type imageScopes { hostName repoName digest packageScopes { purl } }
reason { justification additionalDetails }"""
IMAGE_QUERY = """query Image($ctx: Context!, $q: IpImagePackagesForImageCoordsQuery!) {
  imagePackagesForImageCoords(context: $ctx, query: $q) {
    imagePackages { packages { package { purl vulnerabilities {
      sourceId isExcepted vulnerabilityExceptions { id sourceType }
    } } } }
  }
}"""
LOOKUP = """query Existing($ctx: Context!, $q: VulnerabilityExceptionsQuery) {
  vulnerabilityExceptions(context: $ctx, query: $q) {
    paging { totalCount } items { """ + FIELDS + """ }
  }
}"""
CREATE = """mutation Create($ctx: Context!, $input: AddVulnerabilityExceptionInput!) {
  addVulnerabilityException(context: $ctx, input: $input) {
    exception { """ + FIELDS + """ }
  }
}"""
JUSTIFICATIONS = {
    "component_not_present", "vulnerable_code_not_present",
    "vulnerable_code_not_in_execute_path",
    "vulnerable_code_cannot_be_controlled_by_adversary",
    "inline_mitigations_already_exist",
}


def coordinates(purl: str) -> tuple[str, str, str, str]:
    path = purl.split("?", 1)[0]
    if "#" in purl or not path.startswith("pkg:apk/"):
        raise ValueError(f"Unsupported assessed package: {purl}")
    path, version = path.rsplit("@", 1)
    kind, namespace, name = path.removeprefix("pkg:").split("/", 2)
    if not version or not namespace or not name:
        raise ValueError(f"A versioned package is required: {purl}")
    return tuple(unquote(value) for value in (kind, namespace, name, version))


def matches(assessed: str, canonical: str) -> bool:
    """Scout's API may report the source APK (curl) for a binary APK (libcurl)."""
    if not canonical.startswith("pkg:apk/"):
        return False
    left, right = coordinates(assessed), coordinates(canonical)
    upstream = parse_qs(assessed.partition("?")[2]).get("upstream", [])
    return left[:2] == right[:2] and left[3] == right[3] and right[2] in {left[2], *upstream}


def http(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Never save authentication bodies, headers, tokens, or HTTP error bodies.
        raise RuntimeError(f"Docker API returned HTTP {exc.code}") from None


class Client:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sequence = 0
        username = os.environ.get("DOCKER_HUB_USERNAME")
        secret = os.environ.get("DOCKER_HUB_ACCESS_TOKEN")
        if not username or not secret:
            raise ValueError("Scout exception publication requires DOCKER_HUB_USERNAME and DOCKER_HUB_ACCESS_TOKEN")
        self.token = http(os.environ.get("SCOUT_AUTH_URL", AUTH), {"identifier": username, "secret": secret}).get("access_token")
        if not self.token:
            raise RuntimeError("Docker authentication did not return an access token")

    def query(self, query: str, variables: dict) -> dict:
        payload = {"query": query, "variables": variables}
        result = http(os.environ.get("SCOUT_API_URL", API), payload, self.token)
        self.sequence += 1
        prefix = self.directory / f"{self.sequence:04d}"
        prefix.with_suffix(".request.json").write_text(json.dumps(payload, indent=2) + "\n")
        prefix.with_suffix(".response.json").write_text(json.dumps(result, indent=2) + "\n")
        if result.get("errors") or not isinstance(result.get("data"), dict):
            raise RuntimeError("Docker Scout GraphQL operation failed; see credential-free API evidence")
        return result["data"]

    def packages(self, context: dict, repository: str, digest: str) -> list[dict]:
        data = self.query(IMAGE_QUERY, {"ctx": context, "q": {
            "hostName": "hub.docker.com", "repoName": repository, "digest": digest,
            "includeExcepted": True, "includePublic": True,
        }})["imagePackagesForImageCoords"]
        inventories = (data or {}).get("imagePackages") or []
        if isinstance(inventories, dict):
            inventories = [inventories]
        return [entry["package"] for inventory in inventories for entry in inventory["packages"]]

    def existing(self, context: dict, repository: str, digest: str, cve: str) -> list[dict]:
        items = []
        page = 1
        while True:
            result = self.query(LOOKUP, {"ctx": context, "q": {
                # Query the organization's CVE records, then check each exact
                # scope below. orgExceptionsOnly excludes image-scoped records.
                "filter": {"cveId": cve, "sourceType": "SCOUT"},
                "paging": {"page": page, "pageSize": 20},
            }})["vulnerabilityExceptions"]
            items.extend(result["items"])
            if len(items) >= result["paging"]["totalCount"]:
                return items
            if not result["items"]:
                raise RuntimeError("Incomplete Scout exception pagination")
            page += 1


def exact_exception(exception: dict, repository: str, digest: str, purl: str, justification: str) -> bool:
    scopes = exception.get("imageScopes") or []
    if exception.get("type") != "FALSE_POSITIVE" or len(scopes) != 1:
        return False
    scope = scopes[0]
    packages = scope.get("packageScopes") or []
    return (scope.get("hostName") == "hub.docker.com" and scope.get("repoName") == repository
            and scope.get("digest") == digest and len(packages) == 1
            and coordinates(packages[0]["purl"]) == coordinates(purl)
            and (exception.get("reason") or {}).get("justification") == justification)


def publish(client: Client, document: dict, image: str, directory: Path) -> None:
    """Called only after DHI signature/file checks and strict OpenVEX validation."""
    from dhi_vex import AUTHOR, PREDICATE

    repository, digest = image.split("@")
    repository = re.sub(r":[^/:]+$", "", repository).removeprefix("docker.io/")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or "/" not in repository:
        raise ValueError("Scout exceptions require an exact image digest and repository")
    if document.get("author") != AUTHOR or document.get("@context") != PREDICATE:
        raise ValueError("Only our verified derived OpenVEX can be published as Scout exceptions")
    context = {"organization": repository.split("/")[0]}
    assessments = []
    for statement in document["statements"]:
        for product in statement["products"]:
            if (product["@id"] != f"pkg:docker/{repository}@{digest}"
                    or product.get("hashes", {}).get("sha-256") != digest.removeprefix("sha256:")):
                raise ValueError("OpenVEX product does not match the target platform digest")
            for component in product.get("subcomponents", []):
                coordinates(component["@id"])
                assessments.append((statement, component["@id"]))
    if not any(statement["status"] == "not_affected" for statement, _ in assessments):
        return
    # A new release may not yet have been indexed by Scout. Empty data is never success.
    for attempt in range(60):
        packages = client.packages(context, repository, digest)
        if packages:
            break
        time.sleep(5)
    else:
        raise RuntimeError("Scout has not indexed the published platform; exception verification incomplete")
    targets = {}
    for statement, assessed in assessments:
        matched = [package for package in packages if matches(assessed, package["purl"])]
        if statement["status"] != "not_affected":
            continue
        justification = statement.get("justification", "")
        if justification not in JUSTIFICATIONS:
            raise ValueError("Cannot map not_affected without a supported OpenVEX justification")
        cve = statement["vulnerability"]["name"]
        if not re.fullmatch(r"CVE-[0-9]{4}-[0-9]{4,}", cve):
            raise ValueError(f"Unsupported vulnerability identifier: {cve}")
        if not matched:
            raise ValueError(f"Assessed package absent from Scout inventory: {assessed}")
        for package in matched:
            if not any(v["sourceId"] == cve for v in package.get("vulnerabilities") or []):
                continue  # No reported CVE needs an exception; never create speculative exclusions.
            key = (cve, package["purl"])
            if key in targets and targets[key]["justification"] != justification:
                raise ValueError(f"Conflicting VEX justifications for {key}")
            # Reject contradictory statuses rather than allowing a stale not_affected to win.
            if any(other["vulnerability"]["name"] == cve and other["status"] != "not_affected"
                   and matches(component, package["purl"]) for other, component in assessments):
                raise ValueError(f"Conflicting VEX statuses for {key}")
            targets[key] = {"justification": justification, "statement": statement}
    summary = []
    for (cve, purl), target in sorted(targets.items()):
        justification = target["justification"].upper()
        candidates = client.existing(context, repository, digest, cve)
        applied_ids = {e["id"] for package in packages if package["purl"] == purl
                       for v in package.get("vulnerabilities") or [] if v["sourceId"] == cve
                       for e in v["vulnerabilityExceptions"] if e.get("sourceType") == "MANUAL_EXCEPTION"}
        if not applied_ids.issubset({item["id"] for item in candidates}):
            raise RuntimeError("Scout lookup omitted an applied organization exception; refusing a duplicate mutation")
        existing = next((item for item in candidates if exact_exception(item, repository, digest, purl, justification)), None)
        created = existing is None
        if created:
            kind, namespace, name, version = coordinates(purl)
            statement = target["statement"]
            details = "Verified DHI OpenVEX passthrough. " + statement.get("status_notes", "")
            details += " " + statement.get("impact_statement", "")
            existing = client.query(CREATE, {"ctx": context, "input": {
                "cveId": cve, "type": "FALSE_POSITIVE", "justification": justification,
                "additionalDetails": details.strip(),
                "imageScopes": [{"hostName": "hub.docker.com", "repoName": repository,
                                 "digest": digest, "packageScopes": [{"purlFields": {
                                     "type": kind, "namespace": namespace, "name": name, "version": version,
                                 }}]}],
            }})["addVulnerabilityException"]["exception"]
            if not exact_exception(existing, repository, digest, purl, justification):
                raise RuntimeError("Scout did not preserve the requested exception scope")
        exception_id = existing["id"]
        for attempt in range(12):
            current = client.packages(context, repository, digest)
            rows = [v for package in current if package["purl"] == purl
                    for v in package.get("vulnerabilities") or [] if v["sourceId"] == cve]
            if rows and all(v["isExcepted"] and any(e["id"] == exception_id for e in v["vulnerabilityExceptions"]) for v in rows):
                break
            time.sleep(5)
        else:
            raise RuntimeError(f"Scout did not confirm effective suppression of {cve} in {purl}")
        summary.append({"cve": cve, "package": purl, "image": image,
                        "exceptionId": exception_id, "created": created, "isExcepted": True})
        print(f"{'Created' if created else 'Reused'} Scout exception {exception_id}: {cve}, {purl}", flush=True)
    (directory / "scout-exceptions.json").write_text(json.dumps(summary, indent=2) + "\n")
