# Hardened PHP 7.3 FPM Alpine

Security-hardened PHP-FPM image that runs as non-root by default.

## Security Features

- Runs as www-data (not root)
- No EXEC_AS_ROOT option
- Minimal packages (no vim, git, wget, mysql-client, rsync)
- Use init container pattern for volume permissions

## Usage

See `docker-compose.yml` for the init container pattern example.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_ENV` | development | Set to `production` for opcache |
| `PHP_ENABLE_SOAP` | false | Enable SOAP extension |
| `DISABLE_HEALTHCHECK` | false | Disable healthcheck |
