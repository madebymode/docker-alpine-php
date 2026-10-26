# Hardened PHP-FPM performance

PHP 8.2–8.5 share [`_shared/zz-performance.ini`](_shared/zz-performance.ini).
These images target production, so OPcache is enabled without a startup switch.
The DHI runtime does not implement Server Side Up's `PHP_OPCACHE_*` environment
variables; configure overrides with PHP INI files.

The baseline follows [Server Side Up's production guide](https://serversideup.net/open-source/docker-php/docs/guide/production-performance-tuning),
[Symfony 7.4's OPcache and realpath recommendations](https://symfony.com/doc/7.4/performance.html#configure-opcache-for-maximum-performance),
and [FrankenPHP's recommendation to apply Symfony's PHP tuning](https://frankenphp.dev/docs/performance/).
FrankenPHP-specific thread, worker, and Caddy settings do not apply to PHP-FPM.

PHP's [OPcache directive reference](https://www.php.net/manual/en/opcache.configuration.php)
and [core performance directives](https://www.php.net/manual/en/ini.core.php#ini.performance-tuning)
define the supported settings. The framework guides supply workload-specific
sizing; these image values are not all PHP's upstream defaults.

## Production release review — October 26, 2026

The local amd64 builds contain the following stable PHP releases. Their FPM
settings and OPcache/JIT state passed the runtime smoke check. This records local
image validation, not a production deployment or an application performance test.

| PHP release | Official production INI snapshot |
| --- | --- |
| 8.2.35 | [php.ini-production](https://github.com/php/php-src/blob/php-8.2.35/php.ini-production) |
| 8.3.36 | [php.ini-production](https://github.com/php/php-src/blob/php-8.3.36/php.ini-production) |
| 8.4.27 | [php.ini-production](https://github.com/php/php-src/blob/php-8.4.27/php.ini-production) |
| 8.5.12 | [php.ini-production](https://github.com/php/php-src/blob/php-8.5.12/php.ini-production) |

The OPcache entries in those templates are commented examples, not active
assignments. Check the directive reference and effective runtime values as well.
The review found no unsupported or removed directives in our shared INI.

| Setting | PHP upstream baseline | Image choice |
| --- | --- | --- |
| `memory_limit` | `128M` | `512M`, matching Craft's recommended script budget. |
| `opcache.enable` | `1` | Same. |
| `opcache.enable_cli` | `0` | `1`, following Server Side Up; optional for CLI, unrelated to FPM cache sharing. |
| Opcode memory / interned strings / file keys | `128` / `8` / `10000` | `256` / `32` / `32531`, following Symfony; measure capacity. |
| `opcache.validate_timestamps` | `1` | `0`, conditional on deployment restarts and correct invalidation of runtime-generated PHP. |
| `opcache.force_restart_timeout` / `opcache.save_comments` / `opcache.enable_file_override` | `180` / `1` / `0` | Same. |
| JIT on 8.2–8.3 | `tracing`, buffer `0`: disabled | `disable`, buffer `0`: disabled. |
| JIT on 8.4–8.5 | `disable`, buffer `64M`: disabled | `disable`, buffer `0`: disabled, with no buffer reservation. |
| Preload script / user | Empty | Same. |
| Realpath cache size / TTL | `4M` / `120` | `4096K` / `600`; same size, longer TTL. |
| `expose_php` | On | Off; header policy, not a speed optimization. |

PHP's [installation guide](https://www.php.net/manual/en/opcache.installation.php#opcache.installation.recommended)
also lists CLI OPcache as a tuning option despite the default being off. It is
not needed to enable web OPcache. Override `opcache.enable_cli=0` for CLI commands
that do not benefit from it, particularly when opting into preloading.

The configured file-key count `32531` is an actual supported hash-table size.
Our previous `20000` already rounded up to the same size; this spelling makes the
capacity explicit. Keep the engine's optimizer defaults rather than copying
optimizer masks from older tuning examples. No legacy `opcache.fast_shutdown`
or `opcache.consistency_checks` settings are added.

## Defaults

| Setting | Value | Purpose |
| --- | --- | --- |
| `memory_limit` | `512M` | Limit allocations by each PHP script; independent of OPcache and the container budget. |
| `opcache.enable` | `1` | Cache PHP bytecode in the FPM service. |
| `opcache.enable_cli` | `1` | Enable OPcache for CLI invocations; their cache is separate from FPM. |
| `opcache.memory_consumption` | `256` | Shared opcode cache budget in MB. |
| `opcache.interned_strings_buffer` | `32` | Interned-string budget within the opcode cache, in MB. |
| `opcache.max_accelerated_files` | `32531` | Script-key capacity. |
| `opcache.validate_timestamps` | `0` | Skip file-change checks; requires deployment restarts. |
| `opcache.force_restart_timeout` | `180` | Timeout for a pending OPcache restart, in seconds. |
| `opcache.save_comments` | `1` | Preserve annotations and documentation comments. |
| `opcache.enable_file_override` | `0` | Keep filesystem existence checks independent of OPcache. |
| `opcache.jit` | `disable` | Disable JIT, including activation during a request. |
| `opcache.jit_buffer_size` | `0` | Reserve no shared memory for JIT code. |
| `opcache.preload`, `opcache.preload_user` | empty | Leave application-specific preloading opt-in. |
| `realpath_cache_size`, `realpath_cache_ttl` | `4096K`, `600` | Cache resolved filesystem paths. |
| `expose_php` | `Off` | Omit PHP's version header. |

The JIT setting uses `disable` rather than Server Side Up's `off` to prevent
request-time activation. A startup INI override can still opt in. Ordinary
OPcache optimization remains enabled. These are starting values; tune cache
capacity and the FPM pool to measured application use and the container budget.

## Craft CMS 5 requirements

[Craft's requirements](https://craftcms.com/docs/5.x/requirements.html) specify at
least 256 MB allocated to PHP and recommend 512 MB. The DHI base inherited
`memory_limit=128M`; the shared INI now sets `512M`. This limit applies to each
script's allocations, while `opcache.memory_consumption=256` is a shared cache.
Neither setting is the container's total memory limit. Measure worker memory and
size `pm.max_children` and the container budget accordingly; see
[container resource guidance](../SECURITY.md#run-containers-with-fewer-privileges).
An application INI override can adjust the script limit.

The four amd64 images provide all required PHP extensions, using `pdo_mysql`
as the database driver. The FPM smoke check verifies these extensions and the
512 MB limit. Database version, database privileges, disk space, Composer in the
build/deployment environment, application configuration, and writable paths must
be checked for the actual application.

The inspected images provide `allow_url_fopen`, `proc_open`, `proc_close`,
`proc_get_status`, and `ignore_user_abort`. ImageMagick's `imagick` extension is
not included; Craft can use the required GD extension. Add ImageMagick in a
derived image when the application needs its expanded image handling.

The hardened FPM images deliberately omit `pcntl` and Composer. Run daemonized
queue workers and dependency updates in a suitable CLI/build environment.
Craft's always-writable paths include `storage/`, `config/license.key`, and the
configured control-panel resource directory (normally `web/cpresources/`).
Projects using `public/` as their webroot must adjust the paths. See the
[Craft mount example](../SECURITY.md#example-craft-cms-writable-paths).

## Deployments and development

At deployment, replace or restart every FPM container after changing application
code or INI settings. Warm application caches before directing traffic to the new
service. CLI cache warm-up can populate generated files, but does not populate
FPM's separate in-memory OPcache.

For generated PHP rewritten during normal operation, the application must
invalidate affected OPcache entries correctly or restart the affected FPM service.
A restart is not required when correct invalidation is already implemented. Keep
`opcache.validate_timestamps=1` if the deployment or application cannot guarantee
this. A read-only container root alone does not guarantee immutable code when
host-mounted files can change. A CLI `opcache_reset()` does not reset FPM's cache.
See [PHP's timestamp-validation reference](https://www.php.net/manual/en/opcache.configuration.php#ini.opcache.validate-timestamps).

For development or applications that modify PHP files in place, mount an
override such as `./php-ini/development.ini` into `/opt/mode/conf.d`:

```ini
opcache.validate_timestamps=1
opcache.revalidate_freq=0
```

Alternatively, set `opcache.enable=0` there. The image scans its version-specific
`/etc/php-8.x/conf.d` first and `/opt/mode/conf.d` afterward, so project INI files
override the shared defaults. Restart FPM after changing overrides.

The realpath cache is disabled when `open_basedir` is set, regardless of the
configured size. See [PHP's realpath-cache reference](https://www.php.net/manual/en/ini.core.php#ini.realpath-cache-size).

## Optional JIT and preloading

### Why JIT is disabled

The previous hardened-image baseline enabled tracing JIT with a 128 MB buffer.
The October 26, 2026 Craft entry-editor incident produced invalid Twig compiler
state and native PHP-FPM crashes consistent with a JIT-related runtime failure.
The exact engine defect remains unconfirmed. In [Twig issue #3871](https://github.com/twigphp/Twig/issues/3871),
the original reporter confirmed on November 27, 2023 that disabling JIT stopped
recurrence of similar `setSourceContext()` errors.

The accepted [PHP JIT-defaults RFC](https://wiki.php.net/rfc/jit_config_defaults)
changed the PHP 8.4 defaults from `tracing` with a zero buffer to `disable` with a
64 MB buffer. JIT is disabled in both cases. The 64 MB value is a buffer-size
default, not a requirement when JIT is disabled. Our explicit `disable` plus `0`
keeps the same disabled baseline across PHP 8.2–8.5 while retaining ordinary
OPcache. The script's 512 MB memory limit is independent of both caches.

Disabling JIT is a mitigation for the suspected execution path, not proof of the
incident's root cause. Upgrading PHP alone does not establish that this defect
is fixed. Keep the patched PHP release and compare cold template compilation,
warmed requests, and worker-crash logs in an isolated application environment.

### Opting in

Only opt into JIT after testing correctness and measuring representative requests.
An application INI override can use:

```ini
opcache.jit=tracing
opcache.jit_buffer_size=64M
```

The JIT buffer adds to OPcache's shared-memory reservation, rather than replacing
the opcode cache budget. It is shared by the FPM workers, not allocated per
request. See the [PHP JIT configuration reference](https://www.php.net/manual/en/opcache.configuration.php#ini.opcache.jit).

Preloading needs an application-specific `opcache.preload` path. The script must
exist and work at PHP startup. Preloaded code requires a restart to change even
when timestamp checks are enabled. With CLI OPcache enabled, also account for CLI
invocations loading it. See [PHP preloading](https://www.php.net/manual/en/opcache.preloading.php).

## Verify and monitor

Use `ini_get()`, `php_ini_scanned_files()`, and `opcache_get_status(false)` through
the actual FPM service. CLI output alone does not establish FPM's settings or
cache state. Keep diagnostics internal or access-controlled.

Check `cache_full`, free opcode memory, free interned-string memory,
`num_cached_keys` versus `max_cached_keys`, and `oom_restarts`/`hash_restarts`
after exercising representative routes. Increase the corresponding capacity
when measurements show pressure. Monitor HTTP failures and native FPM crashes
alongside request latency and CPU use.

The CI [performance smoke check](../tests/fpm-performance/run.sh) starts a disposable
FPM service and verifies its settings, script memory limit, required Craft PHP
extensions, and OPcache/JIT state over three FastCGI requests. All four release
builds listed above passed locally on amd64. This verifies the image baseline;
it is not an application benchmark or a reproduction of the Craft incident.
The replacement images have not been published or deployed as part of this work.
