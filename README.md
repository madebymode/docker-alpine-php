# cross platform alpine-based php 7.1 - 8.5 images

## Container Runtimes

### Using Docker PHP Images from Docker Hub

This repository builds and publishes PHP images optimized for both CLI and FPM use cases, tailored for various PHP versions and their minor releases. Our images are compatible with both ARM64 and x86_64 host architectures and integrate seamlessly with Laravel and other PHP frameworks.

#### Pulling our PHP Docker Images

To get a specific version of our PHP image, use:

```bash
docker pull mxmd/php:<VERSION>-<TYPE>
```

Where:
- `<VERSION>` is the desired PHP major version with the latest minor release (e.g., `7.4`), or you can specify a minor version (e.g., `7.1.33`, `8.1.13`).
- `<TYPE>` is either `cli` or `fpm`.

For example, to pull the PHP 7.4.33 FPM image:

```bash
docker pull mxmd/php:7.4.33-fpm
```

Available versions of our images along with their Docker Hub links:

- [7.1-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.1-cli), [7.1-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.1-fpm)
- [7.2-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.2-cli), [7.2-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.2-fpm)
- [7.3-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.3-cli), [7.3-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.3-fpm)
- [7.4-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.4-cli), [7.4-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=7.4-fpm)
- [8.0-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.0-cli), [8.0-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.0-fpm)
- [8.1-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.1-cli), [8.1-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.1-fpm)
- [8.2-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.2-cli), [8.2-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.2-fpm)
- [8.3-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.3-cli), [8.3-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.3-fpm)
- [8.4-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.4-cli), [8.4-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.4-fpm)
- [8.5-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.5-cli), [8.5-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=8.5-fpm)

Pull the standard PHP 8.5 images with:

```bash
docker pull mxmd/php:8.5-cli
docker pull mxmd/php:8.5-fpm
```

#### Hardened FPM Images (`fpm-hardened`)

For production workloads where PHP-FPM handles public web traffic, use the hardened variants. Unlike CLI images (which run internal jobs with no public exposure), FPM directly handles inbound HTTP requests — so a reduced attack surface matters.

