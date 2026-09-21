# Flashing and recovery

The default `scripts/flash.sh` operation **replaces every partition on the
Jetson's NVMe drive and preserves QSPI boot firmware**. It is not an APP-only
update. Back up the original installation, including models and other private
files, before starting.

This wrapper is for `ark-headless-image`, machine `ark-jaj-orin-nx`, the ARK
Just a Jetson carrier, and an Orin NX 16GB module (`P3767-0000`, T234). It accepts
only the pinned R39.2.1 OE4T helpers plus this repository's USB hub fix. Container
and offline checks can be run without a Jetson. Successful flashing and booting
must be recorded separately; a passing dependency dry-run is not a flash test.

## What the operation changes

| Mode | NVMe | QSPI |
| --- | --- | --- |
| Default, upstream `--external-only` | Recreates the complete partition table and writes the image | Preserved |
| `--full-flash --confirm-write-qspi` | Recreates the complete partition table and writes the image | Replaced with bundle firmware |
| `--check` | No device access | No device access |

The retained QSPI must already contain compatible R39.2.1 Super firmware and a
boot configuration that can load this NVMe installation. The wrapper cannot
infer the installed firmware version from the recovery USB ID. Preserve its
version, original carrier configuration, and backup before recovery mode.
Keeping QSPI also keeps a custom fast UEFI already installed there; full flashing
replaces it with the firmware built into this bundle.

Both modes first boot the bundle's recovery kernel, device tree, BCT and pinmux
configuration into RAM. These must match the physical carrier even when QSPI
will be preserved. The wrapper checks the JAJ filenames and Super BPMP selection
and freshly reads the module EEPROM before writing. It rejects other board
IDs/SKUs, early `TS1`/`EB1` modules unsupported by this Super configuration, and
missing serial data used to identify the exported storage device.

