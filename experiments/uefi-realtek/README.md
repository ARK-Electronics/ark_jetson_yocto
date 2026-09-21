# Realtek UEFI initialization experiment

**The tested profile failed the Ethernet requirement.** Enabling the existing
Realtek PCIe UNDI driver in the minimal R39.2.1 UEFI delayed the first observed
peer link to 9.896 seconds and still allowed a later link drop. This directory
preserves the experiment for reproducibility; no production recipe enables it.

The hypothesis was that the vendor UEFI driver could initialize the RTL8111H
early enough to establish continuous Ethernet link within six seconds of power,
including POR. The candidate changed exactly two resolved settings:
`NETWORKING=n → y` and `NETWORKING_DEVICE_REALTEK=n → y`. TPM, Secure Boot,
OP-TEE persistent variables, firmware management/ESRT, the existing single
L4TLauncher fix, PCIe/NVMe and Linux's C7 configuration remained unchanged.
PXE, HTTP, iSCSI, VLAN, IPv4/IPv6 and other NIC drivers stayed disabled.

One diagnostic cold boot produced these host peer observations, measured from
the power-on command:

| Event | Seconds |
| --- | ---: |
| First peer link up | 9.895969884 |
| Peer link down | 18.084329781 |
| Peer link recovered | 20.908683230 |
| Observed down interval | 2.824353449 |

Linux boot and the CUDA smoke test passed. The diagnostic's live MCU reads
before probe initialization and before PHY reset both reported `0x0000`, with
completed read transactions, versus native expected version `0x0083`. Native
initialization subsequently reported programming `0x0083`. The required MCU
version was therefore still absent from those sampled handoff observations.
This rejects this profile as a solution; it does not prove that the vendor
driver never bound, or that every possible firmware implementation must fail.

The [Linux diagnostic](../r8168-phy-diagnostic/) adds reads and logging while
preserving normal initialization decisions. A completed transaction does not
prove RAM integrity or full calibration state. This single diagnostic boot is
not an unmodified timing distribution. The original firmware and module are the
rollback baseline. See the [link investigation](../../docs/early-ethernet.md)
for the separate baseline measurements and protocol limitations.

## Recorded inputs and firmware contents

`jaj_nvme.defconfig` is the exact tested profile; `resolved.config` is the actual
generated configuration. `uefi-sources.lock` pins all eight source checkouts.
`provenance.json` records the pinned build-wrapper inputs, compiler, measured
container ID, config delta, firmware hash, complete module inventory and the
sanitized diagnostic result. `python-packages-measured.txt` records the measured
build environment. No firmware binary, device identifier or raw log is included.

The RELEASE firmware was **1,966,080 bytes**, below the **3,670,016-byte** native
UEFI partition capacity. Its SHA256 was
`fecf325287ae7c13e56b83695bb2b8265e80161e58e18b6d12bf687f47b1fdca`.
The firmware volume contained 125 modules versus 118 in the retained profile,
with exactly these additions and no removals: `ArpDxe`, `DnsDxe`, `DpcDxe`,
`MnpDxe`, `RtkUndiDxe`, `SnpDxe`, `TcpDxe`. TCP/DNS are included by the upstream
core-networking selection even with the IP-stack options disabled.

The Realtek AArch64 PCIe UNDI binary is version **2.075**, from pinned
[edk2-non-osi](https://github.com/NVIDIA/edk2-non-osi/tree/c07d24e45c87d175ad1dc5d74b2c7feed9356503/Drivers/Realtek/Bus/Pcie/PcieNetworking).
Its firmware-volume PE32 payload was verified byte-for-byte against that source
binary. The vendor implementation is not supplied as source, so its presence
does not establish native H2 firmware/calibration equivalence. Generic SNP
binding initializes then shuts down/stops UNDI; ARP/MNP can initialize it again,
and the default ExitBootServices path shuts it down again. These call paths can
disturb link or add delay; this test does not isolate their individual effects.

## Reproduce the build only

Use Linux with Git, Python 3, `flock` and Docker. Obtain the public kernel
repository at the exact reference commit:

```sh
git clone https://github.com/ARK-Electronics/ark_jetson_kernel.git
git -C ark_jetson_kernel checkout --detach adf6376842a524531438362e7cf48826cb6e7dfe
```

From this Yocto repository's root, replacing the checkout argument as needed:

```sh
python3 experiments/uefi-realtek/test_build.py
python3 experiments/uefi-realtek/build.py --kernel-source ./ark_jetson_kernel --check
python3 experiments/uefi-realtek/build.py --kernel-source ./ark_jetson_kernel
```

The helper reads pinned Git objects, verifies their hashes, and extracts only
the required wrapper and profile files into a **new** directory under
`private/uefi-realtek-reproduction/`. It replaces the defconfig in that isolated
copy and invokes the pinned
[build wrapper](https://github.com/ARK-Electronics/ark_jetson_kernel/blob/adf6376842a524531438362e7cf48826cb6e7dfe/scripts/build_fast_boot_uefi.sh)
with `--bsp R39.2.1 --build-dir <new-output>/build`. The wrapper downloads the
pinned sources, builds its container and RELEASE firmware, applies the existing
[single-boot-order patch](https://github.com/ARK-Electronics/ark_jetson_kernel/blob/adf6376842a524531438362e7cf48826cb6e7dfe/products/JAJ/fastboot/r39.2.1/uefi-single-boot-order.patch),
then restores that source change. The input checkout is never modified.

An existing output directory is refused; choose a new `--output-name` to repeat.
`--prepare-only` extracts inputs and records the command without building.
`--check` performs read-only input checks and does not invoke Docker. Following a
build, the helper checks the exact resolved config, module inventory, embedded
Realtek PE32 hash and firmware size. Its private `verification.json` records the
new firmware hash and whether it matches the measured image. Nothing stages,
flashes, deploys or accesses a device.

The measured experiment reused an isolated copy of an existing source/toolchain
cache and built RELEASE with four jobs and Docker networking disabled. The
public helper instead uses the pinned wrapper's normal download workflow. Its
Ubuntu package repositories and Python requirements are not a permanent binary
snapshot: the recorded container ID is provenance, not a published image that
others can pull. Fresh builds can use different package versions and need not
produce the same firmware hash. All source/configuration and resulting module
checks still apply; a build success is not hardware qualification.

The helper and documentation are MIT licensed. Third-party source keeps its
original licenses. The vendor [Realtek license](Realtek-PCIe-License.txt) is
included unchanged for the binary fetched by the build; it is not relicensed
under MIT. No vendor binary is distributed here.
