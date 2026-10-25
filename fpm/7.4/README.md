# cross platform alpine-based php* images



### required ENV

 make sure these ENV varaiables exist on your host-machine

```
HOST_USER_GID
HOST_USER_UID
```
#### set these env vars

ie on `macOS` in `~/.extra` or `~/.bash_profile`

get `HOST_USER_UID`

```
id -u
```


get `HOST_USER_GID`
```
id -g
```


### run
```
echo "export HOST_USER_GID=$(id -g)" >> ~/.bash_profile && echo "export HOST_USER_UID=$(id -u)" >> ~/.bash_profile && echo "export DOCKER_USER=$(id -u):$(id -g)" >> ~/.bash_profile
```


### optional ENV

this will enable opcache and php.ini production settings

```ini
HOST_ENV=production
```


EXIF is compiled into the PHP 7.4 image as a shared extension and is disabled by
default. Like SOAP, the entrypoint toggles its INI file based on an environment
variable. Set `PHP_ENABLE_EXIF=true` or `PHP_ENABLE_EXIF=1` to enable it; other
values disable it. Configure this on both CLI and FPM services when the application
requires `ext-exif`:

```yaml
environment:
  PHP_ENABLE_EXIF: "true"
```

Recreate existing containers after changing the environment variable.

docker-compose.yml
```yaml
  php74:
    image: mxmb/php:7.4-fpm
    # optional: disable if you're running behind a proxy like traefik
    ports:
      - "9000:9000"
    volumes:
      # real time sync for app php files
      - .:/app
      # cache laravel libraries dir
      - ./vendor:/app/vendor:cached
      # logs and sessions should be authorative inside docker
      - ./storage:/app/storage:delegated
      # cache static assets bc fpm doesn't need to update css or js
      - ./public:/app/public:cached
      # additional php config REQUIRED
      - ./docker-conf/php-ini:/usr/local/etc/php/custom.d
    env_file:
      - .env
    environment:
      # note that apline has dif dir structures: /user/local/etc - conf.d need to be scanned here for all modules from image
      - PHP_INI_SCAN_DIR=/usr/local/etc/php/conf.d/:/usr/local/etc/php/custom.d
      # composer settings
      - COMPOSER_AUTH=${COMPOSER_AUTH}
      - COMPOSER_ALLOW_SUPERUSER=1
      # these are CRITICAL
      - HOST_USER_UID=${HOST_USER_UID:-1000}
      - HOST_USER_GID=${HOST_USER_GID:-1000}
      # enables opache in prod
      - HOST_ENV=${HOST_ENV:-production}
      # this should only be used in troubleshooting
      - EXEC_AS_ROOT=0      
```
