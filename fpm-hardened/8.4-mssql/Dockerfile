# Hardened PHP-FPM Alpine image with MSSQL support
# Runs as www-data by default, no root execution support
# Use init container pattern for volume permissions

ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}
FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-fpm-alpine${ALPINE_VERSION}

ARG PHP_VERSION
ARG ALPINE_VERSION
ARG TARGETARCH
ENV DISABLE_HEALTHCHECK=false

# Add Repositories & Upgrade
RUN rm -f /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories && \
    apk update && apk upgrade

# Add Build Dependencies
RUN apk add --no-cache --virtual .build-deps \
    zlib-dev \
    libjpeg-turbo-dev \
    libpng-dev \
    libxml2-dev \
    bzip2-dev \
    zip \
    libwebp-dev \
    openssl-dev

# Add Runtime Dependencies (minimal - no dev tools)
RUN apk add --no-cache \
    jpegoptim \
    pngquant \
    optipng \
    bash \
    shared-mime-info \
    zip \
    curl \
    gcompat \
    icu-dev \
    freetype-dev \
    libzip-dev \
    bzip2 \
    libwebp \
    libpng \
    fcgi \
    linux-headers

# Configure & Install Core PHP Extensions
RUN docker-php-ext-configure gd \
      --with-jpeg=/usr/include/ \
      --with-freetype=/usr/include/ \
      --with-webp=/usr/include/ && \
    docker-php-ext-install \
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

# Detect architecture
ARG TARGETARCH
RUN if [ -z "$TARGETARCH" ]; then \
      case "$(uname -m)" in \
        x86_64) TARGETARCH=amd64 ;; \
        aarch64) TARGETARCH=arm64 ;; \
        *) echo "unsupported arch"; exit 1 ;; \
      esac; \
    fi && \
    echo "Building for $TARGETARCH"

# Microsoft SQL Server (multi-arch, Alpine with sig verification)
ENV ACCEPT_EULA=Y

ARG ODBC_VERSION=18.5.1.1-1
ARG ODBC_GUID=fae28b9a-d880-42fd-9b98-d779f0fdd77f
ARG TOOLS_VERSION=18.4.1.1-1
ARG TOOLS_PATH=7/6/d/76de322a-d860-4894-9945-f0cc5d6a45f8

RUN set -eux; \
    # Install runtime + dev deps for ODBC & GPG
    apk add --no-cache --virtual .mssql-deps \
      ca-certificates \
      curl \
      gnupg \
      unixodbc \
      unixodbc-dev; \
    \
    # Detect arch
    case "$TARGETARCH" in \
      amd64) arch=amd64 ;; \
      arm64) arch=arm64 ;; \
      *) echo "Unsupported arch: $TARGETARCH"; exit 1 ;; \
    esac; \
    \
    # Name pkgs & sigs
    ODBC_PKG="msodbcsql18_${ODBC_VERSION}_${arch}.apk"; \
    ODBC_SIG="msodbcsql18_${ODBC_VERSION}_${arch}.sig"; \
    TOOLS_PKG="mssql-tools18_${TOOLS_VERSION}_${arch}.apk"; \
    TOOLS_SIG="mssql-tools18_${TOOLS_VERSION}_${arch}.sig"; \
    \
    # Download driver & tools + sigs
    curl -fsSL -O "https://download.microsoft.com/download/${ODBC_GUID}/${ODBC_PKG}" \
                 -O "https://download.microsoft.com/download/${ODBC_GUID}/${ODBC_SIG}" \
                 -O "https://download.microsoft.com/download/${TOOLS_PATH}/${TOOLS_PKG}" \
                 -O "https://download.microsoft.com/download/${TOOLS_PATH}/${TOOLS_SIG}"; \
    \
    # Import MS key & verify
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --import -; \
    gpg --verify "${ODBC_SIG}" "${ODBC_PKG}"; \
    gpg --verify "${TOOLS_SIG}" "${TOOLS_PKG}"; \
    \
    # Install the apks
    apk add --no-cache --allow-untrusted \
      "./${ODBC_PKG}" \
      "./${TOOLS_PKG}"; \
    \
    # Build & enable PHP extensions
    apk add --no-cache --virtual .phpize-deps $PHPIZE_DEPS; \
    pecl install sqlsrv pdo_sqlsrv; \
    docker-php-ext-enable sqlsrv pdo_sqlsrv; \
    \
    # Cleanup
    apk del .mssql-deps .phpize-deps; \
    rm -rf /root/.gnupg \
           "${ODBC_PKG}" "${ODBC_SIG}" \
           "${TOOLS_PKG}" "${TOOLS_SIG}"

LABEL afterapk="php-fpm-alpine-hardened-mssql-$PHP_VERSION"

# Bake in production PHP configuration (no runtime modifications)
RUN cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini" && \
    sed -i 's/^expose_php = On/expose_php = Off/' "$PHP_INI_DIR/php.ini" && \
    mv "$PHP_INI_DIR/conf.d/docker-php-ext-soap.ini" "$PHP_INI_DIR/conf.d/docker-php-ext-soap.disabled" || true

# PHP-FPM status page
RUN echo '[www]' > /usr/local/etc/php-fpm.d/status.conf && \
    echo 'pm.status_path = /status' >> /usr/local/etc/php-fpm.d/status.conf

# Health check script
COPY _shared/php-fpm-healthcheck /usr/local/bin/
RUN chmod +x /usr/local/bin/php-fpm-healthcheck

WORKDIR /app

HEALTHCHECK --interval=5s --timeout=1s \
    CMD if [ -z "$DISABLE_HEALTHCHECK" ]; then php-fpm-healthcheck || exit 1; else exit 0; fi

COPY _shared/entrypoint.sh /usr/local/bin/entrypoint
COPY _shared/init-permissions.sh /usr/local/bin/init-permissions
RUN chmod +x /usr/local/bin/entrypoint /usr/local/bin/init-permissions

ENTRYPOINT ["entrypoint"]
CMD ["php-fpm", "-F"]

USER www-data
