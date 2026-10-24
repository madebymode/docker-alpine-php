#!/usr/bin/env bash

set -euo pipefail

MODE=""
TARGET_TYPE=""
TARGET_VERSION=""
PLATFORMS="linux/amd64"
PROOF_DIR=""
FORCE_BUILD=false
BUILD_ALL=false

usage() {
  cat <<'EOF'
Usage:
  podman-local.sh (--all | [--type TYPE] [--version VERSION]) [options]
  podman-multiarch.sh (--all | [--type TYPE] [--version VERSION]) [options]

Options:
  --type TYPE          Image family (for example: cli, fpm, fpm-hardened)
  --version VERSION    Version directory (for example: 8.5 or 7.4)
  --all                Build every discovered image
  --force              Rebuild even when a recent local result exists
  --platform LIST      Target platform or comma-separated platforms
  --proof-dir DIR      Export the result as an OCI archive
  -h, --help           Show this help
EOF
}

require_value() {
  local flag=$1
  local value=${2:-}
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "Error: $flag requires a value" >&2
    exit 1
  fi
}

while (( $# > 0 )); do
  case $1 in
    --mode)
      require_value "$1" "${2:-}"
      MODE=$2
      shift 2
      ;;
    --type)
      require_value "$1" "${2:-}"
      TARGET_TYPE=$2
      shift 2
      ;;
    --version)
      require_value "$1" "${2:-}"
      TARGET_VERSION=$2
      shift 2
      ;;
    --platform)
      require_value "$1" "${2:-}"
      PLATFORMS=$2
      shift 2
      ;;
    --proof-dir)
      require_value "$1" "${2:-}"
      PROOF_DIR=$2
      shift 2
      ;;
    --all)
      BUILD_ALL=true
      shift
      ;;
    --force)
      FORCE_BUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown flag: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$MODE" != "local" && "$MODE" != "manifest" ]]; then
  echo "Error: invoke this through podman-local.sh or podman-multiarch.sh" >&2
  exit 1
fi

if $BUILD_ALL && [[ -n "$TARGET_TYPE" || -n "$TARGET_VERSION" ]]; then
  echo "Error: --all cannot be combined with --type or --version" >&2
  exit 1
fi

if ! $BUILD_ALL && [[ -z "$TARGET_TYPE" && -z "$TARGET_VERSION" ]]; then
  echo "Error: specify --all or at least one of --type/--version" >&2
  exit 1
fi

[[ "$TARGET_VERSION" == "8.4-msql" ]] && TARGET_VERSION="8.4-mssql"

if ! command -v podman >/dev/null 2>&1; then
  echo "Error: podman was not found in PATH" >&2
  exit 127
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq was not found in PATH" >&2
  exit 127
fi

if ! podman info >/dev/null 2>&1; then
  echo "Error: Podman is not available. On macOS, start it with: podman machine start" >&2
  exit 1
fi

DATE_CMD=date
if [[ "$(uname)" == "Darwin" ]]; then
  if command -v gdate >/dev/null 2>&1; then
    DATE_CMD=gdate
  else
    echo "Error: GNU date (gdate) is required on macOS. Install MacPorts coreutils or run: brew install coreutils" >&2
    exit 1
  fi
fi

collect_targets() {
  find . \( -path './.git' -o -path './.git/*' \) -prune -o \
    -mindepth 2 -maxdepth 2 -type d -print | sort | while read -r dir; do
    local type="${dir#./}"
    local version="${dir##*/}"
    type="${type%/*}"

    [[ -f "${dir}/.env" && -f "${dir}/Dockerfile" ]] || continue
    [[ -n "$TARGET_TYPE" && "$type" != "$TARGET_TYPE" ]] && continue
    [[ -n "$TARGET_VERSION" && "$version" != "$TARGET_VERSION" ]] && continue
    printf '%s %s\n' "$type" "$version"
  done
}

resolve_manifest_digest() {
  local ref=$1
  local manifest
  local digest

  manifest=$(podman manifest inspect "$ref" 2>/dev/null) || return 1
  digest=$(jq -r '.Descriptor.digest // .digest // empty' <<<"$manifest")
  [[ -n "$digest" ]] || return 1
  printf '%s\n' "$digest"
}

was_recent() {
  local image=$1
  local created
  local created_seconds
  local now_seconds

  created=$(podman image inspect --format '{{.Created}}' "$image" 2>/dev/null) || return 1
  created_seconds=$($DATE_CMD --date="$created" +%s)
  now_seconds=$($DATE_CMD +%s)
  (( now_seconds - created_seconds < 86400 ))
}

append_common_build_args() {
  local array_name=$1
  local -a common_args=(
    --build-arg "PHP_VERSION=$PHP_VERSION"
    --build-arg "ALPINE_VERSION=$ALPINE_VERSION"
    --build-arg "ALPINE_IMAGE=alpine:$ALPINE_VERSION"
    --build-arg "RUNTIME_BASE_IMAGE=$RUNTIME_BASE_IMAGE"
    --build-arg "RUNTIME_BASE_DIGEST=$RUNTIME_BASE_DIGEST"
    --build-arg "ALMA_COMMIT=$ALMA_COMMIT"
    --file "$DIR/Dockerfile"
    "$TYPE/"
  )

  if [[ -n "${PHP_VERSION_MAJOR:-}" ]]; then
    common_args+=(--build-arg "PHP_VERSION_MAJOR=$PHP_VERSION_MAJOR")
  fi

  eval "$array_name"'+=("${common_args[@]}")'
}

