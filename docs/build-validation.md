# Build validation — 2026-09-21

The base and combined optional images built successfully for the JAJ with
Orin NX 16GB (`ark-jaj-orin-nx`, P3767-0000). Both use the repository's pinned
Yocto 6.0 Wrynose/OE4T metadata, L4T R39.2.1, Linux 6.8.12 and CUDA 13.2.
This report records build and artifact checks. Hardware results and readiness
criteria are tracked separately in [validation.md](validation.md).

## Configurations and completed tasks

| Build | Configuration or target | Successful tasks |
| --- | --- | ---: |
| Base headless image | `kas/jaj.yml:local.yml` | 5,425 |
| Prism package only | `bitbake prism-llama` | 1,483 |
| Optional fastboot kernel | `kas/jaj.yml:kas/fastboot.yml:local.yml`, `virtual/kernel` | 1,081 |
| Combined optional image | JAJ + Bonsai + fastboot + no-camera fragments | 5,463 |

These are BitBake task totals, including tasks reused from cache. The final
combined build reused 5,404 tasks and completed the remaining tasks successfully;
package QA and image QA remained enabled.

The base uses the unmodified pinned NVIDIA kernel and upstream boot arguments.
The measured base configuration selected `NVPMODEL_CONFIG_DEFAULT = "0"` through
local configuration. The Bonsai fragment selects the same MAXN_SUPER mode and
adds the pinned Prism runtime; it does not install weights or start a server.

Reproduce the selected image configurations with an independently configured
`local.yml` as described in the [build instructions](../README.md#build):

```sh
./scripts/build.sh build kas/jaj.yml:local.yml
./scripts/build.sh build kas/jaj.yml:kas/bonsai.yml:kas/fastboot.yml:kas/no-camera.yml:local.yml
```

The combined image was built with:

```text
quiet loglevel=3 jaj_fastboot.bpmp_debugfs_async=1 jaj_fastboot.bpmp_debugfs_delay_ms=0
```

The BPMP delay is **zero** in this artifact. A different delay is a separate
runtime experiment. The [fastboot fragment](fastboot.md) retains hardware
initialization and the selected firmware/security profile. The
[no-camera fragment](no-camera.md) disables only the camera I2C mux, preserving
GPU, NVMe and FFC PCIe configuration.

## Final combined artifact

Archive:
`ark-headless-image-ark-jaj-orin-nx.rootfs-20260921210431.tegraflash-tar.zst`

- Size: **834,780,769 bytes**.
- Archive SHA-256: `f8f5ea39eff55149b20ea30a96842f19a32c55c57dc3561ed6b1061e15021a48`.
- Rootfs `/boot/Image` SHA-256: `5272e484777ecc1c8303a159caa3670d6d0ab0e8bd53d2a1849dfd804de67b71`.

The base artifacts from timestamp `20260921195840` were retained separately
before deploy cleanup. Deploy symlinks identify the latest image and should not
be used as an immutable comparison reference.

## Corrections and checks

- The Prism recipe now uses Wrynose's default Git unpack directory and installs
  shared libraries without preserving host ownership. Its CUDA SM87 build,
  package ownership checks and package QA passed. The final image contains
  `llama-bench`, `llama-cli`, `llama-server` and `libgomp1`; no model-server startup
  unit is installed.
- The no-camera fragment now adds its overlay alongside NVIDIA's original
  `virtual/dtbo` provider. Replacing that provider initially removed required
  firmware overlays and caused flash-archive assembly to fail. The corrected
  archive contains `tegra234-carveouts.dtbo`, `tegra-optee.dtbo` and
  `tegra234-p3768-0000+p3767-0000-dynamic.dtbo`, each matching its recipe-sysroot
  content. The rootfs contains `/boot/ark_no_csi.dtbo` and the corresponding
  extlinux `OVERLAYS` entry.
- All **five no-camera tests** passed, including an actual BitBake-generated
  dependency graph, overlay application to clean and camera-enabled DTBs,
  idempotence, and the pinned upstream extlinux generation/install functions.
  All **eight BPMP guard/patch tests** passed. The real kernel build also passed
  exact source checks before and after patching; kernel modules and NVIDIA's
  out-of-tree modules compiled and passed packaging checks.
- The final rootfs contains the reviewed stable USB identity derivation and DHCP
  correction. Boot configuration, Prism binaries and USB files matched their
  audited hashes. These checks do not replace target networking tests.
- An earlier exploratory build changed distribution metadata while tasks were
  running, producing GCC basehash mismatches. The successful base and combined
  builds used frozen metadata; no signature or QA check was disabled.

## Hardware scope

Both tested images used external-only NVMe flashing and retained the custom minimal
R39.2.1 UEFI/QSPI from [ark_jetson_kernel PR 109](https://github.com/ARK-Electronics/ark_jetson_kernel/pull/109).
Consequently, those hardware results do **not** qualify the full UEFI firmware
built into this repository's flash bundle. Follow the
[flashing guide](flashing.md) for the distinction between retained-QSPI and full
flashing. No boot-time or inference-performance claim follows from these build
checks.

Deploy the kernel, matching kernel modules, NVIDIA out-of-tree modules and
initramfs from the same build together. A successful kernel-only build is not
sufficient evidence that an older rootfs's driver modules match it. Changing a
boot argument cannot add the BPMP patch to an unmodified kernel.
