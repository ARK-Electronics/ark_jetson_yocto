# JAJ board sources

The carrier files are taken from
[ARK-Electronics/ark_jetson_kernel](https://github.com/ARK-Electronics/ark_jetson_kernel)
commit `adf6376842a524531438362e7cf48826cb6e7dfe`, under `products/JAJ/`.
No device backups, firmware binaries, credentials, or root filesystems are included.

`ark-jaj-devicetree` includes NVIDIA's Orin NX 16GB Super DTS first, then the
carrier delta. The HDMI DCB and boot-priority overlay retain their original
GPL notices. The new top-level DTS is GPL-2.0-only; recipe metadata is MIT.
The full upstream NVIDIA source and its license remain inputs supplied by
meta-tegra, not copied into this layer.

`ark-jaj-bct` carries the four checked-in MB1/MB2 configuration files. The three
spreadsheet-generated MB1 files retain NVIDIA's BSD-3-Clause notices; the MB2
file contains the carrier EEPROM configuration from the same source tree.
The BCT files have unique carrier names and LF newlines. The pinmux's GPIO
include is renamed accordingly; register values are unchanged. The checked-in
BCT files are authoritative, not the older spreadsheet.

`tegra-bootfiles` has no unpack task, so its append depends on `ark-jaj-bct` and
copies the carrier files from that recipe's sysroot into the flash input
package. Their `tegra234-` prefix is required by meta-tegra's flash-bundle glob.
The machine selects the three new configuration filenames; pinmux includes
the fourth (GPIO). Both firmware and extlinux select the custom DTB.

The machine supports only P3767-0000 (Orin NX 16GB), inherits NVIDIA's Super
nvpmodel, BPMP firmware, UPHY and NVMe/QSPI layout, and retains Linux FFC PCIe
controller C7 at Gen2. NVIDIA's Nano-only dynamic overlay does not overwrite
C7 for SKU 0000. Before adding Nano SKUs, remove its C7 max-link-speed write
or explicitly override it after that overlay. Do not disable C7 to improve
boot timing. USB, UART, HDA and HDMI carrier wiring remains in the base DTS.
No camera overlay is selected and no IMX708 driver is added.

Full UEFI is the baseline. The normal ARK boot-priority overlay is omitted if
`TEGRA_MINIMAL_BOOT` is explicitly enabled, to preserve minimal UEFI's required
single-device selector. That optional firmware configuration requires separate
hardware validation. Kernel/initramfs and BPMP fast-boot patches from the
Ubuntu build are intentionally not assumed compatible with Yocto's startup.

## Headless GPU startup

For this machine, `tegra-configs` replaces its display preload template with a
compute-only initialization: it records NVIDIA's `nvgpu-l4t` variant and loads
`nvgpu`, with failure propagated to `systemd-modules-load.service`. The display
modules and libraries remain installed; only automatic `nvidia_drm` loading in
this early hook is omitted. This avoids powering the GPU through DRM before
NVIDIA applies the configured static masks on R39.

The `tegra-nvpower` append replaces the native GPU handler's call to the
Ubuntu-only `/etc/systemd/nvpmodel.sh` wrapper, which OE4T does not install,
with `/usr/sbin/nvpmodel -f /etc/nvpmodel.conf </dev/null`. It changes only that
command and requires exactly one expected source match. The handler retains
its original failure check: if nvpmodel fails, it stops before GPU power-on.
The selected configuration is installed at image construction time, so the
Ubuntu wrapper's wait for that file is unnecessary.

The append requires module loading and udev, then waits for a
change event on the bound Orin GPU using NVIDIA's existing power-policy rule.
This scoped wait finishes before `nvpower.service` completes. The unchanged
`nvpmodel.service` already requires and follows nvpower, and the CUDA readiness
probe follows nvpmodel. No power mode, GPU mask, clock or fan policy is replaced;
`nvfancontrol` and the existing NVIDIA services remain enabled. A future display
image must explicitly load DRM after this power-policy sequence.

## Base and benchmark power defaults

The base `kas/jaj.yml` image retains NVIDIA's NX 16GB Super default mode 4
(`40W`). The optional `kas/bonsai.yml` benchmark variant uses meta-tegra's native
`NVPMODEL_CONFIG_DEFAULT = "0"` to select `MAXN_SUPER` in the installed
`/etc/nvpmodel.conf` before the first GPU power-on or CUDA context. The pinned
NX 16GB Super configuration names mode 0 `MAXN_SUPER`.

MAXN_SUPER requires adequate power delivery and active cooling. The native
recipe changes only the default selector; NVIDIA's mode definitions, masks,
clock limits and fan policy remain intact. This does not run `jetson_clocks`
or force mask values. Existing saved nvpmodel state on a reused rootfs can
override a config default, so use the freshly flashed benchmark image and
verify `nvpmodel -q` and thermals before comparing runs.
