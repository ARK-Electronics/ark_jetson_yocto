# Optional camera-less bench

Use this fragment only when no CSI camera is attached:

```sh
scripts/build.sh build kas/jaj.yml:kas/no-camera.yml:local.yml
```

It is independent of power mode and kernel boot-time tuning. To combine the
MAXN_SUPER Bonsai runtime, optional BPMP tuning and camera-less setup:

```sh
scripts/build.sh build kas/jaj.yml:kas/bonsai.yml:kas/fastboot.yml:kas/no-camera.yml:local.yml
```

The base configuration and camera drivers remain unchanged. The fragment selects
`ark-no-camera-overlay` as `virtual/dtbo`; OE4T's `l4t-launcher-extlinux` recipe
installs and, when configured, signs `/boot/ark_no_csi.dtbo`. Its extlinux entry
contains `OVERLAYS /boot/ark_no_csi.dtbo` alongside the existing explicit `FDT`.
This fragment selects the complete extlinux overlay list; do not combine it with
a camera-enabling overlay. Remove the fragment and rebuild/deploy the matching
boot files before using CSI cameras again.

The overlay sets only `/bus@0/cam_i2cmux/status` to `disabled`, preventing both
camera I2C branches from enumerating. It does not disable GPU, PCIe, security,
power policy, or the camera drivers. It is harmless when the clean DTB contains
no camera mux. It does not claim to disable every camera-related SoC service.

## Retained firmware and ordering

The clean Yocto JAJ DTB contains no IMX219 sensors. Previous JAJ firmware from
`ark_jetson_kernel` commit `adf6376842a524531438362e7cf48826cb6e7dfe` includes
`tegra234-p3767-camera-p3768-imx219-dual.dtbo` through
`products/JAJ/default_overlays`. An external-only flash preserves this firmware.

R39's `DxeDtPlatformDtbKernelLoaderLib.c` registers `UpdateFdt` for DTB-table
installation. It reapplies firmware-media overlays unless the tree already has
`/firmware/uefi/firmware-media-overlays-applied`. `L4TLauncher.c` installs the disk
FDT first, then processes explicit extlinux `OVERLAYS`, so this optional overlay
can disable the mux after the retained camera overlay has been applied. Never
set that firmware marker manually to suppress overlays: other firmware overlays
include required carveout and security configuration.

## Validation

With `dtc` and `fdtoverlay` on the host and existing JAJ build artifacts:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s meta-ark/recipes-bsp/ark-no-camera-overlay/tests -v
```

The tests compile the actual overlay, apply it to the clean DTB and a tree merged
with the pinned NVIDIA dual-IMX219 overlay, and compare every node/property.
Only the camera-mux status changes (or that disabled node is added). C4, C7 and
GPU configuration therefore remain identical. They also execute OE4T's actual
extlinux generation and install functions in a temporary directory to check the
`OVERLAYS` entry and installed path. Alternate artifacts can be selected through
`ARK_NO_CAMERA_BASE_DTB` and `ARK_NO_CAMERA_SENSOR_DTBO`.

Hardware validation remains separate: verify the runtime mux status is disabled,
the two IMX219 probe attempts disappear, and CUDA, NVMe and required PCIe devices
still work. Record this variant separately from the camera-enabled baseline;
no boot-time saving is promised.
