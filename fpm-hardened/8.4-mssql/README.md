# Hardened PHP 8.4 FPM Alpine with MSSQL

Security-hardened PHP-FPM image with Microsoft SQL Server support that runs as non-root by default.

## Security Features

- Runs as www-data (not root)
- No EXEC_AS_ROOT option
- Minimal packages (no vim, git, wget, mysql-client, rsync)
- Use init container pattern for volume permissions

## MSSQL Extensions

- `sqlsrv` - Microsoft SQL Server driver
- `pdo_sqlsrv` - PDO driver for SQL Server

## Usage

See `docker-compose.yml` for the init container pattern example.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_ENV` | development | Set to `production` for opcache |
| `PHP_ENABLE_SOAP` | false | Enable SOAP extension |
| `DISABLE_HEALTHCHECK` | false | Disable healthcheck |
| `ACCEPT_EULA` | Y | Accept Microsoft EULA (required for MSSQL) |
