ARG PHP_VERSION
ARG ALPINE_VERSION
ARG ALMA_COMMIT

FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-fpm-alpine${ALPINE_VERSION} AS php-patcher

ARG ALMA_COMMIT

RUN apk add --no-cache \
    patch wget jq \
    autoconf dpkg-dev file g++ gcc libc-dev make pkgconf re2c \
    argon2-dev bzip2-dev curl-dev freetype-dev gnu-libiconv-dev icu-dev libjpeg-turbo-dev \
    libpng-dev libwebp-dev libxml2-dev libzip-dev oniguruma-dev openssl-dev \
    sqlite-dev readline-dev libedit-dev libsodium-dev zlib-dev

RUN docker-php-source extract

RUN set -eux; \
    test -n "${ALMA_COMMIT}"; \
    mkdir -p /tmp/patches; \
    wget -q "https://git.almalinux.org/rpms/php/raw/commit/${ALMA_COMMIT}/SPECS/php.spec" \
         -O /tmp/php.spec; \
    awk '/^Patch[0-9]+:/ { name=$2; if (tolower(name) ~ /-(cve|ghsa)-/) print name }' /tmp/php.spec \
        > /tmp/patch-order.txt; \
    while IFS= read -r name; do \
        wget -q "https://git.almalinux.org/rpms/php/raw/commit/${ALMA_COMMIT}/SOURCES/${name}" \
             -O "/tmp/patches/${name}"; \
    done < /tmp/patch-order.txt; \
    echo "Patches to apply (in spec order):"; cat /tmp/patch-order.txt; \
    test "$(wc -l < /tmp/patch-order.txt)" -gt 0

WORKDIR /usr/src/php
RUN while IFS= read -r name; do \
        p="/tmp/patches/${name}"; \
        [ -f "$p" ] || continue; \
        echo "Applying: $p"; \
        patch -p1 < "$p" || exit 1; \
    done < /tmp/patch-order.txt

RUN cp /usr/include/gnu-libiconv/iconv.h /usr/include/iconv.h && \
    ./configure $(php-config --configure-options) --with-iconv=/usr && \
    SHORT_SHA=$(echo "${ALMA_COMMIT}" | cut -c1-12); \
    ORIG=$(awk -F'"' '/^#define PHP_VERSION "/{print $2; exit}' main/php_version.h); \
    sed -i "s|#define PHP_EXTRA_VERSION \"\"|#define PHP_EXTRA_VERSION \"-1.alma.${SHORT_SHA}\"|" main/php_version.h; \
    sed -i "s|#define PHP_VERSION \"${ORIG}\"|#define PHP_VERSION \"${ORIG}-1.alma.${SHORT_SHA}\"|" main/php_version.h; \
    sed -i '/^CFLAGS/s/$/ -Wno-incompatible-pointer-types/' Makefile && \
    make -j$(nproc) sapi/cli/php sapi/fpm/php-fpm && \
    cp sapi/cli/php /usr/local/bin/php && \
    cp sapi/fpm/php-fpm /usr/local/sbin/php-fpm && \
    make install-headers

RUN docker-php-ext-configure gd --with-jpeg=/usr/include/ --with-freetype=/usr/include/ --with-webp=/usr/include/ && \
    docker-php-ext-install \
    mysqli pdo pdo_mysql soap sockets json intl gd xml bz2 pcntl bcmath zip fileinfo phar opcache

FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-fpm-alpine${ALPINE_VERSION}

ARG PHP_VERSION
ARG ALPINE_VERSION
ARG ALMA_COMMIT
ENV DISABLE_HEALTHCHECK=false

COPY --from=php-patcher /usr/local/bin/php /usr/local/bin/php
COPY --from=php-patcher /usr/local/sbin/php-fpm /usr/local/sbin/php-fpm
COPY --from=php-patcher /usr/local/lib/php/extensions/ /usr/local/lib/php/extensions/
COPY --from=php-patcher /usr/local/include/php/ /usr/local/include/php/
COPY --from=php-patcher /usr/local/etc/php/conf.d/ /usr/local/etc/php/conf.d/

RUN rm -f /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories

RUN apk update && apk upgrade

RUN apk add --update --no-cache \
    jpegoptim pngquant optipng mysql-client bash shared-mime-info \
    zip curl wget gcompat icu-dev freetype-dev libzip-dev bzip2 \
    libjpeg-turbo libwebp libpng fcgi su-exec shadow rsync gnu-libiconv

# Check the final runtime, including its headers, libraries, and default INI files.
RUN php -r 'exit(extension_loaded("soap") && class_exists("SoapClient") && class_exists("SoapServer") ? 0 : 1);' && \
    php-fpm -i | grep -F 'Soap Client => enabled'

ARG HOST_USER_GID
ARG HOST_USER_UID

LABEL afterapk="php-fpm-alpine-$PHP_VERSION"
LABEL com.mxmd.alma-commit="${ALMA_COMMIT}"

ARG HOST_ENV=development

RUN echo '[www]' > /usr/local/etc/php-fpm.d/status.conf && \
    echo 'pm.status_path = /status' >> /usr/local/etc/php-fpm.d/status.conf

COPY _shared/php-fpm-healthcheck /usr/local/bin/
RUN chmod +x /usr/local/bin/php-fpm-healthcheck

WORKDIR /

HEALTHCHECK --interval=5s --timeout=1s \
    CMD if [ -z "$DISABLE_HEALTHCHECK" ]; then php-fpm-healthcheck || exit 1; else exit 0; fi

COPY _shared/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint
ENTRYPOINT ["entrypoint"]

CMD ["php-fpm", "-F"]