T234 does not support the upstream `--partition` option. Omitting `--erase-nvme`
does not retain partitions: `make-sdcard` still clears and recreates the GPT.
The exact behavior is in the pinned
[initrd-flash source](https://github.com/OE4T/meta-tegra/blob/2e37d1673d25fb92440bcf6db8dcf1076e822037/recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh)
and [make-sdcard source](https://github.com/OE4T/meta-tegra/blob/2e37d1673d25fb92440bcf6db8dcf1076e822037/recipes-bsp/tegra-binaries/tegra-helper-scripts/make-sdcard.sh).

## Host and artifact

Use a native x86_64 Linux host with a local, rootful Docker daemon. The invoking
user needs permission to use Docker, plus Python 3.12 or later, `debugfs`
(`e2fsprogs`), and `zstd`. Host `sudo` is not required by this wrapper. Docker
Desktop, rootless Docker, remote Docker contexts and USB forwarding through a VM
are outside this supported path.

`docker/Dockerfile.flash` pins its Ubuntu 24.04 base digest and the Ubuntu archive
snapshot `20260921T000000Z`. Its CA bootstrap package is checksummed. This fixes
package inputs rather than following the current apt repositories; see the
[Ubuntu snapshot service](https://snapshot.ubuntu.com/). The image records its
installed package versions in `/usr/local/share/flash-package-versions.txt`.
The wrapper builds a container tag derived from the Dockerfile hash when needed.
It downloads no BSP or models: the trusted build artifact supplies NVIDIA's tools
and firmware. Observe the licenses accompanying those artifacts.

Build the selected image, then validate its deploy artifact:

```bash
ARTIFACT=build/tmp/deploy/images/ark-jaj-orin-nx/ark-headless-image-ark-jaj-orin-nx.rootfs.tegraflash-tar.zst
./scripts/flash.sh --artifact "$ARTIFACT" --check
```

An uncompressed tar archive or an already extracted bundle is also accepted:

```bash
./scripts/flash.sh --bundle /absolute/path/to/extracted-bundle --check
```

The wrapper stages a separate copy under ignored `private/flash/`, preserving the
input. `--work-dir` selects a new directory elsewhere. Allow room for extraction
and signing; the raw ext4 image is sparse, and a copy tool or filesystem that
expands holes can need its full logical size. Checks verify machine/image/BSP
metadata, carrier configuration, helper hashes, the single-root layout, and
`ID=ark-headless` inside the root filesystem. They do not authenticate an arbitrary
third-party bundle: its remaining executables run with hardware privileges. Use
your own build or an authenticated release; `--sha256 HASH` additionally checks
an archive against an independently obtained digest.

Presigned and fused/secure-boot installations need a separately reviewed signing
and key-provisioning workflow. This wrapper deliberately does not forward PKC or
SBK keys or accept `.presigning-vars` bundles.

## Back up the original installation

Keep backups, source BSP, carrier configuration, model weights, keys and logs in
private storage. Save the original OS/kernel/BSP versions, `nvbootctrl` slot
information, disk size, `lsblk`, `blkid`, partition table, and boot configuration.
A filesystem archive alone does not preserve GPT, partition GUIDs, small boot
partitions or QSPI. A live copy can also race applications writing their files.

An offline backup does not require removing the NVMe. From the **original,
matching NVIDIA BSP**, boot its RAM recovery environment using the exact original
carrier configuration and overlays. Its `--initrd --boot-rootfs` path stops
before storage flashing. Follow that BSP's `tools/kernel_flash/README_initrd_flash.txt`
and its host prerequisites; it is a different workflow from this repository's
OE4T USB mass-storage flasher. The wrapper does not configure NFS, host networking
or NVIDIA's backup service for you. Never use OE4T `initrd-flash` as a backup
boot command: after booting it automatically sends a write sequence.

In the RAM recovery shell, verify that **all** partitions of `/dev/nvme0n1` are
unmounted. Record `/proc/mtd` to identify the complete QSPI device. Use a recovery
SSH configuration of your own; the examples below use a host alias already set
up as `RECOVERY_HOST`, without embedding an address or credential.

A complete raw NVMe backup preserves GPT, every partition, filesystem UUIDs,
PARTUUIDs and all file data. It reads the entire drive, and compression savings
are not guaranteed. Reserve at least the disk's full byte size for worst-case
backup storage. From a private directory on the host, after verifying the target:

```bash
set -o pipefail
ssh "$RECOVERY_HOST" 'lsblk -b -o NAME,SIZE,TYPE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS /dev/nvme0n1' > nvme-inventory.txt
ssh "$RECOVERY_HOST" 'sfdisk --dump /dev/nvme0n1' > nvme-partitions.sfdisk
ssh "$RECOVERY_HOST" 'blockdev --getsize64 /dev/nvme0n1' > nvme-size-bytes.txt
ssh "$RECOVERY_HOST" 'dd if=/dev/nvme0n1 bs=4M iflag=fullblock status=progress' \
  | zstd -T2 -3 -o nvme.img.zst
zstd -t nvme.img.zst
```

Save QSPI separately. Only use the following device name after `/proc/mtd`
confirms that `/dev/mtd0` is the complete boot QSPI device on this module:

```bash
ssh "$RECOVERY_HOST" 'cat /proc/mtd' > mtd-inventory.txt
ssh "$RECOVERY_HOST" 'dd if=/dev/mtd0 bs=1M status=progress' > qspi.img
sha256sum nvme.img.zst qspi.img > SHA256SUMS
sha256sum -c SHA256SUMS
```

Require successful pipeline exit codes and exact uncompressed byte counts against
the inventories. Verify the backup contains the original model files and their
known hashes, preferably by restoring to spare storage before migration. A raw
backup also retains unused/deleted sectors; protect it as private data.

For a smaller vendor-supported backup, NVIDIA's matching
`tools/backup_restore/l4t_backup_restore.sh -e nvme0n1 -b BOARD_CONFIG` produces a
partition map, used-file archives for ext4, other partition images and QSPI data.
Read its included README and inspect its log: it mounts ext4 during collection,
and a zero wrapper exit alone does not prove every archived file was copied.
The corresponding `-r` restore normally writes **both NVMe and QSPI**, even with
`-e nvme0n1`. See NVIDIA's
[R39.2.1 flashing and backup guide](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/FlashingSupport.html).

## Enter recovery and flash

Connect the carrier's recovery USB port using a data cable and enter Force
Recovery using the carrier's documented controls. `lsusb -d 0955:7323` identifies
the Orin NX 16GB recovery device. This ID identifies the module, not the carrier
or installed firmware. See NVIDIA's
[recovery USB IDs](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/IN/QuickStart.html).

After making and verifying the backup:

```bash
./scripts/flash.sh --artifact "$ARTIFACT" --confirm-erase-nvme
```

When several modules are connected, supply `--usb-instance "$USB_INSTANCE"`,
where the value is the exact device path under `/sys/bus/usb/devices`. Hub paths
are supported only by the patched helper whose hash the wrapper verifies. The
patch disconnects the selected USB device, never an ancestor hub.

To intentionally replace the boot firmware as well:

```bash
./scripts/flash.sh --artifact "$ARTIFACT" \
  --full-flash --confirm-erase-nvme --confirm-write-qspi
```

The container runs as UID 0 with `USER=root` because NVIDIA's legacy signing tools
consult that variable. It uses no network, NFS or host D-Bus service. The Orin
flash initrd enumerates as `1d6b:0104` and exports `flashpkg` and `nvme0n1` as
USB mass-storage devices. NVIDIA's separate recovery/backup environment can use
`0955:7035`; that is not the OE4T gadget ID.

Dynamic `/dev` access is required because the gadget re-enumerates and creates
new `/dev/sd*` devices and partitions. The default container grants `SYS_ADMIN`,
USB character major 189 and SCSI block majors 8/65, plus the selected USB driver's
bind/unbind controls. Its AppArmor/seccomp restrictions are relaxed inside this
container for mount and block-device operations. This remains a trusted-tools
workflow with access to host SCSI disks; helper identity and gadget matching are
important. The pinned helper scans only `/dev/sda` through `/dev/sdz`.

A short root Docker helper temporarily installs one uniquely named rule under
`/run/udev/rules.d`, matching only the selected port's `1d6b:0104` block devices.
It sets `UDISKS_IGNORE=1`/`UDISKS_AUTO=0`, reloads host udev rules, and removes its
rule on exit. Existing rules and services are untouched; the main flash container
has read-only `/run/udev`. A custom automounter that ignores those properties
requires a suitable dedicated flash host. An interrupted host or killed wrapper
can leave its runtime rule behind; inspect the reported rule name before removing
it and reloading udev.

`--privileged-container` is an explicit fallback for a host that cannot provide
the scoped device access. It grants broad host hardware access and belongs on a
dedicated flash host. The wrapper never enables that fallback automatically or
changes host security policy.

Private run directories contain the wrapper transcript, validation report,
upstream `log.initrd-flash.*`, generated board data and device logs. Keep them
private because board serials appear there. The wrapper requires both a successful
host process and the target's exact `Final status: SUCCESS`; the pinned upstream
script alone can return zero after a target failure.

After success, capture UART through boot, verify SSH, confirm `ID=ark-headless`,
check NVMe mounts and the expected device tree, then run the GPU checks before
restoring models or claiming application readiness. Flash completion does not
establish that the OS or CUDA works.

## Restore the original system

For the default external-only migration, leave the preserved QSPI alone. Boot
the original matching RAM recovery environment again, verify the target identity
and unmounted NVMe, validate `SHA256SUMS`, and check that the disk has exactly the
recorded byte size. Then restore the complete raw disk image:

```bash
set -o pipefail
sha256sum -c SHA256SUMS
zstd -dc nvme.img.zst \
  | ssh "$RECOVERY_HOST" 'dd of=/dev/nvme0n1 bs=4M iflag=fullblock conv=fsync status=progress'
ssh "$RECOVERY_HOST" sync
```

Require the complete saved byte count and successful pipeline exit before
rebooting. This restores the original partition GUIDs and filesystem UUIDs,
avoiding the UUID changes a file-level reconstruction can introduce. Validate
the original boot, files and model hashes again.

If QSPI was also replaced, restoring NVMe alone is insufficient. Use the original
BSP and carrier-specific firmware restore procedure, or the matching NVIDIA
backup/restore package prepared before migration. A raw `qspi.img` is an archival
copy; do not assume the NVMe wrapper or `dd` can program it correctly. NVIDIA's
standard restore can overwrite both media, so review its partition map and
selected board configuration before executing it.
