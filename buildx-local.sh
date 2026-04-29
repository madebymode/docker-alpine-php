#!/usr/bin/env bash

PLATFORMS="linux/amd64"
TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false
BUILDER_NAME="${BUILDER_NAME:-local-buildkit}"
BUILDER_CONTEXT_NAME="${BUILDER_CONTEXT_NAME:-${BUILDER_NAME}-context}"
PROOF_DIR=""

DATE_CMD=date
if [[ "$(uname)" == "Darwin" ]]; then
  if command -v gdate >/dev/null 2>&1; then
    DATE_CMD=gdate
  else
    echo "Error: GNU date (gdate) is required on macOS. Install via 'brew install coreutils'." >&2
    exit 1
  fi
fi

set -euo pipefail

cleanup() {
  echo "Cleaning up…" >&2
}
trap cleanup EXIT

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

while [[ $# -gt 0 ]]; do
  case $1 in
    --type)     TARGET_TYPE="$2"; shift 2 ;;
    --version)  TARGET_VERSION="$2"; shift 2 ;;
    --all)      BUILD_ALL=true; shift ;;
    --force)    FORCE_BUILD=true; shift ;;
    --platform) PLATFORMS="$2"; shift 2 ;;
    --proof-dir) PROOF_DIR="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if $BUILD_ALL && [[ -n "$TARGET_TYPE" || -n "$TARGET_VERSION" ]]; then
  echo "Error: --all cannot be combined with --type or --version" >&2
  exit 1
fi

if ! $BUILD_ALL && [[ -z "$TARGET_TYPE" && -z "$TARGET_VERSION" ]]; then
  echo "Error: specify --all or at least one of --type/--version" >&2
  exit 1
fi

[[ "${TARGET_VERSION:-}" == "8.4-msql" ]] && TARGET_VERSION="8.4-mssql"

setup_buildx_builder

if [[ "$PLATFORMS" == *","* ]]; then
  docker run --rm --privileged tonistiigi/binfmt --install all
fi

collect_targets() {
  find . -path './.git' -prune -o -mindepth 2 -maxdepth 2 -type d -print | sort | while read -r dir; do
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
    docker buildx imagetools inspect "$ref" --format '{{json .Manifest}}' 2>/dev/null | \
      sed -n 's/.*"digest":"\([^"]*\)".*/\1/p' | head -n 1
  ) || return 1

  [[ -n "$digest" ]] || return 1
  printf '%s\n' "$digest"
}

append_common_build_args() {
  local -n build_args_ref=$1

  build_args_ref+=(
    --build-arg PHP_VERSION="$PHP_VERSION"
    --build-arg ALPINE_VERSION="$ALPINE_VERSION"
    --build-arg ALPINE_IMAGE="alpine:$ALPINE_VERSION"
    --build-arg RUNTIME_BASE_IMAGE="$RUNTIME_BASE_IMAGE"
    --build-arg RUNTIME_BASE_DIGEST="$RUNTIME_BASE_DIGEST"
    --file "$DIR/Dockerfile"
    "$t/"
  )
}

export_proof_artifact() {
  local proof_name proof_path
  local proof_cmd=(
    docker buildx build
    --builder "$BUILDER_NAME"
    --platform "$PLATFORMS"
    --provenance=mode=max
    --sbom=true
    --output
  )

  mkdir -p "$PROOF_DIR"
  proof_name="${TAG//\//_}"
  proof_name="${proof_name//:/_}"
  proof_path="${PROOF_DIR}/${proof_name}.oci.tar"

  proof_cmd+=("type=oci,dest=${proof_path}")
  append_common_build_args proof_cmd

  echo "Exporting proof artifact: $proof_path" >&2
  "${proof_cmd[@]}"
}

TARGETS=()
while IFS= read -r line; do TARGETS+=("$line"); done < <(collect_targets)
if (( ${#TARGETS[@]} == 0 )); then
  echo "Error: no matching directories with both .env and Dockerfile" >&2
  exit 1
fi

was_recent() {
  local img="$1"
  local created
  created=$(
    docker inspect --format '{{.Created}}' "$img" 2>/dev/null \
    || return 1
  )
  local csec=$($DATE_CMD --date="$created" +%s)
  local now=$($DATE_CMD +%s)
  (( now - csec < 86400 ))
}

for target in "${TARGETS[@]}"; do
  read -r t v <<< "$target"
  DIR="$t/$v"

  unset IMAGE_REPO LOCAL_IMAGE_REPO IMAGE_TAG IMAGE_TAG_SUFFIX
  unset IMAGE_COMPAT_REPO LOCAL_IMAGE_COMPAT_REPO IMAGE_COMPAT_TAG LOCAL_IMAGE_COMPAT_TAG
  set -a
  # shellcheck disable=SC1090
  source "$DIR/.env"
  set +a

  TAG_REPO="${IMAGE_REPO:-mxmd/php}"
  TAG_REF="${IMAGE_TAG:-${v}-${t}${IMAGE_TAG_SUFFIX:-}}"
  TAG="${TAG_REPO}:${TAG_REF}"
  TAGS=("$TAG")
  RUNTIME_BASE_IMAGE=""
  RUNTIME_BASE_DIGEST=""

  if [[ "$t" == "fpm-hardened" ]]; then
    RUNTIME_BASE_IMAGE="dhi.io/php:${PHP_VERSION_MAJOR}-alpine${ALPINE_VERSION}-fpm"
    if ! RUNTIME_BASE_DIGEST="$(resolve_manifest_digest "$RUNTIME_BASE_IMAGE")"; then
      echo "Warning: could not resolve digest for $RUNTIME_BASE_IMAGE; base name label will still be set." >&2
      RUNTIME_BASE_DIGEST=""
    fi
  fi

  if [[ -n "${IMAGE_COMPAT_REPO:-}" && -n "${IMAGE_COMPAT_TAG:-}" ]]; then
    TAGS+=("${IMAGE_COMPAT_REPO}:${IMAGE_COMPAT_TAG}")
  fi

  if [[ "$FORCE_BUILD" != "true" ]] && was_recent "$TAG"; then
    echo "Skipping $TAG (built <24h ago)" >&2
    continue
  fi

  echo "Building ${TAGS[*]} for $PLATFORMS" >&2
  BUILD_CMD=(
    docker buildx build
    --builder "$BUILDER_NAME"
    --load
    --platform "$PLATFORMS"
  )
  for tag in "${TAGS[@]}"; do
    BUILD_CMD+=(--tag "$tag")
  done
  append_common_build_args BUILD_CMD
  "${BUILD_CMD[@]}"

  if [[ -n "$PROOF_DIR" ]]; then
    export_proof_artifact
  fi
done
