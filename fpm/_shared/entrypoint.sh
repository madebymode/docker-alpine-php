#!/bin/sh

# Enable or disable opcache based on HOST_ENV
if [ "$HOST_ENV" = "production" ]; then
    if [ -f "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.disabled" ]; then
        mv "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.disabled" "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.ini"
    fi
    ln -sf "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/conf.d/00-php.ini"
    # Hide PHP version in headers for production
    sed -i 's/^expose_php = On/expose_php = Off/' "$PHP_INI_DIR/conf.d/00-php.ini"
    echo "Production mode enabled"
else
    if [ -f "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.ini" ]; then
        mv "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.ini" "$PHP_INI_DIR/conf.d/docker-php-ext-opcache.disabled"
    fi
    ln -sf "$PHP_INI_DIR/php.ini-development" "$PHP_INI_DIR/conf.d/00-php.ini"
    echo "Development mode enabled"
fi

# Modify www-data user and group IDs to match the host user and group IDs if the arguments are passed and not macOS
if [ -n "$HOST_USER_UID" ] && [ -n "$HOST_USER_GID" ] && [ "$(uname)" != "Darwin" ] && [ "$HOST_USER_GID" != "20" ]; then
    usermod -u $HOST_USER_UID www-data
    groupmod -g $HOST_USER_GID www-data
else
    echo "Skipping usermod and groupmod due to macOS or GID 20"
    # fix warnings for composer v2.8.2+ https://github.com/composer/composer/compare/2.8.1...2.8.2
    git config --global --add safe.directory /app
fi

# bash and sh commands should run as www-data
COMMAND="exec"
if [ -n "$HOST_USER_UID" ] && [ -n "$HOST_USER_GID" ] && [ "$(uname)" != "Darwin" ] && [ "$HOST_USER_GID" != "20" ]; then
    COMMAND="su-exec www-data"
fi
# run as root
if [ "$EXEC_AS_ROOT" = "true" ] || [ "$EXEC_AS_ROOT" = "1" ] || [ "$1" = "php-fpm" ]; then
    COMMAND="exec"
fi

# Disable the health check if $1 isn't php-fpm
if [ "$1" != "php-fpm" ]; then
    export DISABLE_HEALTHCHECK=true
fi

# Execute the passed command with the correct user
$COMMAND "$@"
