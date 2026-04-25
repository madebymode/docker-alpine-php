# syntax=docker/dockerfile:1
#
# Three-stage hardened PHP-FPM image for PHP 8.3.
#
# Stage 1 (builder):    dhi.io/php:8.3-dev — DHI's own dev variant, which ships
#                       the PHP source in $PHP_SRC_DIR and a full phpize/compiler
#                       environment. Compiling against DHI's exact headers avoids
#                       the ABI mismatch caused by the official php:fpm-alpine
#                       image (different PCRE2 linking, different compile flags).
# Stage 2 (go-builder): compiles a static FastCGI health probe with no runtime
#                       dependencies — replaces the PHP CLI in stage 3.
# Stage 3 (runtime):    dhi.io/php:8.3-fpm — CIS-hardened, non-root,
#                       read-only rootfs. sh is present; exec in via
#                       `docker exec -it <container> sh`.
#
# FPM handles public web traffic, so this image intentionally omits:
#   - pcntl     (fork/exec primitive, useful for post-exploitation RCE)
#   - PHP CLI   (replaced by a purpose-built static Go binary for healthchecks)
#   - Composer  (build tool, no place in a production runtime)

ARG ALPINE_VERSION

# ---------------------------------------------------------------------------
# Stage 1: builder — DHI dev variant
# ---------------------------------------------------------------------------
FROM dhi.io/php:8.3-alpine${ALPINE_VERSION}-dev AS builder

RUN apk add --no-cache \
    bzip2-dev \
    freetype-dev \
    icu-dev \
    libjpeg-turbo-dev \
    libpng-dev \
    libwebp-dev \
    libxml2-dev \
    libzip-dev \
    mariadb-dev \
    oniguruma-dev \
    pax-utils \
    pcre2-dev

RUN cd $PHP_SRC_DIR/ext/gd && \
    phpize && \
    ./configure --with-jpeg --with-freetype --with-webp && \
    make -j"$(nproc)" install

RUN set -e; \
    for ext in bcmath bz2 exif mysqli pdo_mysql zip; do \
        cd $PHP_SRC_DIR/ext/$ext && \
        phpize && ./configure && make -j"$(nproc)" install; \
    done

RUN mkdir -p /opt/runtime-libs && \
    find $PHP_PREFIX/lib/php/extensions -name '*.so' \
        -exec scanelf --needed --nobanner --format '%n\n' '{}' ';' | \
    tr ',' '\n' | grep -v '^$' | sort -u > /tmp/dep-names.txt; \
    while read -r lib; do \
        find /lib /usr/lib -name "$lib" -print -quit 2>/dev/null; \
    done < /tmp/dep-names.txt | sort -u > /tmp/dep-paths.txt; \
    while read -r f; do \
        scanelf --needed --nobanner --format '%n\n' "$f" 2>/dev/null | tr ',' '\n'; \
    done < /tmp/dep-paths.txt | grep -v '^$' | sort -u | while read -r lib; do \
        find /lib /usr/lib -name "$lib" -print -quit 2>/dev/null; \
    done >> /tmp/dep-paths.txt; \
    sort -u /tmp/dep-paths.txt | while read -r f; do \
        [ -n "$f" ] && cp -L --parents "$f" /opt/runtime-libs; \
    done

RUN mkdir -p /opt/dhi-conf && \
    printf '%s\n' \
        'extension=bcmath.so' \
        'extension=bz2.so' \
        'extension=exif.so' \
        'extension=gd.so' \
        'extension=mysqli.so' \
        'extension=pdo_mysql.so' \
        'extension=zip.so' \
        > /opt/dhi-conf/zz-extensions.ini && \
    printf '%s\n' \
        'opcache.jit=tracing' \
        'opcache.jit_buffer_size=128M' \
        'opcache.memory_consumption=256' \
        'opcache.interned_strings_buffer=16' \
        'opcache.max_accelerated_files=20000' \
        'realpath_cache_size=4096K' \
        'realpath_cache_ttl=600' \
        'expose_php=Off' \
        > /opt/dhi-conf/zz-performance.ini && \
    printf '%s\n' \
        '[www]' \
        'pm.status_path = /status' \
        'pm = dynamic' \
        'pm.max_children = 20' \
        'pm.start_servers = 4' \
        'pm.min_spare_servers = 2' \
        'pm.max_spare_servers = 6' \
        'pm.max_requests = 500' \
        > /opt/dhi-conf/zz-fpm-pool.conf

# ---------------------------------------------------------------------------
# Stage 2: go-builder
# ---------------------------------------------------------------------------
FROM golang:1.26-alpine3.22 AS go-builder

COPY _shared/fcgi-health.go /src/
RUN cd /src && \
    go mod init fcgi-health && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /fcgi-health .

# ---------------------------------------------------------------------------
# Stage 3: hardened runtime
# ---------------------------------------------------------------------------
FROM dhi.io/php:8.3-alpine${ALPINE_VERSION}-fpm

COPY --from=builder $PHP_PREFIX/lib/php/extensions $PHP_PREFIX/lib/php/extensions
COPY --from=builder /opt/runtime-libs/ /
COPY --from=builder /opt/dhi-conf/zz-extensions.ini  $PHP_PREFIX/etc/php/conf.d/zz-extensions.ini
COPY --from=builder /opt/dhi-conf/zz-performance.ini $PHP_PREFIX/etc/php/conf.d/zz-performance.ini
COPY --from=builder /opt/dhi-conf/zz-fpm-pool.conf   $PHP_PREFIX/etc/php-fpm.d/zz-fpm-pool.conf

COPY --from=go-builder /fcgi-health /usr/local/bin/fcgi-health

ENV HOME="/tmp" \
    XDG_CACHE_HOME="/tmp/.cache" \
    PATH="/app/vendor/bin:${PATH}" \
    PHP_INI_SCAN_DIR="$PHP_PREFIX/etc/php/conf.d:/opt/mode/conf.d"

WORKDIR /app
EXPOSE 9000

HEALTHCHECK --interval=5s --timeout=2s --start-period=5s \
  CMD ["/usr/local/bin/fcgi-health"]

CMD ["-F"]
