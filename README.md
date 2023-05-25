# cross platform alpine-based php 7.1, 7.4, 8.0, 8.1, 8.2 images

see

- https://github.com/madebymode/docker-alpine-php/tree/7.1
- https://github.com/madebymode/docker-alpine-php/tree/7.4
- https://github.com/madebymode/docker-alpine-php/tree/8.0
- https://github.com/madebymode/docker-alpine-php/tree/8.1
- https://github.com/madebymode/docker-alpine-php/tree/8.2

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


### host machine
```
echo "export HOST_USER_GID=$(id -g)" >> ~/.bash_profile && echo "export HOST_USER_UID=$(id -u)" >> ~/.bash_profile && echo "export DOCKER_USER=$(id -u):$(id -g)" >> ~/.bash_profile
```


### optional ENV

this will enable opcache and php.ini production settings

```ini
HOST_ENV=production
```
