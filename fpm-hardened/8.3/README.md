# PHP 8.3 FPM Hardened

Three-stage build on top of the [CIS Docker Hardened Image](https://dhi.io) runtime:

| Stage | Base | Purpose |
|-------|------|---------|
| `builder` | `dhi.io/php:8.3-alpine3.22-dev` | Compiles extensions against DHI's exact PHP binary using `$PHP_SRC_DIR` |
| `go-builder` | `golang:1.26-alpine3.22` | Builds the static `fcgi-health` probe binary |
| runtime | `dhi.io/php:8.3-alpine3.22-fpm` | CIS-hardened, non-root, read-only rootfs |

The `-dev` variant is used as the builder because it shares the exact PHP ABI with the runtime — extensions compiled against the official `php:fpm-alpine` image are ABI-incompatible with DHI (different PCRE2 linking).

The resulting image tag is:

```
mxmd/php:fpm-hardened-8.3
```

## Prerequisites

```bash
docker login dhi.io
```

DHI is a paid registry. The dev and fpm base images are pulled at build time.

## Extension set

Compiled from `$PHP_SRC_DIR` in the builder stage:

| Extension | Source |
|-----------|--------|
| bcmath, bz2, exif, gd, mysqli, pdo_mysql, zip | Compiled from PHP source |
| intl, mbstring, opcache, sodium, sockets, xml, dom, curl, openssl | Bundled in DHI runtime |

`pcntl` is intentionally excluded — it exposes fork/exec primitives that are useful for post-exploitation in web-facing containers.

## Performance settings (baked in)

```ini
opcache.jit=tracing
opcache.jit_buffer_size=128M
opcache.memory_consumption=256
opcache.max_accelerated_files=20000
realpath_cache_ttl=600
expose_php=Off
```

FPM pool: `pm=dynamic`, `max_children=20`, `max_requests=500`.

## Runtime model

- Runs as `nonroot` (DHI default) — no root user exists in the image
- `read_only: true` — all writable state goes through bind mounts or tmpfs
- `$PHP_PREFIX=/opt/php-8.3` — DHI's prefix; all PHP paths live here
- No package manager, no Composer

## Debugging

```bash
docker exec -it <container-name> sh
```

## Adding extensions

Build against the dev variant in a multi-stage Dockerfile:

```dockerfile
FROM dhi.io/php:8.3-alpine3.22-dev AS builder
RUN pecl install redis
# OR for bundled extensions:
RUN cd $PHP_SRC_DIR/ext/intl && phpize && ./configure && make && make install

FROM dhi.io/php:8.3-alpine3.22-fpm
COPY --from=builder $PHP_PREFIX/lib/php/extensions $PHP_PREFIX/lib/php/extensions
COPY custom-ext.ini $PHP_PREFIX/etc/php/conf.d/
```

Note: writing files to `$PHP_PREFIX` in the runtime stage requires `COPY`, not `RUN` — the runtime has no root user in `/etc/passwd`.

## Compose example

```yaml
services:
  php:
    image: mxmd/php:fpm-hardened-8.3
    user: "${HOST_USER_UID:-1000}:${HOST_USER_GID:-1000}"
    read_only: true
    tmpfs:
      - /tmp
      - /run
    volumes:
      - .:/app
      - ./docker-conf/php-ini:/opt/mode/conf.d
    environment:
      - PHP_INI_SCAN_DIR=/opt/php-8.3/etc/php/conf.d:/opt/mode/conf.d
```

Mount custom ini files into `/opt/mode/conf.d` — that path is included in `PHP_INI_SCAN_DIR`.

## Craft CMS / framework notes

- Override `HOME_PATH=/app` in your compose environment — framework configs that derive `@webroot` from env vars will otherwise resolve to the host path
- `cpresources` and other writable public dirs must be accessible to the nonroot user via bind mounts
- Session writes require a writable `storage/` bind mount
