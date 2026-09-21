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
