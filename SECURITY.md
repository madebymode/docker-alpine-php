# Security

## Legacy PHP and security backports

We've integrated available AlmaLinux security backports into our PHP 7.2–8.1
CLI and FPM images. The testing described below checks how those patches behave
in our PHP 7.4 FPM build. This is a best-effort approach to keeping legacy applications running
while you move to a supported PHP version. For new production deployments,
we recommend a hardened image on a PHP branch that still receives upstream
security updates.

Each build applies patches from a specific commit recorded in
[`.github/alma-patches.json`](.github/alma-patches.json), then recompiles PHP.
The PHP version and image metadata record that commit so you can identify the
patch set. Available patches differ between branches, and we don't claim the
same coverage as a complete AlmaLinux package or a supported PHP release.

Extensions are compiled against the patched PHP headers, and the final image
includes the matching headers and extension configuration. Build checks confirm
that SOAP loads in CLI and, for FPM images, through FPM.

## What we tested

On October 24, 2026, we tested our PHP 7.4.33 FPM build on **linux/amd64** with
AlmaLinux commit `f9bae1f7c1b113362d7b210974aba3ba3caa8e64`. We ran vendor
regression tests and our own additional checks against the binaries and
extensions in the image, using disposable containers.

These checks passed:

| Area | What we verified |
| --- | --- |
| Backport version | The image metadata and both PHP binaries identify the expected patch commit. |
| Password verification | Malformed bcrypt salts and hashes are rejected. Correct passwords still verify, and incorrect passwords don't. |
| Memory exhaustion | PHP terminates before running application shutdown callbacks when its memory limit is exceeded. An older image without the mitigation failed this check. |
| Session upload progress | The backport prevents upload-progress state from being created while still accepting an ordinary file upload. An older image without the mitigation still created that state. |
| SOAP | SOAP loads in CLI and FPM. Regression tests for malformed data, cleanup after parsing errors, and unusually large names pass. |
| FPM status page | Request information is escaped in the status-page test for CVE-2026-6735. |
| FPM logging | Worker output split across the affected boundaries is handled correctly in the tests for CVE-2024-9026. |
| HTTP and URLs | Selected tests pass for URL validation, malformed response headers, redirects, and header injection through proxy requests. |
| Database drivers | MySQL response-parsing tests pass for known buffer overreads. SQLite rejects an oversized value rather than returning it unquoted. |
| Archives, images, and XML | Selected tests pass for archive bounds errors, image metadata memory exposure, and XML parsing errors. |

Some tests couldn't run because they needed a different platform or additional
services or extensions. We treat those as gaps in coverage. The passing tests
give us evidence that the selected fixes work under the conditions tested;
they don't establish that every vulnerability in these areas is covered.

We also checked a platform difference in bcrypt's error response without
relaxing the password-verification checks. Tests that allocate large amounts
of memory were rerun with enough container memory to let them finish.

## Run the upstream regression tests yourself

You can run the public regression tests against the image and architecture
you deploy. You don't need our local test tooling to get them.

Start with the commit for your PHP branch in
[`.github/alma-patches.json`](.github/alma-patches.json). The
[`php.spec` file for the tested PHP 7.4 commit][php74-spec] lists the patches
in the order they are applied. The patches include `.phpt` tests and supporting
files where available. Here are some of the tests we used:

| Area | Public regression sources |
| --- | --- |
| Malformed bcrypt salts and short hashes | [CVE-2023-0567 patch and tests][bcrypt-tests] |
| SOAP parsing and object cleanup | [CVE-2026-6722][soap-map-tests], [CVE-2026-7261][soap-cleanup-tests], [CVE-2026-7262][soap-value-tests] |
| Large SOAP names | [CVE-2025-6491 patch and test][soap-large-tests] |
| FPM status-page output | [CVE-2026-6735 patch and test][fpm-status-tests] |
| FPM worker-output logging | [CVE-2024-9026 patch and tests][fpm-log-tests] |

Start with a writable copy of the matching PHP source and apply the selected
patches in spec order. Keep the tests and their supporting files together.
Use PHP's [`run-tests.php` runner][php-test-runner] to run them against the
**PHP binary in your image**. Running a `.phpt` file directly with `php` won't
perform the expected-output checks.

