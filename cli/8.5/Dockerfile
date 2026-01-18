# Load the PHP version and Alpine version from the .env file
ARG PHP_VERSION=${PHP_VERSION}
ARG ALPINE_VERSION=${ALPINE_VERSION}

# Pull the PHP image with the specified version and Alpine version
FROM --platform=$TARGETPLATFORM  php:${PHP_VERSION}-cli-alpine${ALPINE_VERSION}

# Redefine the ARGs after FROM

ARG PHP_VERSION
ARG ALPINE_VERSION

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
    rsync \
    linux-headers

# Configure & Install Extension
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
    && apk del -f .build-deps

ARG HOST_USER_GID
ARG HOST_USER_UID

LABEL afterapk="php-cli-alpine-$PHP_VERSION"

ARG HOST_ENV=development



# Install Composer with the filename 'composer2'
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer2

# Create a symbolic link named 'composer' that points to 'composer2'
RUN ln -s /usr/local/bin/composer2 /usr/local/bin/composer

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
