# Load the PHP version and Alpine version from the .env file
ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}

# Pull the PHP image with the specified version and Alpine version
FROM --platform=$TARGETPLATFORM  php:${PHP_VERSION}-cli-alpine${ALPINE_VERSION}

# Redefine the ARGs after FROM
ARG PLATFORM
ARG PHP_VERSION
ARG ALPINE_VERSION


# Print the platform
RUN echo "Building for platform: ${PLATFORM}"

# Add Repositories
RUN rm -f /etc/apk/repositories &&\
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/main" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VERSION}/community" >> /etc/apk/repositories

# upgrade
RUN apk update && \
  apk upgrade

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

# Add App Dependencies
RUN apk add --update --no-cache \
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
    rsync

# Configure & Install Extension
RUN docker-php-ext-configure gd --with-jpeg-dir=/usr/include/ --with-freetype-dir=/usr/include/ --with-webp-dir=/usr/include/ && \
    docker-php-ext-install \
    mysqli \
    pdo \
    pdo_mysql \
    sockets \
    json \
    intl \
    gd \
    xml \
    bz2 \
    pcntl \
    bcmath \
    zip \
    fileinfo \
    soap \
    phar && \
    apk del -f .build-deps

ARG HOST_USER_GID
ARG HOST_USER_UID

LABEL afterapk="php-cli-alpine-$PHP_VERSION"

ARG HOST_ENV=development

# Install Composer 1.10
RUN curl -sS https://getcomposer.org/installer | php -- --version=1.10.22 --install-dir=/usr/local/bin --filename=composer
# Install Composer 2
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer2
ENV COMPOSER_ALLOW_SUPERUSER=1
ENV PATH="./vendor/bin:$PATH"

# Setup Working Dir to model BH
WORKDIR /

# Copy entrypoint script
COPY _shared/entrypoint.sh /usr/local/bin/entrypoint

# Set permissions for the entrypoint script
RUN chmod +x /usr/local/bin/entrypoint

# Set entrypoint
ENTRYPOINT ["entrypoint"]
