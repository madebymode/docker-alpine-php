# ─── args & base image ────────────────────────────────────────────────────────
ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}   # e.g. "3.24"
FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-fpm-alpine${ALPINE_VERSION}

# Redefine ARGs & platform
ARG PHP_VERSION
ARG ALPINE_VERSION
ARG TARGETARCH
ENV DISABLE_HEALTHCHECK=false

# ─── Alpine repos & upgrade ───────────────────────────────────────────────────
RUN rm -f /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories && \
    apk update && apk upgrade

# ─── build-deps for PHP extensions ─────────────────────────────────────────────
RUN apk add --no-cache --virtual .build-deps \
      zlib-dev \
      libjpeg-turbo-dev \
      libpng-dev \
      libxml2-dev \
      bzip2-dev \
      zip \
      libwebp-dev \
      openssl-dev

# ─── runtime deps ───────────────────────────────────────────────────────────────
RUN apk add --no-cache \
      jpegoptim \
      pngquant \
      optipng \
      mysql-client \
      bash \
      shared-mime-info \
      zip \
      curl \
      wget \
      gcompat \
      icu-dev \
      freetype-dev \
      libzip-dev \
      bzip2 \
      libwebp \
      libpng \
      fcgi \
      su-exec \
      shadow \
      rsync \
      linux-headers

# ─── compile & install core PHP extensions ────────────────────────────────────
RUN docker-php-ext-configure gd \
      --with-jpeg=/usr/include/ \
      --with-freetype=/usr/include/ \
      --with-webp=/usr/include/ && \
    docker-php-ext-install \
      exif \
      bcmath \
      bz2 \
      gd \
      intl \
      mysqli \
      pcntl \
      pdo_mysql \
      soap \
      sockets \
      zip \
      opcache && \
    apk del .build-deps

# prep
ARG TARGETARCH
RUN if [ -z "$TARGETARCH" ]; then \
      case "$(uname -m)" in \
        x86_64) TARGETARCH=amd64 ;; \
        aarch64) TARGETARCH=arm64 ;; \
        *) echo "unsupported arch"; exit 1 ;; \
      esac; \
    fi && \
    echo "Building for $TARGETARCH"

# ─── Microsoft SQL Server (multi-arch, Alpine w/ sig verification) ─────────────
ENV ACCEPT_EULA=Y

ARG MSSQL_VERSION=18.7.1.1-1
ARG ODBC_GUID=ade174b7-8cea-4543-91a6-c33ae320c2f0
ARG TOOLS_GUID=a5dcc5e7-6124-49d3-8df4-48d738a0e784

RUN set -eux; \
    # 1) install runtime + dev deps for ODBC & GPG
    apk add --no-cache --virtual .mssql-deps \
      ca-certificates \
      curl \
      gnupg \
      unixodbc \
      unixodbc-dev; \
    \
    # 2) detect arch
    case "$TARGETARCH" in \
      amd64) arch=amd64 ;; \
      arm64) arch=arm64 ;; \
      *) echo "Unsupported arch: $TARGETARCH"; exit 1 ;; \
    esac; \
    \
    # 3) name pkgs & sigs
    ODBC_PKG="msodbcsql18_${MSSQL_VERSION}_${arch}.apk"; \
    ODBC_SIG="msodbcsql18_${MSSQL_VERSION}_${arch}.sig"; \
    TOOLS_PKG="mssql-tools18_${MSSQL_VERSION}_${arch}.apk"; \
    TOOLS_SIG="mssql-tools18_${MSSQL_VERSION}_${arch}.sig"; \
    \
    # 4) download driver & tools + sigs
    curl -fsSL -O "https://download.microsoft.com/download/${ODBC_GUID}/${ODBC_PKG}" \
                 -O "https://download.microsoft.com/download/${ODBC_GUID}/${ODBC_SIG}" \
                 -O "https://download.microsoft.com/download/${TOOLS_GUID}/${TOOLS_PKG}" \
                 -O "https://download.microsoft.com/download/${TOOLS_GUID}/${TOOLS_SIG}"; \
    \
    # 5) import MS key & verify
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --import -; \
    gpg --verify "${ODBC_SIG}" "${ODBC_PKG}"; \
    gpg --verify "${TOOLS_SIG}" "${TOOLS_PKG}"; \
    \
    # 6) install the apks
    apk add --no-cache --allow-untrusted \
      "./${ODBC_PKG}" \
      "./${TOOLS_PKG}"; \
    \
    # 7) build & enable PHP extensions
    apk add --no-cache --virtual .phpize-deps $PHPIZE_DEPS; \
    pecl install sqlsrv pdo_sqlsrv; \
    docker-php-ext-enable sqlsrv pdo_sqlsrv; \
    \
    # 8) cleanup everything
    apk del .mssql-deps .phpize-deps; \
    rm -rf /root/.gnupg \
           "${ODBC_PKG}" "${ODBC_SIG}" \
           "${TOOLS_PKG}" "${TOOLS_SIG}"

# ─── remaining app setup ──────────────────────────────────────────────────────
# Verify EXIF is available in the final runtime before entrypoint toggles.
RUN php -r 'exit(extension_loaded("exif") && function_exists("exif_read_data") && function_exists("exif_imagetype") ? 0 : 1);' && \
    php-fpm -i | grep -F 'EXIF Support => enabled'

ARG HOST_USER_GID
ARG HOST_USER_UID
LABEL afterapk="php-fpm-alpine-$PHP_VERSION"
ARG HOST_ENV=development

ENV PHP_ENABLE_EXIF=0

# PHP-FPM status page
RUN echo '[www]' > /usr/local/etc/php-fpm.d/status.conf && \
    echo 'pm.status_path = /status' >> /usr/local/etc/php-fpm.d/status.conf

# Health check script
COPY _shared/php-fpm-healthcheck /usr/local/bin/
RUN chmod +x /usr/local/bin/php-fpm-healthcheck

WORKDIR /

# Healthcheck
HEALTHCHECK --interval=5s --timeout=1s \
    CMD if [ -z "$DISABLE_HEALTHCHECK" ]; then php-fpm-healthcheck || exit 1; else exit 0; fi

# Entrypoint & default cmd
COPY _shared/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint
ENTRYPOINT ["entrypoint"]
CMD ["php-fpm", "-F"]