The hardened images use the [CIS Docker Hardened Image (DHI)](https://dhi.io) FPM runtime:

- **Non-root by default** — runs as DHI's `nonroot` user; if you need host UID/GID mapping, set `user:` explicitly in Compose
- **Read-only root filesystem** — `read_only: true`; writable scratch space via `tmpfs` at `/tmp` and `/run`
- **No Composer** — build tooling is excluded from the runtime image
- **Minimal attack surface** — only runtime artifacts copied from the builder stage; no build-deps remain

```bash
docker pull mxmd/php:fpm-hardened-8.5
docker pull mxmd/php:fpm-hardened-8.4
docker pull mxmd/php:fpm-hardened-8.3
docker pull mxmd/php:fpm-hardened-8.2
```

> **Note:** Building locally requires `docker login dhi.io` to pull the DHI base image.

See per-version READMEs for full Compose examples:
- [fpm-hardened/8.5](fpm-hardened/8.5/README.md)
- [fpm-hardened/8.4](fpm-hardened/8.4/README.md)
- [fpm-hardened/8.3](fpm-hardened/8.3/README.md)
- [fpm-hardened/8.2](fpm-hardened/8.2/README.md)

#### Usage with Docker Compose

Use the PHP 8.5 DHI image as your PHP-FPM service in Docker Compose:

```yaml
services:
  php:
    image: mxmd/php:fpm-hardened-8.5
    user: "${HOST_USER_UID:-1000}:${HOST_USER_GID:-1000}"
    read_only: true
    tmpfs:
      - /tmp
      - /run
    expose:
      - "9000"
    volumes:
      - .:/app
      - ./docker-conf/php-ini:/opt/mode/conf.d:ro
```

The project is mounted at `/app`, and PHP loads custom `.ini` files from
`./docker-conf/php-ini` through `/opt/mode/conf.d`. Temporary files use `/tmp`
and `/run`. The image's built-in healthcheck queries FPM using `fcgi-health`.
Configure your web server's FastCGI upstream as `php:9000`.

### Host UID/GID Variables

Set these variables to run PHP with the same UID/GID as the owner of your
bind-mounted project files. The Compose example defaults each value to `1000`:

```bash
HOST_USER_GID
HOST_USER_UID
```

#### Setting these Environment Variables

On `macOS`, you can set them in `~/.extra` or `~/.bash_profile`.

To get `HOST_USER_UID`:

```bash
id -u
```

To get `HOST_USER_GID`:

```bash
id -g
```

To set these on your host machine:

```bash
echo "export HOST_USER_GID=$(id -g)" >> ~/.bash_profile && echo "export HOST_USER_UID=$(id -u)" >> ~/.bash_profile && echo "export DOCKER_USER=$(id -u):$(id -g)" >> ~/.bash_profile
```

### Optional Environment Variables

For standard CLI/FPM images, this variable activates OPcache and production
`php.ini` settings:

```ini
HOST_ENV=production
```

The DHI images include their OPcache and FPM performance settings in the image.

---

## Building Images:

### Flags:

Both local scripts support the following flags:

- `--force`: Forces the building of the Docker image regardless of its creation date.

- `--all`: Commands the script to construct Docker images for all predefined types and versions.

- `--proof-dir [DIR]`: Exports an OCI artifact tarball with `provenance=mode=max` and `sbom=true` into the given directory after the local image build finishes.

### 1. Local Traditional Build (`local-single-arch.sh`):

This script leverages Docker's standard build process, constructing images specifically for the architecture of the host machine.
Internally it now uses `docker buildx build --load` with a shared local `docker-container` builder named `local-buildkit`.
If `DOCKER_HOST` is set, the script creates a dedicated Docker context for that host so Buildx can reuse its TLS configuration for remote daemons.
If `--proof-dir` is set, the script runs a second Buildx export to write an OCI artifact tarball with attestations to disk.

#### How to Use:

To build a Docker image for a specific type and version:
```bash
./local-single-arch.sh --type [TYPE] --version [VERSION]
```

To also export local proof artifacts:
```bash
./local-single-arch.sh --type [TYPE] --version [VERSION] --proof-dir ./out/proof
```

`--load` builds do not keep attestations in the local Docker image store, so `--proof-dir` writes them as OCI artifacts on disk instead.

For building all available types and versions:
```bash
./local-single-arch.sh --all
```

### 2. Local Docker Buildx Multi-Architecture Build (`buildx-local.sh`):

Buildx is a Docker CLI plugin that offers extended features for building images. It is especially valuable for creating multi-architecture images.
These local builds use `--load`, so they do not attach Buildx provenance attestations; the release workflow still publishes provenance.
If `DOCKER_HOST` is set by Docker Machine, the script creates a dedicated Docker context for that host so Buildx can reuse its TLS configuration for remote daemons.
If `--proof-dir` is set, the script runs a second Buildx export to write an OCI artifact tarball with attestations to disk.

#### How to Use:

For a specific type and version:
```bash
./buildx-local.sh --type [TYPE] --version [VERSION]
```

To also export local proof artifacts:
```bash
./buildx-local.sh --type [TYPE] --version [VERSION] --proof-dir ./out/proof
```

For all available types and versions:
```bash
./buildx-local.sh --all
```


## 3. GitHub Actions and CI

The workflows discover image directories containing both a `.env` file and a
`Dockerfile`. Full builds currently include standard CLI/FPM images for PHP
7.1–8.5, the 8.4 MSSQL variants, and hardened FPM images for PHP 8.2–8.5.
Each build reads its PHP version, Alpine line, and image tag settings from the
corresponding `.env` file.

### Workflow Overview

| Workflow | Trigger | Behavior |
| --- | --- | --- |
| [Test Builds](.github/workflows/test-build.yml) | Push to `dev`; same-repository pull request targeting `master` | Validates all discovered images with amd64 and arm64 builds and hardened PHP extension smoke tests on amd64. |
| [Build Docker Images](.github/workflows/release.yml) | Push to `master`; manual run; reusable workflow call | Builds and publishes all discovered images, or a selected set supplied by another workflow. Publishes attestations, image tags, and GitHub releases. |
| [Build DHI Images](.github/workflows/build-dhi.yml) | Manual run; call from the DHI update checker | Uses the shared release workflow to build and publish only `fpm-hardened` images. |
| [Update PHP Alpine Versions](.github/workflows/update-php-alpine-versions.yml) | Daily at **09:00 UTC**; manual run | Updates tracked CLI/FPM PHP patch versions, commits directly, and builds only changed image directories. |
| [Check DHI Base Image Updates](.github/workflows/check-dhi-updates.yml) | Daily at **10:00 UTC**; manual run | Checks DHI builder/runtime digests, commits changes, and rebuilds all hardened FPM images when digests change. |
| [Scan Docker Images for Fixes](.github/workflows/scan-docker-images.yml) | Daily at **11:00 UTC**; manual run | Scans published images with Docker Scout and requests fresh builds only for images with fixable CVEs. |

### Builds, Tags, and Releases

Publishing builds use Docker Buildx and QEMU for `linux/amd64` and `linux/arm64`.
They publish maximum-mode provenance, SBOM attestations, and these Docker Hub
tags:

| Image family | Published tag examples |
| --- | --- |
| Standard CLI/FPM | `8.5.10-cli`, `8.5-cli`, `8.5.10-fpm`, `8.5-fpm` |
| MSSQL | `<PHP_VERSION>-mssql-cli`, `8.4-mssql-cli`, and the corresponding `-fpm` tags |
| Hardened FPM | `fpm-hardened-8.5` and the configured tags for the other hardened versions |

Each tag also receives a timestamped variant with a `-YYYYMMDDHHMM` suffix.
GitHub releases are created for new image-tag prefixes and new published
manifest digests. Digest release notes include the Docker digest, published
tags, and digest references. Each selected image is built and published on every
release-workflow run.

Hardened builds pin both the DHI development and FPM runtime bases using
[`.github/dhi-digests.json`](.github/dhi-digests.json). After publishing, the
release workflow checks the amd64 image for `bcmath`, `bz2`, `exif`, `gd`,
`mysqli`, `pdo_mysql`, and `zip`. The test workflow checks the same extensions
in a locally loaded amd64 image. These runtime smoke tests run on amd64;
build validation covers both architectures.

The shared release workflow accepts these inputs from other workflows:

| Input | Purpose |
| --- | --- |
| `image_type` | Restricts discovery to an image family, such as `fpm-hardened`. Empty selects all families. |
| `image_matrix` | Selects explicit type/version pairs, such as `[{"type":"fpm","version":"8.5"}]`. Requested images must exist in the discovered build set. |
| `ref` | Checks out the commit to build and uses it as the GitHub release target. |
| `fresh_build` | Pulls base images and disables the build cache. Scout-triggered rebuilds enable this. |

### Automated Version and Digest Updates

The PHP updater reads Docker official-images metadata through
[`update_php_alpine_versions.py`](.github/scripts/update_php_alpine_versions.py).
It matches each tracked PHP major/minor version, image type, and Alpine line;
updates stay within existing image directories and configured Alpine lines. Matching
MSSQL directories are updated alongside their standard CLI/FPM counterparts.
Changes are committed directly to the branch the workflow runs on, and only
the affected directories are passed to the release workflow.

The DHI checker inspects the `dev` and `fpm` base tags for every hardened version.
Changed or newly tracked digests are committed, then the DHI build workflow is
called with the exact update commit. A DHI digest change rebuilds all hardened
versions. Both updaters trigger builds after successfully committing and pushing
detected changes.

### Scheduled Docker Scout Scans

The Scout workflow scans the published rolling tags, including MSSQL and
hardened variants. It resolves each tag to one immutable manifest digest and
scans both amd64 and arm64 from that digest. Manual runs can select `all`,
`cli`, `fpm`, or `fpm-hardened`.

Only CVEs with available fixes trigger rebuilds. A finding on either
architecture selects that image directory once, and the release workflow
rebuilds both architectures by pulling base images and rebuilding every layer.
Registry failures, scanner errors, or timeouts fail the scan and stop the
automatic rebuild handoff for that run.

Results appear in the workflow summary. Detailed Markdown reports and logs are
saved in the `scout-reports` artifact for 30 days. Rebuilds pick up fixes available
within the configured versions; findings that require changing a pinned
dependency or base version can remain until that version is updated. The PHP
and DHI update checks are scheduled earlier each day.

The scan-selection regression tests can be run locally with:

```bash
python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v
```

### Running Workflows Manually

Open the repository's **Actions** tab, select a workflow, choose **Run workflow**,
and select the branch. Use **Build Docker Images** for a full publishing build,
**Build DHI Images** for hardened images, or one of the update/scan workflows to
check upstream changes or available fixes first. **Test Builds** runs
automatically on pushes to `dev` and same-repository pull requests to `master`.

### Credentials and Permissions

| Credential | Use |
| --- | --- |
| `DOCKER_HUB_USERNAME` | Repository secret used to log in to Docker Hub and DHI. |
| `DOCKER_HUB_ACCESS_TOKEN` | Repository secret for pulling DHI bases, publishing to `mxmd/php`, and authenticating Docker Scout. |
| `GITHUB_TOKEN` | Supplied automatically by GitHub Actions for repository access, update commits, and GitHub releases. |

The build-test jobs use read-only repository permissions. Update and publishing
jobs request `contents: write`; the Scout scan job uses read access and its
rebuild job requests write access for releases. The configured Docker account
must have access to the target repository, DHI base images, and Docker Scout.
