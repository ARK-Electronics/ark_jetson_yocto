# r8168 PHY handoff diagnostic

This experiment observes why an Ethernet link established before Linux drops
when Linux initializes the Realtek controller. It does not implement a
continuous-link fix and is excluded from every image recipe. The customer
requires link within six seconds of power, including POR, and uninterrupted
link afterward; the current image fails because of its later link drop.
See the [measured link investigation](../../docs/early-ethernet.md) for
carrier transitions and diagnostic results.

The two patches add `r8168.ark_phy_diag`, a read-only boolean module parameter
that defaults to **off**. With it enabled, `ARK_R8168_PHY` kernel messages report
selected PHY registers, transport-completion bits, cached MCU state and live
MCU version observations. The incremental patch restricts its live MCU reads
to the audited `CFG_METHOD_30` controller with OCP support and no vendor
diagnostic session. Both patches preserve normal initialization decisions.

These observations are intrusive: indirect reads write address selectors,
BMSR reads clear latched link history, and polling/printing changes timing.
The MCU getter restores the cached page; it does not change the cached
firmware-loaded flags. A completed OCP transaction is not proof of PHY RAM
integrity. The earliest sample is after UEFI and PCIe handoff, not a measurement
of PHY state immediately after power. Do not use this diagnostic boot as an
unmodified performance result.

## Reproduce only the module

Start in this repository's root with its completed optimized Yocto build and
existing builder image available. No download, BitBake task, kernel build or
image build is performed. The helper needs host Python 3, `patch` and Docker.

The required source is NVIDIA OOT **39.2.1**, Realtek **8.053.00-NAPI**; the
kernel must be exactly **6.8.12-l4t-r39.2.1-1021.21**, built with the cached
Yocto GCC **15.3.0** toolchain. `inputs.json` pins the driver sources, generated
NVIDIA compatibility headers, kernel configuration and `Module.symvers`.
These cached files are not interchangeable with generic Linux headers or a
similarly named Ubuntu kernel. The current configuration has
`CONFIG_MODVERSIONS=y` and no module-signature enforcement.

```sh
python3 experiments/r8168-phy-diagnostic/test_build.py
python3 experiments/r8168-phy-diagnostic/build.py --check
python3 experiments/r8168-phy-diagnostic/build.py
```

The default output is `private/r8168-diagnostic-build/`. An existing directory
is always refused; use `--output-name r8168-repeat-2` for a new attempt. The
helper copies the driver, applies both patches with zero fuzz and verifies
the resulting source hash. It reads only the generated recipe's `PATH` and
compiler assignments with `shlex`; it never sources or evaluates that shell
script. Compiler arguments containing shell syntax are refused.

Docker mounts the completed repository read-only and only the new output
directory writable, with networking disabled. It uses the existing
`ark-jetson-yocto-builder:wrynose-<uid>-<gid>` image, or an explicit existing
`ARK_BUILDER_IMAGE`; the resolved image ID is recorded. The actual Kbuild call
is `make -C <prepared-kernel-output> M=<private-driver-copy> modules`, using
the cached compiler flags and NVIDIA conftest includes. This compiles four
r8168 objects and its module metadata, without rebuilding other drivers.

The output contains `module/r8168.ko`, patch/build logs and `manifest.json`
with exact argv, input hashes, builder ID, source hash and module hash. Output
manifests are private and may contain local paths. Changing the output path
can change debug information and thus the unstripped module hash. A successful
build does not establish correct hardware behavior.

## Controlled deployment and interpretation

The helper never deploys, unloads, enables or reboots anything. Before a
separate controlled target test, verify `uname -r`, the full module vermagic
and imported symbol CRCs against the running kernel. Preserve the original
module, its hash and loading configuration. This build's native module
version format uses variable-length entries; an older host `modprobe
--show-modversions` can reject them even though the target format is valid.

Use UART or independent USB management for the experiment. Replacing or
reloading an Ethernet driver itself can interrupt link, so compare controlled
cold boots, including the host carrier transitions, and explicitly enable
`ark_phy_diag=1` only for diagnostic captures. Restore the original module
and configuration afterward. Retain raw diagnostic logs privately; publish
only relevant register fields and relative timing, without device identities.

Pinned hashes:

| Artifact | SHA256 |
| --- | --- |
| Original `r8168_n.c` | `d94dfc2256cc3832fd6f88df03c755bd61811910affef9ee33e30df3c036dc61` |
| First patch | `ad5349075fc178598c27c512dd2f2c0d29dac16350e24d65f442a0932473fa92` |
| Incremental patch | `8cee52fc89bfc02ad2d5bd17a58cf8a7398b32699d567207ecc1e5392a29a244` |
| Patched `r8168_n.c` | `d2620f52319bd36098fa2f36b0f5fc779989a72f852f0d1531b086ddfedf40a2` |

The helper and documentation are MIT licensed. The patches modify the
GPL-licensed Realtek/NVIDIA driver and retain that driver's licensing; no
vendor source tree or compiled module is distributed here.
