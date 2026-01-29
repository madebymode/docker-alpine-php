# Hardened PHP 8.4 FPM Alpine

Security-hardened PHP-FPM image. Runs as non-root. No EXEC_AS_ROOT option.

## Security Features

- **Always non-root** - `USER www-data` in Dockerfile, no escape hatch
- **Production config baked in** - php.ini-production, opcache, expose_php=Off
- **No Composer** - Use CLI image for dependency installation
- **No dev tools** - No vim, git, wget, mysql-client, rsync
- **SOAP disabled** - Disabled by default

## Production Pattern

Init container sets permissions, FPM runs as non-root with matching UID:

```yaml
services:
  # Runs ONCE as root to fix volume permissions
  php-init:
    image: mxmd/php:8.4-fpm-hardened
    user: root
    environment:
      - HOST_USER_UID=${HOST_USER_UID:-1000}
      - HOST_USER_GID=${HOST_USER_GID:-1000}
    volumes:
      - /var/www/myapp/shared/storage:/app/storage
      - /var/www/myapp/shared/cache:/app/bootstrap/cache
    entrypoint: ["/usr/local/bin/init-permissions"]
    command: ["/app/storage", "/app/bootstrap/cache"]
    restart: "no"

  # Runs as non-root with UID matching host paths
  php-fpm:
    image: mxmd/php:8.4-fpm-hardened
    user: "${HOST_USER_UID:-1000}:${HOST_USER_GID:-1000}"
    depends_on:
      php-init:
        condition: service_completed_successfully
    volumes:
      - app_data:/app:ro
      - /var/www/myapp/shared/storage:/app/storage
      - /var/www/myapp/shared/cache:/app/bootstrap/cache
    restart: always
```

## Key Points

| What | How |
|------|-----|
| UID mapping | `user:` in docker-compose, not runtime usermod |
| Volume perms | Init container runs as root, chowns to HOST_USER_UID |
| FPM process | Always non-root, UID set by docker-compose |
| PHP config | Baked in at build time, no runtime changes |

## Differences from Standard Image

| Feature | Standard | Hardened |
|---------|----------|----------|
| EXEC_AS_ROOT | Available | **Removed** |
| Runtime usermod | Yes | **No** |
| PHP config | Runtime switchable | Baked in |
| Composer | Included | Removed |
| Dev tools | Included | Removed |
