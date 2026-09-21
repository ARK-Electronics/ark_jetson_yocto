# First-boot root filesystem growth

OE4T's initrd flasher grows the single-root APP partition to the remaining NVMe capacity when it creates the partition table. The root image still contains its original ext4 filesystem size. `ark-grow-rootfs.service` uses the native `e2fsprogs-resize2fs` utility to grow that mounted filesystem to its existing partition's capacity. It never changes partitions.

Before invoking the utility, the helper verifies that `/` is a writable, complete ext4 mount, that its device number matches the mounted root and block device, and that the kernel identifies the partition as `nvme0n1p1`, partition 1, named `APP`. Other layouts fail visibly. The helper records `/var/lib/ark-grow-rootfs/completed` only after `resize2fs` returns success. A failure leaves no success marker and is retried on the next boot. Inspect `systemctl status ark-grow-rootfs.service` and `journalctl -u ark-grow-rootfs.service` for details.

Both ARK readiness services require successful growth. A growth failure suppresses their success markers while allowing the rest of multi-user boot, including SSH, to proceed. Initial growth is provisioning work: exclude the first boot after flashing from boot-time comparisons. Confirm the completion marker and available capacity with `df -h /`, then collect subsequent cold boots.

Run the device-free guard/failure tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s meta-ark/recipes-core/ark-grow-rootfs/tests -v
```

The tests use synthetic mount/sysfs records and a fake resize command. Actual on-device first-boot growth remains to be qualified with the Yocto image.
