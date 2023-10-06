#!/bin/bash

TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --type) TARGET_TYPE="$2"; shift ;;
        --version) TARGET_VERSION="$2"; shift ;;
        --force) FORCE_BUILD=true ;;
        --all) BUILD_ALL=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# If --all is passed, disregard TARGET_TYPE and TARGET_VERSION
if $BUILD_ALL; then
    TARGET_TYPE=""
    TARGET_VERSION=""
else
    # Check for missing parameters only if --all is not set
    if [[ -z "$TARGET_TYPE" ]]; then
        echo "Error: Missing --type parameter."
        exit 1
    fi

    if [[ -z "$TARGET_VERSION" ]]; then
        echo "Error: Missing --version parameter."
        exit 1
    fi
fi

DATE_CMD=date
if [[ "$(uname)" == "Darwin" ]]; then
    # If on macOS, check if gdate is available
    if command -v gdate > /dev/null; then
        DATE_CMD=gdate
    else
        echo "Error: GNU date (gdate) is not installed. Install it using Homebrew (brew install coreutils)."
        exit 1
    fi
fi

# Exit immediately if a command exits with a non-zero status
set -e

# Handle script termination gracefully
cleanup() {
    echo "Cleaning up..."
    exit
}

was_created_last_day() {
    local image="$1"
    local timestamp=$(docker inspect --format '{{.Created}}' "$image")
    local created_time=$($DATE_CMD --date="$timestamp" +%s)
    local current_time=$($DATE_CMD +%s)
    local one_day_in_seconds=86400
    local time_diff=$((current_time - created_time))

    if [ "$time_diff" -lt "$one_day_in_seconds" ]; then
        return 0
    else
        return 1
    fi
}

trap cleanup SIGINT SIGTERM

# Variables
TYPES=("cli" "fpm")
PHP_VERSIONS=("7.1" "7.2" "7.3" "7.4" "8.0" "8.1" "8.2")

TARGET_PHP_VERSIONS=("${PHP_VERSIONS[@]}")
TARGET_TYPES=("${TYPES[@]}")

[ ! -z "$TARGET_VERSION" ] && TARGET_PHP_VERSIONS=("$TARGET_VERSION")
[ ! -z "$TARGET_TYPE" ] && TARGET_TYPES=("$TARGET_TYPE")

for VERSION in "${TARGET_PHP_VERSIONS[@]}"; do
    for TYPE in "${TARGET_TYPES[@]}"; do
        DIR="${TYPE}/${VERSION}"
        echo "Processing version: ${VERSION}, type: ${TYPE}"
        if [[ -f "${DIR}/.env" ]]; then
            # Source environment variables from the .env file
            set -a
            source "${DIR}/.env"
            set +a

            echo "PHP_VERSION: ${PHP_VERSION}"
            echo "ALPINE_VERSION: ${ALPINE_VERSION}"


            TAG_NAME="mode-dev/php:${PHP_VERSION}-${TYPE}"

            echo "TAG_NAME: ${TAG_NAME}"
            echo "DIR: ${DIR}"
            echo "Build context: $TYPE/"


            # Check if the image exists locally
            set +e

            echo "Inspecting image: $TAG_NAME"
            ERROR_MSG=$(docker inspect "$TAG_NAME" 2>&1)
            IMAGE_EXISTS=$?
            if [ $IMAGE_EXISTS -ne 0 ]; then
                echo "Error inspecting image: $ERROR_MSG"
            fi

            set -e


            if [[ $IMAGE_EXISTS -ne 0 ]]; then
                echo "Image $TAG_NAME doesn't exist locally. Building..."
            else
                if $FORCE_BUILD; then
                    echo "Force build enabled. Building $TAG_NAME regardless of its creation date."
                elif was_created_last_day "$TAG_NAME"; then
                    echo "Image $TAG_NAME was created within the last day. Skipping build."
                    continue
                else
                    echo "Image $TAG_NAME is older than a day. Building..."
                fi
            fi

            if [[ -f "${DIR}/Dockerfile" ]]; then
                echo "${DIR}/Dockerfile exists"
            else
                echo "Error: ${DIR}/Dockerfile does not exist"
                exit 1
            fi

            # Build the Docker image locally
            docker build \
              --tag "${TAG_NAME}" \
              --build-arg PHP_VERSION="${PHP_VERSION}" \
              --build-arg ALPINE_VERSION="${ALPINE_VERSION}" \
              --build-arg ALPINE_IMAGE="alpine:${ALPINE_VERSION}" \
              --file "${DIR}/Dockerfile" \
              $TYPE/

        fi
    done
done



cleanup
