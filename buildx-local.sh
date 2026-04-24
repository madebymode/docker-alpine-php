#!/usr/bin/env bash

PLATFORMS="linux/amd64"
TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false

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
  echo "Cleaning up buildx builder & context…" >&2
  docker buildx use default >/dev/null 2>&1 || true
  docker buildx rm builder >/dev/null 2>&1 || true
  docker context rm builder >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --rm --privileged tonistiigi/binfmt --install all
docker context inspect builder >/dev/null 2>&1 || docker context create builder
docker buildx create builder --use --bootstrap

while [[ $# -gt 0 ]]; do
  case $1 in
    --type)     TARGET_TYPE="$2"; shift 2 ;;
    --version)  TARGET_VERSION="$2"; shift 2 ;;
    --all)      BUILD_ALL=true; shift ;;
    --force)    FORCE_BUILD=true; shift ;;
    --platform) PLATFORMS="$2"; shift 2 ;;
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
    --load
    --platform "$PLATFORMS"
  )
  for tag in "${TAGS[@]}"; do
    BUILD_CMD+=(--tag "$tag")
  done
  BUILD_CMD+=(
    --build-arg PHP_VERSION="$PHP_VERSION"
    --build-arg ALPINE_VERSION="$ALPINE_VERSION"
    --build-arg ALPINE_IMAGE="alpine:$ALPINE_VERSION"
    --file "$DIR/Dockerfile"
    "$t/"
  )
  "${BUILD_CMD[@]}"
done
