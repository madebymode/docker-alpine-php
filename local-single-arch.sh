#!/bin/bash

TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false
TARGETPLATFORM=linux/amd64

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --type) TARGET_TYPE="$2"; shift ;;
        --version) TARGET_VERSION="$2"; shift ;;
        --force) FORCE_BUILD=true ;;
        --all) BUILD_ALL=true ;;
        --platform) TARGETPLATFORM="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if $BUILD_ALL && [[ -n "$TARGET_TYPE" || -n "$TARGET_VERSION" ]]; then
    echo "Error: --all cannot be combined with --type or --version."
    exit 1
fi

if ! $BUILD_ALL && [[ -z "$TARGET_TYPE" && -z "$TARGET_VERSION" ]]; then
    echo "Error: specify --all or at least one of --type/--version."
    exit 1
fi

[[ "${TARGET_VERSION:-}" == "8.4-msql" ]] && TARGET_VERSION="8.4-mssql"

DATE_CMD=date
if [[ "$(uname)" == "Darwin" ]]; then
    if command -v gdate > /dev/null; then
        DATE_CMD=gdate
    else
        echo "Error: GNU date (gdate) is not installed. Install it using Homebrew (brew install coreutils)."
        exit 1
    fi
fi

set -e

cleanup() {
    echo "Cleaning up..."
    exit
}

was_created_last_day() {
    local image="$1"
    local timestamp
    timestamp=$(docker inspect --format '{{.Created}}' "$image")
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

collect_targets() {
    find . \( -path './.git' -o -path './.git/*' \) -prune -o -mindepth 2 -maxdepth 2 -type d -print | sort | while read -r dir; do
        local type="${dir#./}"
        type="${type%/*}"
        local version="${dir##*/}"

        [[ -f "${dir}/.env" && -f "${dir}/Dockerfile" ]] || continue
        [[ -n "$TARGET_TYPE" && "$type" != "$TARGET_TYPE" ]] && continue
        [[ -n "$TARGET_VERSION" && "$version" != "$TARGET_VERSION" ]] && continue

        printf '%s %s\n' "$type" "$version"
    done
}

trap cleanup SIGINT SIGTERM

TARGETS=()
while IFS= read -r line; do TARGETS+=("$line"); done < <(collect_targets)
if [[ "${#TARGETS[@]}" -eq 0 ]]; then
    echo "Error: no matching directories with both .env and Dockerfile."
    exit 1
fi

for target in "${TARGETS[@]}"; do
    read -r TYPE VERSION <<< "$target"
    DIR="${TYPE}/${VERSION}"

    echo "Processing version: ${VERSION}, type: ${TYPE}"

    unset IMAGE_REPO LOCAL_IMAGE_REPO IMAGE_TAG IMAGE_TAG_SUFFIX
    unset IMAGE_COMPAT_REPO LOCAL_IMAGE_COMPAT_REPO IMAGE_COMPAT_TAG LOCAL_IMAGE_COMPAT_TAG
    set -a
    source "${DIR}/.env"
    set +a

    echo "PHP_VERSION: ${PHP_VERSION}"
    echo "ALPINE_VERSION: ${ALPINE_VERSION}"

    TAG_REPO="${LOCAL_IMAGE_REPO:-mode-dev/php}"
    TAG_REF="${IMAGE_TAG:-${PHP_VERSION}-${TYPE}${IMAGE_TAG_SUFFIX:-}}"
    TAG_NAME="${TAG_REPO}:${TAG_REF}"
    COMPAT_TAG=""
    if [[ -n "${LOCAL_IMAGE_COMPAT_REPO:-}" && -n "${LOCAL_IMAGE_COMPAT_TAG:-}" ]]; then
        COMPAT_TAG="${LOCAL_IMAGE_COMPAT_REPO}:${LOCAL_IMAGE_COMPAT_TAG}"
    fi

    echo "TAG_NAME: ${TAG_NAME}"
    if [[ -n "$COMPAT_TAG" ]]; then
        echo "COMPAT_TAG: ${COMPAT_TAG}"
    fi
    echo "DIR: ${DIR}"
    echo "Build context: ${TYPE}/"
    echo "Platform: $TARGETPLATFORM"

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

    docker build --no-cache \
      --tag "${TAG_NAME}" \
      --provenance="mode=max" \
      --build-arg PHP_VERSION="${PHP_VERSION}" \
      --build-arg ALPINE_VERSION="${ALPINE_VERSION}" \
      --build-arg ALPINE_IMAGE="alpine:${ALPINE_VERSION}" \
      --build-arg TARGETPLATFORM="${TARGETPLATFORM}" \
      --file "${DIR}/Dockerfile" \
      "${TYPE}/"

    if [[ -n "$COMPAT_TAG" ]]; then
        docker tag "${TAG_NAME}" "${COMPAT_TAG}"
    fi
done

cleanup
