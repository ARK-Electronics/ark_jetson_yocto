# ARK Jetson Yocto

Headless Yocto Linux for the ARK Electronics Just a Jetson carrier with an
Orin NX 16GB (P3767-0000). Board bring-up and hardware qualification are in
progress; no Yocto boot-time or performance result is claimed yet.

The layer set is pinned to Yocto 6.0 Wrynose and OE4T meta-tegra for NVIDIA
L4T R39.2.1 / JetPack 7.2.1, CUDA 13.2 and Linux 6.8.12. Pins correspond to
OE4T tegra-demo-distro `b65accc6faf5cf603278c9d59dec4e8803fb6e8c`.
This project uses its own small systemd distribution, without a desktop.

## Build

Use an x86-64 Linux host with Docker, at least 250 GB free SSD space, and
preferably 32 GB RAM. The initial build uses four workers for a 16 GB host.
Source downloads and sstate are retained in ignored local directories.
BitBake runs as your UID inside the container. The wrapper grants SYS_ADMIN
inside that container for task network namespaces on Ubuntu hosts; it does
not change host AppArmor/sysctl settings. Only this repository is mounted.
Use this builder only with source and recipes you trust.

Create an ignored `local.yml` with your own SSH **public** key:

```yaml
header:
  version: 17
local_conf_header:
  access: |
    ARK_SSH_PUBLIC_KEY = "ssh-ed25519 AAAA... your-key"
```

Then run `./scripts/build.sh`. To include the pinned Bonsai runtime, run
`./scripts/build.sh build kas/jaj.yml:kas/bonsai.yml:local.yml`. Root password login is disabled. SSH uses the
provided key over Ethernet DHCP or the USB gadget at 192.168.55.1. Never
commit private keys, local.yml, device backups or build output.

The image includes CUDA runtime, power/clock utilities, SSH, Python and
benchmark tools. It does not include ARK-OS or model weights. Super mode
support comes from the Orin NX Super BSP configuration; actual clock and
power verification is part of hardware qualification.

## Flashing and tests

Use the [flashing and recovery guide](docs/flashing.md) to validate and flash
the `.tegraflash-tar.zst` artifact. The wrapper defaults to replacing the whole
NVMe while preserving compatible QSPI firmware. Preserve a verified backup
first. No automatic flashing occurs during a build.

[Validation results](docs/validation.md) distinguish host checks, the measured
Ubuntu comparison baseline, and pending Yocto hardware qualification.

Startup measurements must report cold power to UART login, network/SSH,
and CUDA computation readiness separately. A minimal Linux readiness marker
is not equivalent to the full ARK-OS application being ready.

## Licenses

ARK-authored metadata and tools are MIT licensed. Copied board sources
retain their original notices. NVIDIA binaries and fetched upstream sources
retain their own licenses; this source repository does not redistribute
proprietary firmware, CUDA packages, model weights or device backups.