For example, inside a disposable container using your image, run this from
the prepared PHP source directory:

```sh
php run-tests.php -q -p /usr/local/bin/php \
  ext/standard/tests/crypt/bcrypt_salt_dollar.phpt
```

Use the runner for your PHP branch and enable the extensions each test needs.
Run FPM tests on a backported FPM image with its own FPM binary, as an
unprivileged user. Keep application data out of the test container: some tests
exhaust memory or terminate workers. The largest SOAP test needed an 8 GiB
container memory limit in our run.

Read the reasons for failures and skips. For example, Alpine may return `*`
where the bcrypt test expects `*0`. Both can indicate failure, but check that
invalid hashes are rejected and valid passwords still work before accepting
the difference. That is what we checked in our validation.

For PHP2Shell, see the [vendor's mitigation][php2shell-backport] and
[Assetnote's scanner][php2shell-scanner]. You can run the scanner against your
own disposable deployment, but read its results alongside the regression
checks. A scan that finds nothing may simply have lost contact with a worker.

## What these results don't cover

- We tested the PHP 7.4 FPM build identified above. Those results don't cover
  every tag, PHP version, architecture, or later rebuild.
- Tests we couldn't run, and patches without regression tests, remain gaps in
  coverage.
- Our PHP2Shell checks ran through CLI and its development server. They verify
  specific mitigation behavior, but don't cover every path involved in
  CVE-2026-109618 and CVE-2026-109619 or FPM worker recovery after memory exhaustion.
- These checks cannot guarantee an image is free of vulnerabilities. Your
  application, dependencies, configuration, and deployment still need their
  own security review.

## Run containers with fewer privileges

Use the [OWASP Docker Security Cheat Sheet][owasp-docker] as a deployment
baseline: run as a non-root user, drop capabilities, prevent privilege
escalation, and limit what the container can access.

### Set a Docker daemon default

On a Linux Docker Engine host, merge these settings into
`/etc/docker/daemon.json`:

```json
{
  "no-new-privileges": true,
  "log-level": "info"
}
```

`no-new-privileges` prevents processes from gaining privileges through setuid,
setgid, or file capabilities when executing a program. It doesn't remove
privileges a process already has, so still run PHP as a non-root user. Docker
supports this as a [default for new containers][docker-daemon]; it doesn't
retrofit containers that are already running.

Keep your existing daemon settings, then validate the combined file:

```sh
sudo dockerd --validate --config-file=/etc/docker/daemon.json
```

Restart Docker during a maintenance window and recreate the affected
containers. For Docker Desktop, merge the settings through **Settings → Docker
Engine**. This is a default, not an enforced policy against someone who can
control the Docker daemon. Keep the per-service settings below so they travel
with your deployment.

### Run PHP as a non-root user

Set an explicit, nonzero UID/GID with Compose's `user` setting or
`docker run --user 1000:1000`. The examples below use `1000:1000`; choose IDs
that own your writable storage and cache directories. Run the FPM master and
its workers as that user, rather than relying only on a root master dropping
privileges for workers.

The hardened images support this model. For standard and backported images,
prepare PHP configuration and user/group IDs when building a derived image,
then launch FPM directly without the entrypoint's configuration and account
changes. Those startup operations need privileges that this setup removes.
FPM listens on port 9000, so it doesn't need permission to bind privileged ports.

Docker's [rootless mode][docker-rootless] also reduces the daemon's host
privileges. It is worth considering where supported, while still selecting a
non-root user inside the container.

### Keep the other isolation controls in place

- Drop all capabilities with `cap_drop: [ALL]`. Add back only a capability your
  application demonstrably needs; don't use `privileged: true`.
- Keep Docker's [default seccomp profile][docker-seccomp] and the host's
  AppArmor or SELinux policy enabled. Avoid `unconfined` profiles.
- Set memory, CPU, and process limits for the workload. Size the container
  memory budget for its FPM pool, rather than copying a fixed value.
  [Docker's resource-limit guidance][docker-resources] explains the tradeoffs.
- Keep the host kernel, Docker, images, and application dependencies updated.
  Scan builds, pin deployment digests, and review updates before deploying them.
- Keep FPM on a private application network with its web server. Don't publish
  port 9000 to the internet. Check Docker's actual port exposure and firewall
  behavior rather than relying on host firewall defaults.
- Don't mount the Docker socket, host root filesystem, or unnecessary devices
  into PHP containers. A read-only socket mount still allows Docker API calls.
  Protect [remote Docker access][docker-socket] with SSH or mutual TLS.
- Supply credentials through your platform's secret mechanism, and keep them
  out of images, source control, and logs. Grant PHP access only to the secrets
  and application data it needs.

## Limit writable files in production

Keep application code, dependencies, and configuration read-only. Allow writes
only where the application needs to store uploads, sessions, cache, or other
runtime data. This makes it harder for a compromised process to change deployed
files. The process can still read or modify anything its permissions allow.

Compose's `read_only: true` protects the container's root filesystem. Bind
mounts need their own `:ro` setting; a writable application mount remains
writable even when the root filesystem is read-only. See the
[Docker Compose reference](https://docs.docker.com/reference/compose-file/services/#read_only).

### Example: hardened FPM with Laravel storage

For Laravel, keep the application read-only and allow writes to `storage` and
`bootstrap/cache`, following
[Laravel's directory requirements](https://laravel.com/framework/docs/deployment#directory-permissions).
Choose an image compatible with your application; pin its digest for deployment.

```yaml
services:
  php:
    image: mxmd/php:fpm-hardened-8.5
    user: "1000:1000"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    mem_limit: "${PHP_CONTAINER_MEMORY_LIMIT:?Set a memory budget for the FPM container}"
    cpus: "1.0"
    pids_limit: 128
    read_only: true
    working_dir: /app
    tmpfs:
      - /tmp:rw,nosuid,nodev,size=128m,mode=1777
      - /run:rw,nosuid,nodev,size=16m,uid=1000,gid=1000,mode=0755
    volumes:
      - ./app:/app:ro
      - ./app/storage:/app/storage:rw
      - ./app/bootstrap/cache:/app/bootstrap/cache:rw
      - ./docker-conf/php-ini:/opt/mode/conf.d:ro
    expose:
      - "9000"
```

Set `PHP_CONTAINER_MEMORY_LIMIT` in your shell or Compose `.env` file before
starting the service. It caps the **whole container**, including all FPM
workers, shared caches, and tmpfs use. PHP's
[`memory_limit`](https://www.php.net/manual/en/ini.core.php#ini.memory-limit)
limits allocations by an individual script; it is a separate setting.

Measure worker memory under representative load, choose `pm.max_children`
accordingly, and leave room for the master process, OPcache, native allocations,
and temporary files. The baked-in pool allows up to 20 workers; reduce that
count for a small container budget. The example deliberately requires you to
choose a budget instead of supplying a universal default.

The corresponding `docker run` settings are `--user 1000:1000`,
`--security-opt no-new-privileges=true`, `--cap-drop ALL`, `--read-only`,
`--memory "$PHP_CONTAINER_MEMORY_LIMIT"`, `--cpus 1`, and `--pids-limit 128`,
together with the required
mounts and tmpfs paths.

After starting the service, you can inspect the main process without needing
a shell in the hardened image:

```sh
docker compose exec php /usr/bin/php -r '
foreach (file("/proc/1/status") as $line) {
    if (preg_match("/^(Uid|Gid|NoNewPrivs|CapEff|Seccomp):/", $line)) {
        echo $line;
    }
}'
```

Confirm the UID/GID values are nonzero, `NoNewPrivs` is `1`, and `CapEff` is
zero. With seccomp filtering enabled, `Seccomp` should be `2`. These checks
verify process settings; also exercise the application under its resource
limits and filesystem permissions.

Create the host directories before starting the container, including the
subdirectories your framework needs. Give the PHP worker's UID/GID write
access to those paths. Install dependencies during the build or deployment,
and refresh generated caches when code changes. If you hit a permissions
error, fix that directory's ownership instead of making the whole app writable.

### Example: Craft CMS writable paths

For Craft, replace the Laravel writable mounts with the paths your site uses:

```yaml
volumes:
  - ./app:/app:ro
  - ./app/storage:/app/storage:rw
  - ./app/web/cpresources:/app/web/cpresources:rw
  - ./app/web/uploads:/app/web/uploads:rw  # Only for a configured local upload directory.
  - ./docker-conf/php-ini:/opt/mode/conf.d:ro
```

Craft requires writable storage and generated control-panel resources; local
asset paths depend on the site's filesystem configuration. Keep project
configuration and dependencies read-only in production, and perform updates
through deployment. See [Craft's filesystem requirements](https://craftcms.com/docs/5.x/requirements)
and [storage layout](https://craftcms.com/docs/5.x/system/directory-structure).

### Preserve data, isolate temporary files

Use persistent volumes, host directories, or external storage for uploads and
other durable application data, and back them up. Use `tmpfs` only for data
that can be discarded: its contents disappear when the container stops.
Caches may use temporary storage if the application can recreate them; sessions
need persistent or shared storage if logins must survive restarts or span
replicas. Configure PHP's upload, session, and temporary paths accordingly.
[Docker's tmpfs documentation](https://docs.docker.com/engine/storage/tmpfs/)
describes its lifecycle and memory limits.

If a separate web server serves uploads or generated assets, give it access to
those paths read-only. Prevent PHP/script execution in public upload directories.
Do not treat an operating-system `noexec` mount as a substitute for web-server
rules: PHP can still interpret readable script files.

These examples use the hardened images. Standard and backported FPM images
change PHP configuration and may update user/group IDs at startup. To use a
read-only root filesystem with those images, prepare that configuration and
those identities in a derived image, then start FPM without the startup
changes. Test startup, uploads, sessions, caches, and background jobs in your
own deployment. We haven't included these application examples in the CVE
regression run.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub Security
Advisories. Avoid including credentials or sensitive system details in public
issues.

## References

These are the sources behind our backports, regression checks, and deployment
recommendations. The AlmaLinux links use the exact PHP 7.4 commit we tested;
check the pin for your PHP branch before using its patches or tests.

- [AlmaLinux PHP specification][php74-spec] lists the patches and their application order. The linked patches in the regression-test section include the test cases where available.
- [PHP's test runner][php-test-runner] runs the `.phpt` cases and checks their expected output.
- [The PHP2Shell backport][php2shell-backport] explains the vendor mitigation; [Assetnote's scanner][php2shell-scanner] provides an additional diagnostic.
- [OWASP's Docker Security Cheat Sheet][owasp-docker] explains the container hardening practices used in our examples.
- Docker documents [daemon settings][docker-daemon], [rootless mode][docker-rootless], [seccomp profiles][docker-seccomp], [resource limits][docker-resources], and [protecting daemon access][docker-socket].

[php74-spec]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SPECS/php.spec
[bcrypt-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2023-0567.patch
[soap-map-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2026-6722.patch
[soap-cleanup-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2026-7261.patch
[soap-value-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2026-7262.patch
[soap-large-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2025-6491.patch
[fpm-status-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2026-6735.patch
[fpm-log-tests]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2024-9026.patch
[php2shell-backport]: https://git.almalinux.org/rpms/php/raw/commit/f9bae1f7c1b113362d7b210974aba3ba3caa8e64/SOURCES/php-cve-2026-109618-109619.patch
[php-test-runner]: https://github.com/php/php-src/blob/php-7.4.33/run-tests.php
[php2shell-scanner]: https://github.com/assetnote/php2shell-scanner

[owasp-docker]: https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html
[docker-daemon]: https://docs.docker.com/reference/cli/dockerd/
[docker-rootless]: https://docs.docker.com/engine/security/rootless/
[docker-seccomp]: https://docs.docker.com/engine/security/seccomp/
[docker-resources]: https://docs.docker.com/engine/containers/resource_constraints/
[docker-socket]: https://docs.docker.com/engine/security/protect-access/
