# cross platform alpine-based php 7.1 - 8.2 images

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


---

## Container Runtimes

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
