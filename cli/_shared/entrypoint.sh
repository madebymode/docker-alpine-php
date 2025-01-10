#!/bin/sh

# Modify www-data user and group IDs to match the host user and group IDs if the arguments are passed and not macOS
if [ -n "$HOST_USER_UID" ] && [ -n "$HOST_USER_GID" ] && [ "$(uname)" != "Darwin" ] && [ "$HOST_USER_GID" != "20" ]; then
    usermod -u $HOST_USER_UID www-data
    groupmod -g $HOST_USER_GID www-data
else
    echo "Skipping usermod and groupmod due to macOS or GID 20"
    # fix warnings for composer v2.8.2+ https://github.com/composer/composer/compare/2.8.1...2.8.2
    echo "handling composer 2.8.2+ behaviors for macOS or GID 20"
    git config --global --add safe.directory /app
fi

# Enable or disable SOAP extension based on PHP_ENABLE_SOAP env var
if [ "$PHP_ENABLE_SOAP" = "true" ] || [ "$PHP_ENABLE_SOAP" = "1" ]; then
    if [ -f "$PHP_INI_DIR/conf.d/docker-php-ext-soap.disabled" ]; then
        mv "$PHP_INI_DIR/conf.d/docker-php-ext-soap.disabled" "$PHP_INI_DIR/conf.d/docker-php-ext-soap.ini"
        echo "SOAP extension enabled"
    fi
else
    if [ -f "$PHP_INI_DIR/conf.d/docker-php-ext-soap.ini" ]; then
        mv "$PHP_INI_DIR/conf.d/docker-php-ext-soap.ini" "$PHP_INI_DIR/conf.d/docker-php-ext-soap.disabled"
        echo "SOAP extension disabled"
    fi
fi

# bash and sh commands should run as www-data
COMMAND="exec"
if [ -n "$HOST_USER_UID" ] && [ -n "$HOST_USER_GID" ] && [ "$(uname)" != "Darwin" ] && [ "$HOST_USER_GID" != "20" ]; then
    COMMAND="su-exec www-data"
fi
# run as root
if [ "$EXEC_AS_ROOT" = "true" ] || [ "$EXEC_AS_ROOT" = "1" ]; then
    COMMAND="exec"
fi

# Execute the passed command with the correct user
$COMMAND "$@"
