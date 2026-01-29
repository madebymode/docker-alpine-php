# Hardened PHP-FPM Alpine image
# Runs as www-data by default, no root execution support
# Use init container pattern for volume permissions

ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}

FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-fpm-alpine${ALPINE_VERSION}

ARG PHP_VERSION
ARG ALPINE_VERSION
ENV DISABLE_HEALTHCHECK=false

# Add Repositories
RUN rm -f /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories

# Upgrade
RUN apk update && apk upgrade

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
RUN apk add --update --no-cache \
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

# Configure & Install Extensions
RUN docker-php-ext-configure gd --with-jpeg=/usr/include/ --with-freetype=/usr/include/ --with-webp=/usr/include/ && \
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
    apk del -f .build-deps

LABEL afterapk="php-fpm-alpine-hardened-$PHP_VERSION"

# Bake in production PHP configuration (no runtime modifications)
RUN cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini" && \
    sed -i 's/^expose_php = On/expose_php = Off/' "$PHP_INI_DIR/php.ini" && \
    # Disable SOAP by default (security)
    mv "$PHP_INI_DIR/conf.d/docker-php-ext-soap.ini" "$PHP_INI_DIR/conf.d/docker-php-ext-soap.disabled" || true

# Create and configure status.conf for PHP-FPM status page
RUN echo '[www]' > /usr/local/etc/php-fpm.d/status.conf && \
    echo 'pm.status_path = /status' >> /usr/local/etc/php-fpm.d/status.conf

# Health check script
COPY _shared/php-fpm-healthcheck /usr/local/bin/
RUN chmod +x /usr/local/bin/php-fpm-healthcheck

# Working directory
WORKDIR /app

# Healthcheck
HEALTHCHECK --interval=5s --timeout=1s \
    CMD if [ -z "$DISABLE_HEALTHCHECK" ]; then php-fpm-healthcheck || exit 1; else exit 0; fi

# Copy entrypoint and init-permissions scripts
COPY _shared/entrypoint.sh /usr/local/bin/entrypoint
COPY _shared/init-permissions.sh /usr/local/bin/init-permissions
RUN chmod +x /usr/local/bin/entrypoint /usr/local/bin/init-permissions

# Set entrypoint
ENTRYPOINT ["entrypoint"]

# Default command
CMD ["php-fpm", "-F"]

# Run as non-root - use docker-compose user: to override UID if needed
USER www-data
