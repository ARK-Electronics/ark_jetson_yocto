#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(id -u) == 0 ]]; then
    echo "Run this wrapper as your normal non-root build user." >&2
    exit 1
fi
image=${ARK_BUILDER_IMAGE:-ark-jetson-yocto-builder:wrynose-$(id -u)-$(id -g)}
want_sha=$(sha256sum "$repo/docker/Dockerfile" | cut -d' ' -f1)
have_sha=$(docker image inspect --format '{{ index .Config.Labels "ark.dockerfile_sha" }}' "$image" 2>/dev/null) || have_sha=""
if [[ "$want_sha" != "$have_sha" ]]; then
    docker build --build-arg BUILD_UID="$(id -u)" --build-arg BUILD_GID="$(id -g)" \
        --label "ark.dockerfile_sha=$want_sha" -t "$image" "$repo/docker"
fi
if (($# == 0)); then
    set -- build kas/jaj.yml:local.yml
fi
# Ubuntu's user-namespace restrictions require CAP_SYS_ADMIN even for a
# non-root builder. Grant it only inside this container; keep the host policy.
exec docker run --rm --init --user 0:0 --cap-add SYS_ADMIN \
    --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    -v "$repo:/work" -w /work --entrypoint setpriv "$image" \
    --reuid="$(id -u)" --regid="$(id -g)" --init-groups \
    --inh-caps=+sys_admin --ambient-caps=+sys_admin kas "$@"
