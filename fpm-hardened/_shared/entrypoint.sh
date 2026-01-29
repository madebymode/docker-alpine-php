#!/bin/sh
# Hardened entrypoint - runs as non-root, no modifications
# All permission setup must happen in init container

if [ "$1" != "php-fpm" ]; then
    export DISABLE_HEALTHCHECK=true
fi

exec "$@"
