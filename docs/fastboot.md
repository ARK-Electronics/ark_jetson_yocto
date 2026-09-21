# Optional kernel boot-time experiment

The normal `kas/jaj.yml` image uses the pinned NVIDIA kernel without the ARK
BPMP patch and keeps the upstream boot arguments. Establish its cold-boot,
network, CUDA, and peripheral baseline before enabling this separate variant:

```sh
scripts/build.sh build kas/jaj.yml:kas/fastboot.yml:local.yml
```

For the MAXN_SUPER Bonsai benchmark variant, combine the independent fragments:

```sh
scripts/build.sh build kas/jaj.yml:kas/bonsai.yml:kas/fastboot.yml:local.yml
```

`kas/fastboot.yml` adds the separate `meta-ark-fastboot` layer, sets
`ARK_BPMP_DEBUGFS_ASYNC = "1"`, includes the guarded kernel patch, and appends
these kernel arguments:

```text
quiet loglevel=3 jaj_fastboot.bpmp_debugfs_async=1 jaj_fastboot.bpmp_debugfs_delay_ms=0
```

The existing serial and display console arguments remain present. `quiet` and
`loglevel=3` reduce console output; kernel messages remain available in the
journal. Remove this fragment to restore the baseline kernel and command line,
then rebuild and deploy the matching kernel, modules, and initramfs together.
Changing boot arguments alone cannot add the patch to an unmodified kernel.
The base configuration never loads this extra layer, so its kernel recipe
metadata and task signatures remain untouched by this experiment.

The patch moves only BPMP diagnostic debugfs creation to a dedicated background
worker. Transport, clocks, resets, power domains, native GPU power policy,
thermal control, fan control, and root-device waits retain their existing
initialization. Full UEFI, TPM, OP-TEE, persistent variables, and the existing
security configuration remain selected. This fragment does not select minimal
UEFI, change power mode, override clocks, or disable PCIe controllers.

The delay is explicitly zero. A nonzero delay is a separate experiment because
it moves BPMP diagnostic traffic further into application startup. Tools needing
`/sys/kernel/debug/bpmp/debug`, including `jetson_clocks`, must wait for the
`debugfs initialized asynchronously` kernel message. Allocation failures and
BPMP devices associated with a NUMA node retain synchronous initialization.
The kernel has NUMA support enabled; verify the actual completion message on the
board before attributing any timing change to this option. No boot-time saving
is promised. Compare cold boots using the same readiness criteria and confirm
CUDA and attached peripherals work in both images.

## Yocto initramfs and the FFC PCIe port

OE4T's `tegra-minimal-initramfs` uses
`recipes-core/initrdscripts/tegra-minimal-init/init-boot.sh`. It already avoids a
runtime `depmod`, so the earlier Ubuntu initramfs dependency-index optimization
is unnecessary here. The script loads modules for sysfs modaliases before
switching to the root filesystem. The built kernel has both PCIe and NVMe as
modules.

C7 (`141e0000.pcie`) remains enabled at Gen2 for the FFC connector. The pinned
PCIe driver preserves its 100 ms reset wait and link-training retries; a port
without an endpoint can consume roughly two seconds across the vendor and
DesignWare host link checks, with additional conditional retries possible.
Because this can happen in the initramfs, the earlier Ubuntu systemd coldplug
replay optimization may not improve the Yocto path. Measure the actual trace
before porting it. Do not shorten link-training timeouts or disable C7 to improve
a headless CUDA result; FFC endpoint support remains part of the board support.

## Provenance and validation

The patch is copied unchanged after its metadata header from
`ark_jetson_kernel` commit `adf6376842a524531438362e7cf48826cb6e7dfe`, path
`products/JAJ/fastboot/r39.2.1/bpmp-debugfs-async.patch` (GPL-2.0-only kernel code).
Its original patch SHA-256 is
`81467e39780bc08f88ca68acfc5bbae7961e3de290988f5f7c913568db6577d5`.
The kernel provider is `linux-noble-nvidia-tegra_6.8`, pinned by meta-tegra to
`78272943bba3a47e633b28963b0cda60de503500`.

The append verifies all three audited sources before applying any recipe patches
and their complete expected contents afterward:

| Source | Original SHA-256 | Patched SHA-256 |
| --- | --- | --- |
| `drivers/firmware/tegra/bpmp.c` | `9a197e986731682e54e2474078f1f7cc4d7369438cd6579752d6d7db711610c9` | `cf849c8aaea7d0c709bbba80fd2f1fa5c30b20b1b87e9c9afa205f38c47617f9` |
| `drivers/firmware/tegra/bpmp-debugfs.c` | `081c627087704d1e200ea32bbed4c8cb84fa5d9d5a22ebc2a459fbb4b1d76a7e` | unchanged |
| `include/soc/tegra/bpmp.h` | `611a4975295bc14f53290ab84e7e19a7b52170c54a802eed72312cd090181ac8` | unchanged |

Source changes fail the build and require a new review. With the pinned kernel
unpacked locally, run:

```sh
python3 meta-ark-fastboot/recipes-kernel/linux/tests/test_bpmp_patch.py
```

Set `ARK_BPMP_KERNEL_SOURCE` if the unpacked kernel is outside the normal build
work directory. The tests apply the real patch with zero fuzz to temporary source
copies and execute the recipe's actual guards, including changed, missing, and
incorrectly patched source rejection. They never modify the active build tree.
