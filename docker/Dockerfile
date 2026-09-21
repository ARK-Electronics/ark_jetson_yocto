FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates chrpath cpio diffstat file gawk git \
    iputils-ping libacl1 locales lz4 python3 python3-pip python3-venv \
    python3-pexpect socat texinfo unzip wget xz-utils zstd rsync \
    bzip2 debianutils libegl1 libgmp-dev libmpc-dev libsdl1.2-dev \
    pylint && rm -rf /var/lib/apt/lists/*
RUN locale-gen en_US.UTF-8 && python3 -m venv /opt/kas && /opt/kas/bin/pip install --no-cache-dir kas==5.5
ARG BUILD_UID=1000
ARG BUILD_GID=1000
RUN if getent passwd ubuntu >/dev/null; then userdel -r ubuntu; fi; \
    (getent group ${BUILD_GID} || groupadd -g ${BUILD_GID} builder) && useradd -m -u ${BUILD_UID} -g ${BUILD_GID} -s /bin/bash builder
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 PATH=/opt/kas/bin:$PATH
USER builder
WORKDIR /work
ENTRYPOINT ["kas"]
