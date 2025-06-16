# Load the PHP version and Alpine version from the .env file
ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}

# Pull the PHP image with the specified version and Alpine version
FROM --platform=$TARGETPLATFORM php:${PHP_VERSION}-cli-alpine${ALPINE_VERSION}

# Redefine the ARGs after FROM
ARG PHP_VERSION
ARG ALPINE_VERSION

# Add Alpine repositories
RUN rm -f /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories

# Upgrade base packages
RUN apk update && apk upgrade

# Build dependencies for PHP extensions
RUN apk add --no-cache --virtual .build-deps \
      zlib-dev \
      libjpeg-turbo-dev \
      libpng-dev \
      libxml2-dev \
      bzip2-dev \
      zip \
      libwebp-dev \
      openssl-dev

# App dependencies
RUN apk add --no-cache \
      jpegoptim \
      pngquant \
      optipng \
      vim \
      mysql-client \
      bash \
      shared-mime-info \
      zip \
      git \
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

# Compile & install core PHP extensions
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
      zip && \
    apk del .build-deps

# ─── M S   S Q L   S E R V E R   S U P P O R T ────────────────────────────────

# Accept the EULA for Microsoft ODBC driver
ENV ACCEPT_EULA=Y

# Download & install the ODBC driver + tools, then build and enable the PHP sqlsrv extensions
RUN wget -q https://download.microsoft.com/download/e/4/e/e4e67866-dffd-428c-aac7-8d28ddafb39b/msodbcsql17_17.5.1.1-1_amd64.apk && \
    wget -q https://download.microsoft.com/download/e/4/e/e4e67866-dffd-428c-aac7-8d28ddafb39b/mssql-tools_17.5.1.1-1_amd64.apk && \
    apk add --no-cache --virtual .mssql-deps \
      unixodbc \
      curl \
      gnupg && \
    apk add --no-cache --virtual .phpize-deps \
      $PHPIZE_DEPS \
      unixodbc-dev && \
    apk add --allow-untrusted \
      msodbcsql17_17.5.1.1-1_amd64.apk \
      mssql-tools_17.5.1.1-1_amd64.apk && \
    pecl install sqlsrv pdo_sqlsrv && \
    docker-php-ext-enable sqlsrv pdo_sqlsrv && \
    apk del .phpize-deps .mssql-deps && \
    rm -f msodbcsql17_*.apk mssql-tools_*.apk

# ──────────────────────────────────────────────────────────────────────────────

# Map host user (optional)
ARG HOST_USER_GID
ARG HOST_USER_UID

LABEL afterapk="php-cli-alpine-$PHP_VERSION"
ARG HOST_ENV=development

# Install Composer v2
RUN curl -sS https://getcomposer.org/installer | php -- \
      --install-dir=/usr/local/bin --filename=composer2 && \
    ln -s /usr/local/bin/composer2 /usr/local/bin/composer

ENV COMPOSER_ALLOW_SUPERUSER=1
ENV PATH="./vendor/bin:$PATH"

# Working directory
WORKDIR /

# Entrypoint
COPY _shared/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint
ENTRYPOINT ["entrypoint"]
