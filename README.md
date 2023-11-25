# cross platform alpine-based php 7.1 - 8.2 images

## Container Runtimes

### Using Docker PHP Images from Docker Hub

This repository builds and publishes PHP images optimized for both CLI and FPM use cases, tailored for various PHP versions and their minor releases. Our images are compatible with both ARM64 and x86_64 host architectures and integrate seamlessly with Laravel and other PHP frameworks.

#### Pulling our PHP Docker Images

To get a specific version of our PHP image, use:

```bash
docker pull mxmd/php:<VERSION>-<TYPE>
```

Where:
- `<VERSION>` is the desired PHP version along with its minor version (e.g., `7.1.33`, `8.0.30`).
- `<TYPE>` is either `cli` or `fpm`.

For example, to pull the PHP 7.4.33 FPM image:

```bash
docker pull mxmd/php:7.4.33-fpm
```

Available versions of our images along with their Docker Hub links:

- [7.1.33-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.1.33-cli), [7.1.33-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.1.33-fpm)
- [7.2.34-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.2.34-cli), [7.2.34-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.2.34-fpm)
- [7.3.33-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.3.33-cli), [7.3.33-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.3.33-fpm)
- [7.4.33-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.4.33-cli), [7.4.33-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:7.4.33-fpm)
- [8.0.30-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.0.30-cli), [8.0.30-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.0.30-fpm)
- [8.1.26-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.1.26-cli), [8.1.26-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.1.26-fpm)
- [8.2.13-cli](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.2.13-cli), [8.2.13-fpm](https://hub.docker.com/r/mxmd/php/tags?page=1&name=php:8.2.13-fpm)

#### Usage with Docker Compose

You can integrate our PHP images into your Docker Compose workflows:

```yaml
services:
  php74-fpm:
    platform: linux/arm64/v8
    image: mxmd/php:7.4.33-fpm
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
      # additional php config
      - ./docker-conf/php-ini:/usr/local/etc/php/custom.d
    env_file:
      - .env
    environment:
      # tell PHP to scan for our mounted custom ini files - preferabbly mount with zz-custom.ini
      - PHP_INI_SCAN_DIR=/usr/local/etc/php/conf.d/:/usr/local/etc/php/custom.d
      # composer
      - COMPOSER_AUTH=${COMPOSER_AUTH}
      # these are CRITICAL for linux hosts - our entrypoint will skip these for macOS if they conflict with GID:20 on the container
      - HOST_USER_UID=${HOST_USER_UID:-1000}
      - HOST_USER_GID=${HOST_USER_GID:-1000}
      # production flag will enable opcache and production php.ini settings
      - HOST_ENV=${HOST_ENV:-production}
      # our entrypoint uses the www-data user for cmd entry that's not php-fpm - swap to EXEC_AS_ROOT=1 if you wanna exec as the root user
      - EXEC_AS_ROOT=0
    ...
  php74-cli:
    image: mxmd/php:7.4.33-cli
    ...
```

**Note**: Adjust volume paths or environment variables as per your project's requirements.

### Required Environment Variables

Ensure these environment variables exist on your host machine:

```bash
HOST_USER_GID
HOST_USER_UID
```

#### Setting these Environment Variables

On `macOS`, you can set them in `~/.extra` or `~/.bash_profile`.

To get `HOST_USER_UID`:

```bash
id -u
```

To get `HOST_USER_GID`:

```bash
id -g
```

To set these on your host machine:

```bash
echo "export HOST_USER_GID=$(id -g)" >> ~/.bash_profile && echo "export HOST_USER_UID=$(id -u)" >> ~/.bash_profile && echo "export DOCKER_USER=$(id -u):$(id -g)" >> ~/.bash_profile
```

### Optional Environment Variables

Enabling the following environment variable activates the opcache and uses `php.ini` production settings:

```ini
HOST_ENV=production
```
---

## Building Images:

### Flags:

Both local scripts support the following flags:

- `--force`: Forces the building of the Docker image regardless of its creation date.

- `--all`: Commands the script to construct Docker images for all predefined types and versions.

### 1. Local Traditional Build (`local-single-arch.sh`):

This script leverages Docker's standard build process, constructing images specifically for the architecture of the host machine.

#### How to Use:

To build a Docker image for a specific type and version:
```bash
./local-single-arch.sh --type [TYPE] --version [VERSION]
```

For building all available types and versions:
```bash
./local-single-arch.sh --all
```

### 2. Local Docker Buildx Multi-Architecture Build (`buildx-local.sh`):

Buildx is a Docker CLI plugin that offers extended features for building images. It is especially valuable for creating multi-architecture images.

#### How to Use:

For a specific type and version:
```bash
./buildx-local.sh --type [TYPE] --version [VERSION]
```

For all available types and versions:
```bash
./buildx-local.sh --all
```


## 3. GitHub Actions

### Workflow Description:

**Trigger**:
- Activates on `push` events to the `master` branch.

**Jobs**:

1. **create-release-and-build**:
   - **Environment**: Runs on the latest Ubuntu.
   - **Matrix Strategy**: Sets combinations of PHP versions from '7.1' to '8.2' for both 'cli' and 'fpm' images.

   **Steps**:
   - **Checkout repository**: Pulls the latest code from the repository.
   - **Setup GitHub CLI**: Initializes the GitHub CLI and logs in using the provided GitHub token.
   - **Create Releases**: If a `.env` file exists in the specified directory and a GitHub release for the given tag doesn't already exist, it creates a new release for the specific PHP version and type.
   - **Set up environment variables**: Sources the `.env` file from the specified directory and sets PHP_VERSION and ALPINE_VERSION as environment variables.
   - **Set up QEMU**: A tool to run code made for one machine on another, useful for multi-architecture builds.
   - **Set up Docker Buildx**: Initializes Buildx, an extended builder with additional features.
   - **Log in to Docker Hub**: Uses the provided secrets to log into Docker Hub.
   - **Build Docker images**: Constructs Docker images for both amd64 and arm64 platforms without pushing them.
   - **Push Docker images (if new tag)**: If a new release tag was created in the "Create Releases" step, this step pushes the built images to Docker Hub.

### Key Features:

- **Matrix Builds**: The workflow is designed to run builds for multiple PHP versions and types concurrently, maximizing efficiency.

- **Conditional Releases**: Only creates a new GitHub release if one for the specific PHP version and type doesn't already exist. This ensures that Docker images are only pushed when necessary.

- **Multi-Architecture**: Utilizes Docker's Buildx and QEMU to build images suitable for both amd64 and arm64 architectures.

### Required Secrets:

The workflow requires the following secrets:

- `GITHUB_TOKEN`: A token provided by GitHub to authenticate and gain required permissions. This is automatically available in GitHub Actions and does not need manual setup.

- `DOCKER_HUB_USERNAME`: Your Docker Hub username.

- `DOCKER_HUB_ACCESS_TOKEN`: A token or password for Docker Hub to authenticate and push images.


