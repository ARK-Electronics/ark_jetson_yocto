#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
image=${ARK_BUILDER_IMAGE:-ark-jetson-yocto-builder:wrynose}
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build --build-arg BUILD_UID="$(id -u)" --build-arg BUILD_GID="$(id -g)" \
        -t "$image" "$repo/docker"
fi
if (($# == 0)); then
    set -- build kas/jaj.yml:local.yml
fi
exec docker run --rm --init --user "$(id -u):$(id -g)" \
    --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    -v "$repo:/work" -w /work "$image" "$@"
