#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: bash $0 IMAGE" >&2
    exit 2
fi

image_ref="$1"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Use an anonymous volume and docker cp so this also works with remote daemons.
container_id=$(docker create \
    --read-only \
    --network none \
    --tmpfs /tmp \
    --tmpfs /run \
    --volume /app \
    "$image_ref")

cleanup() {
    docker rm --force --volumes "$container_id" >/dev/null
}
trap cleanup EXIT

docker cp "$script_dir/check.php" "$container_id:/app/test-performance.php"
docker start "$container_id" >/dev/null

ready=0
for attempt in {1..20}; do
    if docker exec "$container_id" /usr/local/bin/fcgi-health >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.5
done
if [[ "$ready" -ne 1 ]]; then
    docker logs "$container_id" >&2
    echo "PHP-FPM did not become ready for $image_ref" >&2
    exit 1
fi

for attempt in {1..3}; do
    if ! docker exec --env FCGI_STATUS_PATH=/app/test-performance.php \
        "$container_id" /usr/local/bin/fcgi-health; then
        docker logs "$container_id" >&2
        echo "PHP-FPM performance check failed for $image_ref" >&2
        exit 1
    fi
done

echo "PHP-FPM performance defaults verified for $image_ref (3 requests)."
