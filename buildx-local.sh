#!/usr/bin/env bash
# buildx-local.sh — multi-arch php builds (cli, fpm, fpm-hardened), tags match the directory name

# 1) Defaults (before set -u to avoid unbound vars)
PLATFORMS="linux/amd64"
TARGET_TYPE=""
TARGET_VERSION=""
FORCE_BUILD=false
BUILD_ALL=false

# Determine date command (macOS support)
DATE_CMD=date
if [[ "$(uname)" == "Darwin" ]]; then
  if command -v gdate >/dev/null 2>&1; then
    DATE_CMD=gdate
  else
    echo "Error: GNU date (gdate) is required on macOS. Install via 'brew install coreutils'." >&2
    exit 1
  fi
fi

# 2) Strict mode
set -euo pipefail

# 3) Cleanup on exit
cleanup() {
  echo "Cleaning up buildx builder & context…" >&2
  docker buildx use default >/dev/null 2>&1 || true
  docker buildx rm builder   >/dev/null 2>&1 || true
  docker context rm builder   >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 4) QEMU + Buildx setup
docker run --rm --privileged tonistiigi/binfmt --install all
docker context inspect builder >/dev/null 2>&1 || docker context create builder
docker buildx create builder --use --bootstrap

# 5) Parse flags
while [[ $# -gt 0 ]]; do
  case $1 in
    --type)     TARGET_TYPE="$2"; shift 2 ;;
    --version)  TARGET_VERSION="$2"; shift 2 ;;
    --all)      BUILD_ALL=true;            shift ;;
    --force)    FORCE_BUILD=true;          shift ;;
    --platform) PLATFORMS="$2";            shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# 6) Alias fix (8.4-msql → 8.4-mssql)
[[ "${TARGET_VERSION:-}" == "8.4-msql" ]] && TARGET_VERSION="8.4-mssql"

# 7) Determine matrix
ALL_TYPES=(cli fpm fpm-hardened)
ALL_VERSIONS=(7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.4-mssql 8.5)

if   $BUILD_ALL; then
  TYPES=("${ALL_TYPES[@]}")
  VERSIONS=("${ALL_VERSIONS[@]}")
elif [[ -n "$TARGET_TYPE" && -n "$TARGET_VERSION" ]]; then
  TYPES=("$TARGET_TYPE")
  VERSIONS=("$TARGET_VERSION")
elif [[ -n "$TARGET_VERSION" ]]; then
  TYPES=("${ALL_TYPES[@]}")
  VERSIONS=("$TARGET_VERSION")
elif [[ -n "$TARGET_TYPE" ]]; then
  TYPES=("$TARGET_TYPE")
  VERSIONS=("${ALL_VERSIONS[@]}")
else
  echo "Error: must specify --all or at least one of --type/--version" >&2
  exit 1
fi

# 8) Fail fast if no matching dirs
found=0
for v in "${VERSIONS[@]}"; do
  for t in "${TYPES[@]}"; do
    [[ -f "$t/$v/.env" ]] && found=1
  done
done
if (( found == 0 )); then
  echo "Error: no matching directories for version(s): ${VERSIONS[*]}" >&2
  exit 1
fi

# 9) Helper: skip if built <24h ago
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

# 10) Build loop
for v in "${VERSIONS[@]}"; do
  for t in "${TYPES[@]}"; do
    DIR="$t/$v"
    [[ ! -f "$DIR/.env" ]] && continue

    # Load build args from .env
    set -a
    # shellcheck disable=SC1090
    source "$DIR/.env"
    set +a

    # Tag uses the directory name (v), not PHP_VERSION
    TAG="mxmd/php:${v}-${t}"

    # Skip if fresh and not forced
    if [[ "$FORCE_BUILD" != "true" ]] && was_recent "$TAG"; then
      echo "Skipping $TAG (built <24h ago)" >&2
      continue
    fi

    echo "Building $TAG for $PLATFORMS" >&2
    docker buildx build \
      --load \
      --platform "$PLATFORMS" \
      --tag "$TAG" \
      --build-arg PHP_VERSION="$PHP_VERSION" \
      --build-arg ALPINE_VERSION="$ALPINE_VERSION" \
      --build-arg ALPINE_IMAGE="alpine:$ALPINE_VERSION" \
      --file "$DIR/Dockerfile" \
      "$t/"
  done
done
