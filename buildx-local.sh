#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Handle script termination gracefully
cleanup() {
    echo "Cleaning up..."
    docker context use default
    docker context rm builder
    exit
}

trap cleanup SIGINT SIGTERM

docker context use default || true
docker context rm builder || true

docker context create builder

# Enable Docker experimental features
export DOCKER_CLI_EXPERIMENTAL=enabled

# Create a new builder instance
docker buildx create --use builder

# Variables
TYPES=("cli" "fpm")
PHP_VERSIONS=("7.1" "7.2" "7.4" "8.0" "8.1" "8.2")

for TYPE in "${TYPES[@]}"; do
    for VERSION in "${PHP_VERSIONS[@]}"; do
        DIR="${TYPE}/${VERSION}"
        if [[ -f "${DIR}/.env" ]]; then
            # Source environment variables from the .env file
            set -a
            source "${DIR}/.env"
            set +a

            TAG_NAME="mxmd/php:${PHP_VERSION}-${TYPE}"

            docker buildx build \
              --push \
              --platform linux/amd64,linux/arm64 \
              --tag "${TAG_NAME}" \
              --build-arg PHP_VERSION="${PHP_VERSION}" \
              --build-arg ALPINE_VERSION="${ALPINE_VERSION}" \
              --build-arg ALPINE_IMAGE="alpine:${ALPINE_VERSION}" \
              --file "${DIR}/Dockerfile" \
              cli/

        fi
    done
done

cleanup
