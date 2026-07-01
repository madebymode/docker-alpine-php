#!/bin/bash

TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false
TARGETPLATFORM=linux/amd64
BUILDER_NAME="${BUILDER_NAME:-local-buildkit}"
BUILDER_CONTEXT_NAME="${BUILDER_CONTEXT_NAME:-${BUILDER_NAME}-context}"
PROOF_DIR=""

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --type) TARGET_TYPE="$2"; shift ;;
        --version) TARGET_VERSION="$2"; shift ;;
        --force) FORCE_BUILD=true ;;
        --all) BUILD_ALL=true ;;
        --platform) TARGETPLATFORM="$2"; shift ;;
        --proof-dir) PROOF_DIR="$2"; shift ;;
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

create_buildx_context() {
  local docker_opts

  if [[ -z "${DOCKER_HOST:-}" ]]; then
    docker context show 2>/dev/null || printf 'default\n'
    return 0
  fi

  docker_opts="host=${DOCKER_HOST}"
  if [[ -n "${DOCKER_TLS_VERIFY:-}" && -n "${DOCKER_CERT_PATH:-}" ]]; then
    docker_opts+=",ca=${DOCKER_CERT_PATH}/ca.pem,cert=${DOCKER_CERT_PATH}/cert.pem,key=${DOCKER_CERT_PATH}/key.pem"
  fi

  # Persist the current Docker host/TLS settings in a real context so Buildx
  # does not fall back to plain HTTP when Docker Machine-style env vars are set.
  docker context rm -f "$BUILDER_CONTEXT_NAME" >/dev/null 2>&1 || true
  docker context create "$BUILDER_CONTEXT_NAME" --docker "$docker_opts" >/dev/null
  printf '%s\n' "$BUILDER_CONTEXT_NAME"
}

setup_buildx_builder() {
  local endpoint

  endpoint="$(create_buildx_context)"

  if docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    docker buildx use "$BUILDER_NAME" >/dev/null
    if docker buildx inspect --bootstrap "$BUILDER_NAME" >/dev/null 2>&1; then
      return 0
    fi

    docker buildx rm "$BUILDER_NAME" >/dev/null 2>&1 || true
  fi

  docker buildx create \
    --name "$BUILDER_NAME" \
    --driver docker-container \
    --use \
    "$endpoint" >/dev/null

  docker buildx inspect --bootstrap "$BUILDER_NAME" >/dev/null
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

resolve_manifest_digest() {
    local ref="$1"
    local digest

    digest=$(
        docker buildx imagetools inspect "$ref" --format '{{.Manifest.Digest}}' 2>/dev/null
    ) || return 1

    [[ -n "$digest" ]] || return 1
    printf '%s\n' "$digest"
}

append_common_build_args() {
    local build_args_name=$1
    local php_version_major="${PHP_VERSION_MAJOR:-}"
    local common_args

    common_args=(
      --build-arg PHP_VERSION="${PHP_VERSION}"
      --build-arg ALPINE_VERSION="${ALPINE_VERSION}"
      --build-arg ALPINE_IMAGE="alpine:${ALPINE_VERSION}"
      --build-arg RUNTIME_BASE_IMAGE="${RUNTIME_BASE_IMAGE}"
      --build-arg RUNTIME_BASE_DIGEST="${RUNTIME_BASE_DIGEST}"
      --file "${DIR}/Dockerfile"
      "${TYPE}/"
    )

    if [[ -n "$php_version_major" ]]; then
      common_args+=(--build-arg PHP_VERSION_MAJOR="${php_version_major}")
    fi

    eval "$build_args_name"'+=("${common_args[@]}")'
}

export_proof_artifact() {
    local proof_name proof_path
    local proof_cmd=(
      docker buildx build
      --builder "${BUILDER_NAME}"
      --platform "${TARGETPLATFORM}"
      --provenance=mode=max
      --sbom=true
      --output
    )

    mkdir -p "${PROOF_DIR}"
    proof_name="${TAG_NAME//\//_}"
    proof_name="${proof_name//:/_}"
    proof_path="${PROOF_DIR}/${proof_name}.oci.tar"

    proof_cmd+=("type=oci,dest=${proof_path}")
    append_common_build_args proof_cmd

    echo "Exporting proof artifact: ${proof_path}"
    "${proof_cmd[@]}"
}

trap cleanup SIGINT SIGTERM

setup_buildx_builder

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
    RUNTIME_BASE_IMAGE=""
    RUNTIME_BASE_DIGEST=""

    if [[ "$TYPE" == "fpm-hardened" ]]; then
        RUNTIME_BASE_IMAGE="dhi.io/php:${PHP_VERSION_MAJOR}-alpine${ALPINE_VERSION}-fpm"
        if ! RUNTIME_BASE_DIGEST="$(resolve_manifest_digest "$RUNTIME_BASE_IMAGE")"; then
            echo "Warning: could not resolve digest for $RUNTIME_BASE_IMAGE; base name label will still be set."
            RUNTIME_BASE_DIGEST=""
        fi
    fi

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

    # The local Docker exporter cannot load attested manifest lists back into
    # the daemon, so keep local `--load` builds single-manifest.
    BUILD_CMD=(
      docker buildx build
      --load
      --no-cache
      --builder "${BUILDER_NAME}"
      --platform "${TARGETPLATFORM}"
      --tag "${TAG_NAME}"
    )
    append_common_build_args BUILD_CMD
    "${BUILD_CMD[@]}"

    if [[ -n "$COMPAT_TAG" ]]; then
        docker tag "${TAG_NAME}" "${COMPAT_TAG}"
    fi

    if [[ -n "${PROOF_DIR}" ]]; then
        export_proof_artifact
    fi
done

cleanup
