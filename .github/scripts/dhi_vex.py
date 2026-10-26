#!/usr/bin/env python3
"""Publish child-scoped OpenVEX assessments from verified DHI evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote

import scout_exceptions

PLATFORMS = ("linux/amd64", "linux/arm64")
PREDICATE = "https://openvex.dev/ns/v0.2.0"
DIGEST = r"sha256:[0-9a-f]{64}"
AUTHOR = "https://github.com/madebymode"


def run(command: list[str], directory: Path, name: str, cwd: Path | None = None) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=600, cwd=cwd)
    (directory / f"{name}.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    return result.stdout


def docker(arguments: list[str], directory: Path, name: str) -> str:
    return run(["docker", *arguments], directory, name)


def recorded_base(provenance: dict, platform: str, stage: str = "runtime") -> str:
    """Use the build's recorded base, never today's rolling tag or digest pins."""
    slsa = provenance[platform]["SLSA"]
    definition = slsa.get("buildDefinition", {})
    # BuildKit emits both SLSA v0.2 and v1, depending on the builder version.
    args = definition.get("externalParameters", {}).get("request", {}).get("args", {})
    if not args:
        args = slsa.get("invocation", {}).get("parameters", {}).get("args", {})
    reference = args.get(f"build-arg:{stage.upper()}_BASE_REF", "")
    suffix = "fpm" if stage == "runtime" else "dev"
    if not re.fullmatch(r"dhi\.io/php:[A-Za-z0-9_.-]+-" + suffix + "@" + DIGEST, reference):
        raise ValueError(f"Missing digest-pinned DHI {stage} base for {platform}")
    image, digest = reference.split("@")
    dependencies = definition.get("resolvedDependencies", slsa.get("materials", []))
    expected_uri = "pkg:docker/" + image.replace(":", "@", 1)
    if not any(
        item.get("uri", "").split("?")[0] == expected_uri
        and item.get("digest", {}).get("sha256") == digest.removeprefix("sha256:")
        for item in dependencies
    ):
        raise ValueError(f"DHI {stage} base is absent from provenance materials for {platform}")
    return reference


def purl(value: str) -> tuple[str, str, str, str, dict[str, list[str]]]:
    path, _, query = value.partition("?")
    path, _, version = path.partition("@")
    kind, namespace, name = path.removeprefix("pkg:").split("/", 2)
    return kind, unquote(namespace), unquote(name), unquote(version), parse_qs(query)


def package_inventory(sbom: dict) -> dict[str, dict[str, str]]:
    files = {item["SPDXID"]: item for item in sbom.get("files", [])}
    contained: dict[str, list[str]] = {}
    for relation in sbom.get("relationships", []):
        if relation["relationshipType"] == "CONTAINS" and relation["relatedSpdxElement"] in files:
            contained.setdefault(relation["spdxElementId"], []).append(relation["relatedSpdxElement"])
    inventory = {}
    for package in sbom.get("packages", []):
        for reference in package.get("externalRefs", []):
            identity = reference.get("referenceLocator", "")
            if reference.get("referenceType") != "purl" or not identity.startswith("pkg:apk/"):
                continue
            checksums = {}
            for file_id in contained.get(package["SPDXID"], []):
                file = files[file_id]
                sha = next((c["checksumValue"] for c in file.get("checksums", []) if c["algorithm"] == "SHA256"), "")
                checksums[file["fileName"].lstrip("/")] = sha
            existing = inventory.setdefault(identity, {})
            if any(path in existing and existing[path] != sha for path, sha in checksums.items()):
                raise ValueError(f"Conflicting package file evidence: {identity}")
            existing.update(checksums)
    return inventory


def validate_passthrough(document: dict, base_sbom: dict, child_sbom: dict) -> None:
    """Refuse to derive assessments for modified or unverifiable packages."""
    if document.get("@context") != PREDICATE or not isinstance(document.get("statements"), list):
        raise ValueError("Invalid OpenVEX document")
    if not re.search(r"<[^<>]+@docker\.com>$", document.get("author", "")):
        raise ValueError("VEX document is not authored by Docker")
    selectors = []
    for statement in document["statements"]:
        for product in statement.get("products", []):
            for component in [product, *product.get("subcomponents", [])]:
                identity = component.get("@id", "")
                if identity.startswith("pkg:apk/"):
                    selectors.append(purl(identity))
                elif identity.startswith("pkg:") and not identity.startswith("pkg:docker/"):
                    raise ValueError(f"Unsupported VEX package scope: {identity}")
    base = package_inventory(base_sbom)
    child = package_inventory(child_sbom)
    for identity, checksums in child.items():
        kind, namespace, name, version, qualifiers = purl(identity)
        names = {name, *qualifiers.get("upstream", [])}
        if not any(
            kind == selector[0] and namespace == selector[1]
            and selector[2] in names and (not selector[3] or selector[3] == version)
            for selector in selectors
        ):
            continue
        # DHI's attached SBOM uses os_name/os_version, while Scout's generated
        # SBOM uses arch/distro/upstream. Both SBOMs were resolved for the same
        # platform; compare package coordinates and actual file contents.
        matches = [files for candidate, files in base.items() if purl(candidate)[:4] == (kind, namespace, name, version)]
        if not checksums or not all(checksums.values()) or not matches or any(files != checksums for files in matches):
            raise ValueError(f"Refusing DHI VEX for a new, changed, or unverifiable package: {identity}")


def derive(document: dict, child_sbom: dict, image: str, source: str, built_at: str, issued_at: str | None = None) -> dict:
    """Issue our own digest-scoped assessment, citing the verified upstream evidence."""
    packages = package_inventory(child_sbom)
    repository, digest = image.split("@")
    repository = re.sub(r":[^/:]+$", "", repository).removeprefix("docker.io/")
    issued = issued_at or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(issued.replace("Z", "+00:00")) < datetime.fromisoformat(built_at.replace("Z", "+00:00")):
        raise ValueError("An assessment cannot be issued before the child image was built")
    statements = []
    for original in document["statements"]:
        selectors = [purl(component["@id"])
                     for product in original.get("products", [])
                     for component in [product, *product.get("subcomponents", [])]
                     if component.get("@id", "").startswith("pkg:apk/")]
        matched = []
        for identity in packages:
            kind, namespace, name, version, qualifiers = purl(identity)
            if any(kind == s[0] and namespace == s[1]
                   and s[2] in {name, *qualifiers.get("upstream", [])}
                   and (not s[3] or s[3] == version) for s in selectors):
                matched.append({"@id": identity})
        if not matched:
            continue
        statement = {key: original[key] for key in (
            "vulnerability", "status", "justification", "impact_statement",
            "action_statement", "action_statement_timestamp",
        ) if key in original}
        statement["timestamp"] = issued
        statement["products"] = [{
            "@id": f"pkg:docker/{repository}@{digest}",
            "hashes": {"sha-256": digest.removeprefix("sha256:")},
            "subcomponents": matched,
        }]
        statement["status_notes"] = (
            f"Derived from {document['author']}; source image {source}; "
            f"upstream document {document['@id']}, statement {original.get('@id', original['vulnerability']['name'])}. "
            "Package versions and SHA-256 file checksums match the verified DHI source. "
            + original.get("status_notes", "")
        )
        # Duplicate upstream assessments need not become duplicate child statements.
        if statement not in statements:
            statements.append(statement)
    if not statements:
        raise ValueError("No upstream assessments match packages in the child image")
    derived = {"@context": PREDICATE, "author": AUTHOR, "role": "Document Creator",
               "timestamp": issued, "version": 1, "tooling": "docker-alpine-php DHI VEX derivation",
               "statements": statements}
    # Every newly issued assessment receives a new content-addressed ID, so no
    # document's contents are changed without changing its ID/version.
    derived["@id"] = "urn:sha256:" + hashlib.sha256(json.dumps(derived, sort_keys=True).encode()).hexdigest()
    return derived


def validate_and_attest(vex_file: Path, directory: Path, architecture: str, upstream: Path | None = None) -> Path:
    binary = os.environ.get("VEXCTL", "vexctl")
    if upstream:
        # Preserve upstream formatting warnings as evidence; published child
        # documents must pass the stricter gate with zero warnings as well.
        run([binary, "validate", str(upstream)], directory, f"{architecture}-upstream-validate")
    run([binary, "validate", "--strict", str(vex_file)], directory, f"{architecture}-openvex-validate")
    attestation = directory / f"{architecture}.intoto.json"
    # vexctl transfers the product's image digest to the in-toto subject, retaining
    # matching product/subcomponent scope according to OpenVEX's inheritance rules.
    run([binary, "attest", "--file", str(attestation), str(vex_file)], directory, f"{architecture}-openvex-attest")
    return attestation


def prepare(image: str, directory: Path, expected_base: str | None = None) -> dict[str, dict[str, str]]:
    directory.mkdir(parents=True, exist_ok=True)
    image = image.removeprefix("registry://")
    if not re.fullmatch(r"[^\s@]+@" + DIGEST, image):
        raise ValueError("The published image must be addressed by immutable digest")
    if ":" not in image.split("@")[0].rsplit("/", 1)[-1]:
        raise ValueError("Include the existing tag as repository:tag@sha256:digest for Scout registration")
    provenance = json.loads(docker(["buildx", "imagetools", "inspect", image, "--format", "{{json .Provenance}}"], directory, "provenance"))
    manifest = json.loads(docker(["buildx", "imagetools", "inspect", image, "--raw"], directory, "manifest"))
    repository = image.split("@")[0]
    bundle = {}
    for platform in PLATFORMS:
        architecture = platform.split("/")[1]
        target = next(item["digest"] for item in manifest["manifests"] if item.get("platform", {}).get("os") == "linux" and item["platform"].get("architecture") == architecture)
        base = recorded_base(provenance, platform)
        if expected_base and base != expected_base:
            raise ValueError(f"Published {platform} base differs from the release's pinned base")
        print(f"Checking verified DHI VEX for {platform}: {base}", flush=True)
        upstream = directory / f"{architecture}.upstream.vex.json"
        upstream.unlink(missing_ok=True)
        source = base
        try:
            docker(["scout", "vex", "get", f"registry://{source}", "--platform", platform, "--verify", "--output", str(upstream)], directory, f"{architecture}-vex-runtime")
        except subprocess.CalledProcessError as exc:
            if "no VEX attestations found for image" not in (exc.stdout or "") + (exc.stderr or ""):
                raise
            # An explicit empty upstream result is not an exclusion. Do not
            # substitute another variant or architecture's assessment.
            bundle[platform] = {"base": base, "image": f"{repository}@{target}", "vex": "", "attestation": ""}
            print(f"No upstream VEX for {platform}; findings remain visible", flush=True)
            continue
        sboms = []
        for name, reference in (("base", source), ("child", image)):
            output = directory / f"{architecture}-{name}.spdx.json"
            output.unlink(missing_ok=True)
            docker(["scout", "sbom", f"registry://{reference}", "--platform", platform, "--format", "spdx", "--output", str(output)], directory, f"{architecture}-{name}-sbom")
            sboms.append(json.loads(output.read_text()))
        document = json.loads(upstream.read_text())
        validate_passthrough(document, *sboms)
        slsa = provenance[platform]["SLSA"]
        built_at = slsa.get("runDetails", {}).get("metadata", {}).get("finishedOn") or slsa.get("metadata", {}).get("buildFinishedOn")
        vex_file = directory / f"{architecture}.vex.json"
        target_image = f"{repository}@{target}"
        vex_file.write_text(json.dumps(derive(document, sboms[1], target_image, source, built_at), indent=2) + "\n")
        attestation = validate_and_attest(vex_file, directory, architecture, upstream)
        bundle[platform] = {"base": base, "source": source, "image": target_image, "vex": str(vex_file), "attestation": str(attestation)}
    (directory / "sources.json").write_text(json.dumps(bundle, indent=2) + "\n")
    return bundle


def publish(bundle: dict[str, dict[str, str]], directory: Path) -> None:
    client = None
    for platform, source in bundle.items():
        # The architecture-specific subject prevents one platform's VEX crossing to another.
        if not source["attestation"]:
            continue
        attestation = Path(source["attestation"]).resolve()
        issued = json.loads(Path(source["vex"]).read_text())["timestamp"]
        repository, digest = source["image"].split("@")
        repository = re.sub(r":[^/:]+$", "", repository).removeprefix("docker.io/")
        run([os.environ.get("ORAS", "oras"), "attach", "--artifact-type", "application/vnd.in-toto+json",
             "--distribution-spec", "v1.1-referrers-api",
             "--annotation", f"in-toto.io/predicate-type={PREDICATE}",
             "--annotation", f"org.opencontainers.image.created={issued}",
             f"docker.io/{repository}@{digest}", f"{attestation.name}:application/vnd.in-toto+json"],
            directory, platform.replace("/", "-") + "-publish", cwd=attestation.parent)
        # Scout currently discovers its own referrer service separately from
        # general OCI referrers on Hub. Register the same validated predicate
        # there as well; --referrer avoids rewriting the published image index.
        docker(["scout", "attestation", "add", "--org", repository.split("/")[0],
                "--referrer", "--file", source["vex"], "--predicate-type", PREDICATE,
                source["image"]], directory, platform.replace("/", "-") + "-scout-publish")
        if client is None:
            client = scout_exceptions.Client(directory / "scout-api")
        evidence = directory / platform.replace("/", "-")
        evidence.mkdir(exist_ok=True)
        scout_exceptions.publish(client, json.loads(Path(source["vex"]).read_text()), source["image"], evidence)
        print(f"Published derived OpenVEX for {source['image']} ({platform})", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Published repository:tag@sha256:digest")
    parser.add_argument("--expected-base", help="Expected pinned runtime base for a new release")
    parser.add_argument("--output-dir", type=Path, default=Path("vex-reports"))
    parser.add_argument("--publish", action="store_true", help="Attach verified VEX to published platform digests")
    args = parser.parse_args()
    bundle = prepare(args.image, args.output_dir, args.expected_base)
    if args.publish:
        publish(bundle, args.output_dir)


if __name__ == "__main__":
    main()
