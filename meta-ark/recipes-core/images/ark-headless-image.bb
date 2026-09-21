SUMMARY = "ARK Just a Jetson headless CUDA development and benchmark image"
LICENSE = "MIT"
inherit core-image
IMAGE_FEATURES += "ssh-server-openssh"
IMAGE_INSTALL:append = " \
    ark-network ark-access ark-bench ark-grow-rootfs \
    systemd-networkd systemd-analyze \
    l4t-usb-device-mode tegra-nvpmodel tegra-tools-jetson-clocks tegra-tools-tegrastats \
    tegra-libraries-cuda cuda-cudart libcublas \
    bash coreutils util-linux iproute2 iputils ethtool pciutils usbutils \
    python3 python3-json python3-multiprocessing \
    openssl-bin curl ca-certificates tar zstd rsync fio \
"
# No debug-tweaks, default passwords, or automatic login. Supply a public key
# using local.yml, as documented in README.md.
IMAGE_FSTYPES:append = " tar.zst"