archive_name() {
  local ref=$1
  ref=${ref//\//_}
  printf '%s\n' "${ref//:/_}.oci.tar"
}

export_local_archive() {
  local tag=$1
  local path="${PROOF_DIR}/$(archive_name "$tag")"
  mkdir -p "$PROOF_DIR"
  echo "Exporting OCI archive: $path" >&2
  podman save --format oci-archive --output "$path" "$tag"
}

export_manifest_archive() {
  local tag=$1
  local path="${PROOF_DIR}/$(archive_name "$tag")"
  mkdir -p "$PROOF_DIR"
  echo "Exporting multi-platform OCI archive: $path" >&2
  podman manifest push --all "$tag" "oci-archive:$path"
}

replace_manifest_alias() {
  local source=$1
  local alias=$2
  podman manifest rm "$alias" >/dev/null 2>&1 || true
  podman manifest create --all "$alias" "$source" >/dev/null
}

TARGETS=()
while IFS= read -r line; do
  TARGETS+=("$line")
done < <(collect_targets)

if (( ${#TARGETS[@]} == 0 )); then
  echo "Error: no matching directories with both .env and Dockerfile" >&2
  exit 1
fi

for target in "${TARGETS[@]}"; do
  read -r TYPE VERSION <<<"$target"
  DIR="$TYPE/$VERSION"

  unset IMAGE_REPO LOCAL_IMAGE_REPO IMAGE_TAG IMAGE_TAG_SUFFIX
  unset IMAGE_COMPAT_REPO LOCAL_IMAGE_COMPAT_REPO IMAGE_COMPAT_TAG LOCAL_IMAGE_COMPAT_TAG
  unset PHP_VERSION PHP_VERSION_MAJOR ALPINE_VERSION PLATFORM
  set -a
  # shellcheck disable=SC1090
  source "$DIR/.env"
  set +a

  if [[ "$MODE" == "local" ]]; then
    TAG_REPO="${LOCAL_IMAGE_REPO:-mode-dev/php}"
    TAG_REF="${IMAGE_TAG:-${PHP_VERSION}-${TYPE}${IMAGE_TAG_SUFFIX:-}}"
  else
    TAG_REPO="${IMAGE_REPO:-mxmd/php}"
    TAG_REF="${IMAGE_TAG:-${VERSION}-${TYPE}${IMAGE_TAG_SUFFIX:-}}"
  fi
  TAG="${TAG_REPO}:${TAG_REF}"
  TAGS=("$TAG")

  if [[ "$MODE" == "local" ]]; then
    if [[ -n "${LOCAL_IMAGE_COMPAT_REPO:-}" && -n "${LOCAL_IMAGE_COMPAT_TAG:-}" ]]; then
      TAGS+=("${LOCAL_IMAGE_COMPAT_REPO}:${LOCAL_IMAGE_COMPAT_TAG}")
    fi
  elif [[ -n "${IMAGE_COMPAT_REPO:-}" && -n "${IMAGE_COMPAT_TAG:-}" ]]; then
    TAGS+=("${IMAGE_COMPAT_REPO}:${IMAGE_COMPAT_TAG}")
  fi

  RUNTIME_BASE_IMAGE=""
  RUNTIME_BASE_DIGEST=""
  ALMA_COMMIT=""

  if [[ -f .github/alma-patches.json && -n "${PHP_VERSION_MAJOR:-}" ]]; then
    ALMA_COMMIT=$(jq -r --arg v "$PHP_VERSION_MAJOR" '.[$v].commit // ""' .github/alma-patches.json)
  fi

  if [[ "$TYPE" == "fpm-hardened" ]]; then
    RUNTIME_BASE_IMAGE="dhi.io/php:${PHP_VERSION_MAJOR}-alpine${ALPINE_VERSION}-fpm"
    if ! RUNTIME_BASE_DIGEST=$(resolve_manifest_digest "$RUNTIME_BASE_IMAGE"); then
      echo "Warning: could not resolve digest for $RUNTIME_BASE_IMAGE; continuing without it" >&2
      RUNTIME_BASE_DIGEST=""
    fi
  fi

  if [[ "$MODE" == "local" ]]; then
    if [[ "$PLATFORMS" == *,* ]]; then
      echo "Error: podman-local.sh accepts one platform; use podman-multiarch.sh for: $PLATFORMS" >&2
      exit 1
    fi

    if ! $FORCE_BUILD && was_recent "$TAG"; then
      echo "Skipping $TAG (built <24h ago)" >&2
      continue
    fi

    echo "Building ${TAGS[*]} for $PLATFORMS" >&2
    BUILD_CMD=(podman build --platform "$PLATFORMS")
    $FORCE_BUILD && BUILD_CMD+=(--no-cache)
    for tag in "${TAGS[@]}"; do
      BUILD_CMD+=(--tag "$tag")
    done
    append_common_build_args BUILD_CMD
    "${BUILD_CMD[@]}"

    if [[ -n "$PROOF_DIR" ]]; then
      export_local_archive "$TAG"
    fi
    continue
  fi

  if ! $FORCE_BUILD && podman manifest exists "$TAG"; then
    echo "Skipping $TAG (local manifest already exists; use --force to rebuild)" >&2
    continue
  fi

  podman manifest rm "$TAG" >/dev/null 2>&1 || true
  echo "Building manifest $TAG for $PLATFORMS" >&2
  BUILD_CMD=(podman build --platform "$PLATFORMS" --manifest "$TAG")
  $FORCE_BUILD && BUILD_CMD+=(--no-cache)
  append_common_build_args BUILD_CMD
  "${BUILD_CMD[@]}"

  for (( i=1; i<${#TAGS[@]}; i++ )); do
    replace_manifest_alias "$TAG" "${TAGS[$i]}"
  done

  if [[ -n "$PROOF_DIR" ]]; then
    export_manifest_archive "$TAG"
  fi
done
