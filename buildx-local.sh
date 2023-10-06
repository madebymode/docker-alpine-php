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
    docker context use default || true
    docker builder ls | awk 'NR>1 {print $1}' | grep -v "default" | grep -v "builder" | xargs -I {} docker builder rm {} || true
    docker context rm builder || true
}

# Function to check when the image was last created locally
was_created_last_day() {
    local image="$1"

    # Get the image creation time using docker inspect
    local timestamp=$(docker inspect --format '{{.Created}}' "$image")

    # Convert the timestamp to seconds
    local created_time=$($DATE_CMD --date="$timestamp" +%s)
    local current_time=$($DATE_CMD +%s)
    local one_day_in_seconds=86400

    # Calculate the difference in time
    local time_diff=$((current_time - created_time))

    # If the time difference is less than a day (86400 seconds), return 0 (true)
    if [ "$time_diff" -lt "$one_day_in_seconds" ]; then
        return 0
    else
        return 1
    fi
}

trap 'echo "Error on line $LINENO"' ERR
trap cleanup SIGINT SIGTERM

cleanup

docker context create builder

# Enable Docker experimental features
export DOCKER_CLI_EXPERIMENTAL=enabled

# Create a new builder instance
docker buildx create --use builder

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

            TAG_NAME="mxmd/php:${PHP_VERSION}-${TYPE}"

            # Disable the 'exit on error' behavior
            set +e

            # Attempt to pull the image and capture the output/error
            PULL_OUTPUT=$(docker pull "mxmd/php:${PHP_VERSION}-${TYPE}" 2>&1)
            PULL_STATUS=$?

            # Print the output for debugging
            echo "Pull output for mxmd/php:${PHP_VERSION}-${TYPE}:"
            echo "--------------------------------------"
            echo "$PULL_OUTPUT"
            echo "--------------------------------------"

            # Check for "No such object" error in the pull output
            if [[ $PULL_OUTPUT == *"Error: No such object:"* ]]; then
                echo "Warning: Image mxmd/php:${PHP_VERSION}-${TYPE} not found."
            # Check for "manifest unknown" error in the pull output
            elif [[ $PULL_OUTPUT == *"manifest unknown: manifest unknown"* ]]; then
                echo "Warning: Image mxmd/php:${PHP_VERSION}-${TYPE} manifest unknown."
            # Check for other errors based on the pull command exit status
            elif [[ $PULL_STATUS -ne 0 ]]; then
                echo "Error pulling mxmd/php:${PHP_VERSION}-${TYPE}. Exiting."
                exit 1
            else
              if $FORCE_BUILD; then
                echo "Force build enabled. Building mxmd/php:${PHP_VERSION}-${TYPE} regardless of its creation date."
              elif was_created_last_day "mxmd/php:${PHP_VERSION}-${TYPE}"; then
                echo "Image mxmd/php:${PHP_VERSION}-${TYPE} was created within the last day. Skipping build."
                continue
              fi
            fi

            # Exit immediately if a command exits with a non-zero status
            set -e

            docker buildx build \
              --push \
              --platform linux/amd64,linux/arm64 \
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
exit;
