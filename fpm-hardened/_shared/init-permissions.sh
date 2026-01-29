#!/bin/sh
# Init container script for setting up volume permissions
# Run as root before starting the main PHP-FPM container
#
# Usage: init-permissions.sh /path/to/dir1 /path/to/dir2 ...
#
# Environment:
#   HOST_USER_UID - UID to chown to (default: 82 = www-data in Alpine)
#   HOST_USER_GID - GID to chown to (default: 82 = www-data in Alpine)

set -e

# Use HOST_USER_UID/GID if set, otherwise default to www-data (82)
TARGET_UID="${HOST_USER_UID:-82}"
TARGET_GID="${HOST_USER_GID:-82}"

if [ $# -eq 0 ]; then
    echo "Usage: init-permissions.sh /path/to/dir1 [/path/to/dir2 ...]"
    echo "No paths provided, nothing to do."
    exit 0
fi

echo "Setting permissions for UID:$TARGET_UID GID:$TARGET_GID"

for path in "$@"; do
    if [ -e "$path" ]; then
        echo "chown $TARGET_UID:$TARGET_GID $path"
        chown -R "$TARGET_UID:$TARGET_GID" "$path"
        find "$path" -type d -exec chmod 755 {} \;
        find "$path" -type f -exec chmod 644 {} \;
    else
        echo "Creating $path"
        mkdir -p "$path"
        chown -R "$TARGET_UID:$TARGET_GID" "$path"
        chmod 755 "$path"
    fi
done

echo "Done"
