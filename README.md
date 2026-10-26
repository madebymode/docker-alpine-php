# mxmd/php — Alpine-based PHP images (7.2–8.5)

Multi-architecture (`linux/amd64`, `linux/arm64`) PHP images built on Alpine Linux for development and production use. Published to [`mxmd/php`](https://hub.docker.com/r/mxmd/php) on Docker Hub.

---

## Image Families

Three image families cover the range from local development to hardened production:

| Family | Tags | Use case |
| --- | --- | --- |
| **CLI** | `8.5-cli`, `8.5.12-cli` | Artisan commands, queue workers, cron jobs, CI runners — any workload that does not receive inbound HTTP |
| **FPM** | `8.5-fpm`, `8.5.12-fpm` | PHP-FPM for development or trusted internal environments |
| **Hardened FPM** | `fpm-hardened-8.5` | PHP-FPM for production web traffic — non-root, read-only rootfs, CIS-hardened base |

For production use, run the **hardened FPM** image on a **currently supported PHP version (8.2 or later)**. The standard CLI and FPM images are development-oriented and include Composer, vim, and other tooling not suited for a production attack surface.

---


## Optional EXIF Extension

All standard CLI and FPM variants, including MSSQL, compile EXIF as a shared
extension. Like SOAP, EXIF is disabled by default and the entrypoint switches its
configuration between `docker-php-ext-exif.ini` and `docker-php-ext-exif.disabled`.
Set `PHP_ENABLE_EXIF=true` or `PHP_ENABLE_EXIF=1` to enable it on each service that
needs it; other values disable it.

```yaml
environment:
  PHP_ENABLE_EXIF: "true"
```

Recreate existing containers after changing the variable. Applications requiring
`ext-exif` need it enabled for Composer and other CLI commands as well as FPM.

Hardened FPM images already include and enable EXIF. Their configuration is
independent of the standard images' entrypoint toggle.

---

## How Images Are Built

### Active PHP versions (8.2–8.5)

Standard CLI and FPM images are built directly from the [official PHP Alpine images](https://hub.docker.com/_/php) on Docker Hub. The base image provides PHP compiled and configured by the PHP Docker maintainers; this repo adds the extensions, tooling, and entrypoint needed for typical Laravel/PHP application stacks.

Each `.env` file in `cli/<version>/` and `fpm/<version>/` pins the PHP patch version and Alpine line. A daily workflow checks Docker Hub for upstream patch releases (e.g. `8.5.11` → `8.5.12`) and automatically bumps the version, commits, and triggers a rebuild.

### EOL PHP versions (7.2–8.1) — AlmaLinux security backports

PHP 7.2 through 8.1 no longer receive upstream security releases. These images use a **two-stage build** to apply selected security patches from [AlmaLinux's `rpms/php` repository](https://git.almalinux.org/rpms/php). This does not reproduce the complete vendor package or guarantee equivalent security coverage; see [the validation results and caveats](SECURITY.md).

**Patcher stage:**
1. Starts `FROM` the official PHP Alpine image for that version (e.g. `php:8.1.34-fpm-alpine3.22`)
2. Downloads the CVE/GHSA-named patches listed in the pinned `php.spec`, in spec order
3. Applies the patches to the extracted PHP source (`docker-php-source extract`)
4. Stamps the AlmaLinux commit SHA into the PHP version so `php --version` reflects the patch set (e.g. `PHP 8.1.34-1.alma.cec9b5f678e7`)
5. Recompiles the PHP binary using the same `./configure` flags as the original image (`php-config --configure-options`)

**Runtime stage:**
Copies the patched `php` (and `php-fpm`) binary into a fresh copy of the official base image, then proceeds identically to the standard build — extensions, Composer, entrypoint.

The pinned AlmaLinux commit SHAs are tracked in [`.github/alma-patches.json`](.github/alma-patches.json). A daily workflow polls AlmaLinux for new commits on each EOL branch and triggers rebuilds when patches land.

**These images are for legacy applications migrating to a supported PHP version — not a long-term substitute for upgrading.**

### Hardened FPM (`fpm-hardened`)

Hardened images use [CIS Docker Hardened Images (DHI)](https://dhi.io) as both the build and runtime base. The build follows a three-stage pattern:

1. **Builder** (`dhi.io/php:<version>-alpine<alpine>-dev`): compiles PHP extensions from source using `phpize`, collects runtime `.so` files and their transitive library dependencies
2. **Go builder** (`golang:alpine`): compiles a static `fcgi-health` binary used as the FPM health probe
3. **Runtime** (`dhi.io/php:<version>-alpine<alpine>-fpm`): a CIS-hardened, non-root, read-only base — copies only the compiled extension artifacts, runtime libraries, and the health probe

The DHI base image digests are pinned in [`.github/dhi-digests.json`](.github/dhi-digests.json) and updated daily. A digest change triggers a full rebuild of all hardened versions.

All hardened versions set a 512 MB per-script PHP memory limit and share
production OPcache settings: OPcache enabled, 256 MB
cache, 32 MB interned strings, 32,531 script keys, timestamp checks disabled, and
JIT disabled with no JIT buffer. Deploy into a fresh FPM container so code changes
take effect. See [performance defaults, overrides, and monitoring](fpm-hardened/PERFORMANCE.md).

---

## Supply Chain Security

### SBOM and Provenance Attestations

Every image published by the release workflow is built with:

- **Maximum-mode provenance** (`--provenance=mode=max`) — records the full build graph including base images, build arguments, and source commit
- **SBOM** (`--sbom=true`, generated by Docker Scout) — attaches a Software Bill of Materials to the image manifest

Hardened releases verify the runtime base's signed DHI VEX and derive an OpenVEX
document under our identity (`https://github.com/madebymode`) for the exact child
image digest and its unchanged package subcomponents. The source is the base
recorded in build provenance. Covered packages must have matching versions and
SHA-256 file checksums. The original Docker document and signature verification
are retained as evidence, and our statements cite that assessment. We do not
attribute our derived-image assertions to Docker.

VEX publication runs after the Docker push, using its returned image digest.
Verification first checks the public Rekor transparency log. If Scout reports
`signature not found in transparency log`, retrieval retries with
`--verify --skip-tlog`, still verifying against Docker's signing key as described
in [Docker's DHI verification guidance](https://docs.docker.com/dhi/how-to/verify/#handle-missing-transparency-log-entries).
Both attempt logs and the verification mode in `sources.json` are retained as
audit evidence. Other verification failures stop publication.

Each published document must pass `vexctl validate --strict` with no errors or
warnings. `vexctl attest` creates the matching in-toto subjects, and ORAS publishes
the complete attestation unchanged as an OCI 1.1 referrer in Docker Hub. This
preserves the existing image tags and digests. The same validated assessment is
also registered with Scout's referrer service. Publication then uses the Docker
Scout GraphQL API to create an organization exception for each reported CVE
covered by a verified `not_affected` statement. Each exception names one exact
platform digest and package version, retains the DHI rationale, and uses the
corresponding OpenVEX justification. Reruns reuse matching exceptions. Publication
reads the image back and requires `isExcepted: true` with the expected exception
ID; authentication, API, scope, or verification failures fail the workflow.
API requests and responses are retained as evidence without credentials.
CI pins vexctl revision
`9f3461445f0ab76553eac55132a9084a2d1a4e63` (the latest tagged release, 0.4.4,
does not include the validator) and ORAS 1.3.6.

Attestations are stored as referrers in the Docker Hub registry alongside the image manifest and can be inspected with:

```bash
docker buildx imagetools inspect mxmd/php:8.5-fpm
```

To retrieve just the SBOM:

```bash
docker buildx imagetools inspect mxmd/php:8.5-fpm \
  --format '{{ json .SBOM.SPDX }}'
```

### Immutable Digest Releases

Every published image creates a GitHub Release tagged with the immutable manifest digest (e.g. `8.5-fpm-sha256-abc123...`). These releases include the Docker digest, all published tags, and digest-pinned pull references. Use the digest reference to guarantee you pull exactly what was built:

```bash
docker pull mxmd/php:8.5-fpm@sha256:<digest>
```

### CVE Scanning

A daily Docker Scout scan checks all published rolling tags across both `linux/amd64` and `linux/arm64`. High or critical CVEs with available fixes trigger an automatic rebuild. Standard CLI and FPM scans include inherited base-image packages, and fresh rebuilds rerun `apk upgrade` to install available Alpine fixes. Hardened scans refresh and publish verified VEX assessments, then apply them with `--vex-location`, `--only-vex-affected`, and explicit trust for our author identity. Base findings remain visible unless covered by VEX. Excluded CVEs do not request rebuilds or enter the release CVE list, and updating VEX metadata does not rebuild the image. An upstream base with no VEX receives no exclusions. Any remaining inherited DHI findings stay in the audit report; the digest updater handles their rebuilds when a new DHI base is available. Only fixable findings in our added layers can trigger a rebuild of the same hardened base. Failed VEX retrieval, signature verification, package checks, validation, or publication makes the scan incomplete and blocks automatic rebuilds for that run. Scan reports and VEX evidence are saved as workflow artifacts for 30 days.

To refresh the VEX exceptions for existing hardened images without building them:

Run **Scan Docker Images for Fixes** with `image_type: fpm-hardened` and
`metadata_only: true`. This preserves daily scans and disables the rebuild job
for that invocation, even if other fixable findings remain. For local use:

```bash
docker login
docker login dhi.io
# Install the pinned vexctl and ORAS versions above and put them on PATH.
# Export DOCKER_HUB_USERNAME and DOCKER_HUB_ACCESS_TOKEN from your secret store.
# The account needs permission to create Scout exceptions in mxmd.
python3 .github/scripts/scan_docker_images.py \
  --image-type fpm-hardened --publish-vex
```

Running the script directly writes reports and a proposed rebuild matrix; only
the GitHub Actions workflow invokes the build workflow for remaining findings.

Organization members can use Scout's server-side exceptions with
`--org mxmd --ignore-suppressed`. Organization exceptions are visible to members;
the portable OpenVEX artifacts remain available to image consumers. Consumers
outside the organization must explicitly accept our VEX author:

```bash
docker scout cves registry://mxmd/php:fpm-hardened-8.5 \
  --vex-author '<.*@docker.com>' \
  --vex-author '^https://github[.]com/madebymode$' --only-vex-affected
```

If a Docker Hub VEX download link returns 404, export the registry artifact with
`docker scout vex get registry://mxmd/php:fpm-hardened-8.5 --platform linux/amd64 --output image.vex.json`.

See [SECURITY.md](SECURITY.md) for the security policy, backport build process,
validation results, [upstream regression tests you can run](SECURITY.md#run-the-upstream-regression-tests-yourself),
and remaining coverage gaps.

---

## Using the Images

### Pulling Images

```bash
# Latest patch release for a major version
docker pull mxmd/php:8.5-cli
docker pull mxmd/php:8.5-fpm

# Specific patch version
docker pull mxmd/php:8.5.12-fpm

# Production hardened FPM
docker pull mxmd/php:fpm-hardened-8.5
```

### Available Versions

**Active (upstream-supported):**
- [8.5-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.5-cli), [8.5-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.5-fpm), [fpm-hardened-8.5](https://hub.docker.com/r/mxmd/php/tags?page=1&name=fpm-hardened-8.5)
- [8.4-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.4-cli), [8.4-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.4-fpm), [fpm-hardened-8.4](https://hub.docker.com/r/mxmd/php/tags?page=1&name=fpm-hardened-8.4), [8.4-mssql-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.4-mssql-cli)
- [8.3-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.3-cli), [8.3-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.3-fpm), [fpm-hardened-8.3](https://hub.docker.com/r/mxmd/php/tags?page=1&name=fpm-hardened-8.3)
- [8.2-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.2-cli), [8.2-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.2-fpm), [fpm-hardened-8.2](https://hub.docker.com/r/mxmd/php/tags?page=1&name=fpm-hardened-8.2)

**EOL (AlmaLinux security backports applied):**
- [8.1-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.1-cli), [8.1-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.1-fpm)
- [8.0-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.0-cli), [8.0-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.0-fpm)
- [7.4-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.4-cli), [7.4-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.4-fpm)
- [7.3-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.3-cli), [7.3-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.3-fpm)
- [7.2-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.2-cli), [7.2-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.2-fpm)

### Hardened FPM with Docker Compose

> **Note:** Building locally requires `docker login dhi.io` to pull the DHI base image.

```yaml
services:
  php:
    image: mxmd/php:fpm-hardened-8.5
    user: "${HOST_USER_UID:-1000}:${HOST_USER_GID:-1000}"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    mem_limit: "${PHP_CONTAINER_MEMORY_LIMIT:?Set a memory budget for the FPM container}"
    cpus: "1.0"
    pids_limit: 128
    read_only: true
    tmpfs:
      - /tmp
      - /run
    expose:
      - "9000"
    volumes:
      - .:/app:ro
      - ./docker-conf/php-ini:/opt/mode/conf.d:ro
```

The project is mounted at `/app`. PHP loads custom `.ini` files from `./docker-conf/php-ini` via `/opt/mode/conf.d`. The built-in healthcheck uses the `fcgi-health` probe over FastCGI. Point your web server's FastCGI upstream at `php:9000`.

Use nonzero UID/GID values. Set `PHP_CONTAINER_MEMORY_LIMIT` in your shell or
Compose `.env` file to a measured budget for the entire FPM pool, and tune
`pm.max_children` to fit. This is separate from PHP's per-script `memory_limit`.
Mount only the application's required storage/cache directories writable.
See [production filesystem guidance and examples](SECURITY.md#limit-writable-files-in-production)
for Laravel and Craft CMS layouts, persistence, and permissions, and
[container security settings](SECURITY.md#run-containers-with-fewer-privileges)
for the Docker daemon default and runtime checks.

See per-version READMEs for full Compose examples:
[fpm-hardened/8.5](fpm-hardened/8.5/README.md) · [fpm-hardened/8.4](fpm-hardened/8.4/README.md) · [fpm-hardened/8.3](fpm-hardened/8.3/README.md) · [fpm-hardened/8.2](fpm-hardened/8.2/README.md)

### Host UID/GID Variables

Set these to run PHP with the same UID/GID as your bind-mounted project files:

```bash
HOST_USER_GID
HOST_USER_UID
```

On macOS, add them to `~/.bash_profile`:

```bash
echo "export HOST_USER_GID=$(id -g)" >> ~/.bash_profile
echo "export HOST_USER_UID=$(id -u)" >> ~/.bash_profile
echo "export DOCKER_USER=$(id -u):$(id -g)" >> ~/.bash_profile
```

### Optional Environment Variables

For standard CLI/FPM images, set `HOST_ENV=production` to activate OPcache and production `php.ini` settings. The hardened DHI images include OPcache and FPM performance settings in the image itself.

---

## Building Locally

Both scripts use `docker buildx build --load` with a shared `docker-container` builder named `local-buildkit`. For EOL versions they read the AlmaLinux commit SHA from `.github/alma-patches.json` and pass it as `ALMA_COMMIT`. If `DOCKER_HOST` is set, the scripts create a dedicated Buildx context to preserve TLS configuration for remote daemons.

### Flags

| Flag | Description |
| --- | --- |
| `--type TYPE` | Image family: `cli`, `fpm`, or `fpm-hardened` |
| `--version VERSION` | PHP version directory (e.g. `8.5`, `7.4`) |
| `--all` | Build every discovered image directory |
| `--force` | Skip the 24-hour recency check and rebuild unconditionally |
| `--platform PLATFORM` | Override target platform (default: `linux/amd64`) |
| `--proof-dir DIR` | Export a second OCI artifact tarball with `provenance=mode=max` and `sbom=true` |

`--load` builds do not attach provenance attestations to the local image store; `--proof-dir` writes them as an OCI artifact on disk instead.

### `local-single-arch.sh` — host-architecture build

```bash
# Build a specific image
./local-single-arch.sh --type cli --version 8.5

# Force rebuild with proof artifacts
./local-single-arch.sh --type fpm --version 7.4 --force --proof-dir ./out/proof

# Build all images
./local-single-arch.sh --all
```

### `buildx-local.sh` — multi-architecture build

```bash
# Single image
./buildx-local.sh --type fpm --version 8.5

# Multi-arch (installs QEMU emulation automatically)
./buildx-local.sh --type cli --version 8.5 --platform linux/amd64,linux/arm64

# All images
./buildx-local.sh --all
```

### Podman-native builds

The Podman scripts do not depend on a `docker` alias or Docker Buildx. On macOS,
start the Podman virtual machine before building:

```bash
podman machine start
```

Build a normal local image with a single target platform:

```bash
./podman-local.sh --type cli --version 8.5
./podman-local.sh --all --force
```

Build a local Podman manifest list for multiple target platforms:

```bash
./podman-multiarch.sh --type cli --version 8.5 \
  --platform linux/amd64,linux/arm64
./podman-multiarch.sh --all
```

Both scripts accept the flags listed above. With Podman, `--proof-dir` exports
an OCI archive of the image or manifest list; it does not add Buildx provenance
or SBOM attestations. A multi-architecture build is kept as a local manifest
list and can be published with `podman manifest push --all`.

---

## CI / Automation

The workflows discover image directories by finding any subdirectory with both a `.env` and a `Dockerfile`. Full builds include CLI/FPM for PHP 7.2–8.5, the 8.4 MSSQL variants, and hardened FPM for PHP 8.2–8.5. Each build reads its PHP version, Alpine line, and tag settings from the `.env` file.

### Workflow Overview

| Workflow | Trigger | Behavior |
| --- | --- | --- |
| [Test Builds](.github/workflows/test-build.yml) | Push to `dev`; PR targeting `master` | Validates all discovered images with amd64 and arm64 builds; runs hardened PHP extension smoke tests on amd64. |
| [Build Docker Images](.github/workflows/release.yml) | Push to `master`; manual; reusable call | Builds and publishes all discovered images (or a selected subset). Publishes SBOM attestations, provenance, image tags, and GitHub releases. |
| [Build DHI Images](.github/workflows/build-dhi.yml) | Manual; called by DHI update checker | Calls the release workflow restricted to `fpm-hardened`. |
| [Check AlmaLinux PHP Security Patches](.github/workflows/check-alma-patches.yml) | Daily **08:00 UTC**; manual | Polls AlmaLinux's `rpms/php` for new commits on EOL branches (7.2–8.1). Updates `.github/alma-patches.json` and rebuilds all EOL images when patches change. |
| [Update PHP Alpine Versions](.github/workflows/update-php-alpine-versions.yml) | Daily **09:00 UTC**; manual | Checks Docker Hub for upstream PHP patch releases; bumps `.env` files and rebuilds affected images. |
| [Check DHI Base Image Updates](.github/workflows/check-dhi-updates.yml) | Daily **10:00 UTC**; manual | Inspects DHI builder/runtime digests; commits changes to `dhi-digests.json` and rebuilds all hardened images when digests change. |
| [Scan Docker Images for Fixes](.github/workflows/scan-docker-images.yml) | Daily **11:00 UTC**; manual | Runs Docker Scout across all published tags (both architectures). Triggers a fresh rebuild for any image with fixable CVEs. |

### Tags and Releases

| Image family | Published tags |
| --- | --- |
| Standard CLI/FPM | `8.5.12-cli`, `8.5-cli`, `8.5.12-fpm`, `8.5-fpm` |
| MSSQL | `8.4.27-mssql-cli`, `8.4-mssql-cli` (and `-fpm` variants) |
| Hardened FPM | `fpm-hardened-8.5` |

Each tag also gets a timestamped variant (`-YYYYMMDDHHMM`). GitHub Releases are created for new tag prefixes and for each new published manifest digest. Digest releases include the Docker digest, all published tags, and digest-pinned pull references.

### Automated Updates

**AlmaLinux patch checker** — queries the Gitea API for the HEAD commit of each EOL branch (`a8-stream-7.2` through `a9-stream-8.1`). A new commit updates `.github/alma-patches.json` and triggers EOL image rebuilds.

**PHP version updater** — reads Docker official-images metadata, matches each tracked PHP `major.minor` + Alpine line, and bumps the `PHP_VERSION` field in matching `.env` files. Only affected directories are passed to the release workflow.

**DHI digest checker** — inspects the `dev` and `fpm` DHI base tags for every hardened version. Changed digests are committed to `.github/dhi-digests.json`; any change rebuilds all hardened versions.

All three updaters commit directly to `master` and hand off to the release workflow only after a successful push.

### Hardened Image Smoke Tests

After publishing, the release workflow pulls the amd64 hardened image and verifies these extensions are loaded: `bcmath`, `bz2`, `exif`, `gd`, `mysqli`, `pdo_mysql`, `zip`. Both workflows also start an isolated, read-only FPM container and make three FastCGI requests to verify the effective performance settings, the 512 MB script limit, Craft-required PHP extensions, active OPcache, and disabled JIT with no buffer. The test workflow checks a locally loaded build. Smoke tests run on amd64 only; the build itself covers both architectures.

Run the FPM performance check locally against a built image:

```bash
bash tests/fpm-performance/run.sh mxmd/php:fpm-hardened-8.2
```

The check uses a disposable anonymous volume and removes its container and volume on exit. It does not need a host port or access to an application.

### Updating Pinned MSSQL Driver Versions

The MSSQL variants download the Microsoft ODBC driver and `mssql-tools18` at hardcoded versions. These are **not updated by automatic rebuilds** — a CVE in `msodbcsql18` or `mssql-tools18` requires a manual bump.

Find the latest version on the [Microsoft ODBC driver for SQL Server (Alpine) install page](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server?view=sql-server-ver17&tabs=alpine18-install), then update these `ARG` lines in both `fpm/8.4-mssql/Dockerfile` and `cli/8.4-mssql/Dockerfile`:

```dockerfile
ARG MSSQL_VERSION=<new-version>   # e.g. 18.7.1.1-1
ARG ODBC_GUID=<new-odbc-guid>     # from the msodbcsql18 download URL
ARG TOOLS_GUID=<new-tools-guid>   # from the mssql-tools18 download URL
```

The GUIDs are the UUID path segments in the `download.microsoft.com/download/<GUID>/` URLs shown in the Microsoft install docs.

### Running Workflows Manually

Open the **Actions** tab, select a workflow, and choose **Run workflow**. Use **Build Docker Images** for a full publish; leave `fresh_build` enabled to rerun package upgrades. Standard CLI/FPM builds always pull their base tags, including test builds. DHI builder/runtime references remain pinned to the recorded digests. Use **Build DHI Images** for hardened only, or the individual update/scan workflows to check upstream changes first. **Test Builds** runs automatically on pushes to `dev` and PRs targeting `master`.

The scan-selection regression tests can be run locally:

```bash
python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v
```

### Credentials and Permissions

| Credential | Use |
| --- | --- |
| `DOCKER_HUB_USERNAME` | Log in to Docker Hub and DHI |
| `DOCKER_HUB_ACCESS_TOKEN` | Pull DHI bases, publish to `mxmd/php`, authenticate Docker Scout |
| `GITHUB_TOKEN` | Supplied automatically; used for update commits and GitHub releases |

Build/test jobs use read-only repository permissions. Update and publish jobs request `contents: write`. The Scout scan job uses read access; its rebuild job requests write access for releases.
