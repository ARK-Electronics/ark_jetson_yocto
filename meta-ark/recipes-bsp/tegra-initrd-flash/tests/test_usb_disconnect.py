#!/usr/bin/env python3
"""Exercise the patched vendor functions against synthetic sysfs, never devices."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / "repos/meta-tegra/recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh"
PATCH = HERE.parent / "files/0001-initrd-flash-preserve-nested-usb-device-path.patch"


class UsbDisconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.staging = tempfile.TemporaryDirectory(prefix="ark-flash-patch-test-")
        staged = pathlib.Path(cls.staging.name) / "initrd-flash.sh"
        shutil.copyfile(SOURCE, staged)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
                       cwd=cls.staging.name, check=True, capture_output=True, text=True)
        subprocess.run(["bash", "-n", str(staged)], check=True)
        content = staged.read_text()
        cls.functions = content[content.index("usb_device_from_sysfs() {"):
                                content.index("wait_for_usb_storage() {")]

    @classmethod
    def tearDownClass(cls):
        cls.staging.cleanup()

    def setUp(self):
        self.tree = tempfile.TemporaryDirectory(prefix="ark-fake-sysfs-")
        self.addCleanup(self.tree.cleanup)
        self.base = pathlib.Path(self.tree.name)
        self.root_hub = self.usb_device(self.base / "devices/pci/usb1", "09")
        self.driver = self.base / "usb-driver"
        self.driver.mkdir()
        (self.driver / "unbind").write_text("")
        (self.driver / "bind").write_text("")

    @staticmethod
    def usb_device(path, device_class="00"):
        path.mkdir(parents=True)
        (path / "uevent").write_text("DRIVER=usb\nDEVTYPE=usb_device\n")
        if device_class is not None:
            (path / "bDeviceClass").write_text(device_class + "\n")
        return path

    @staticmethod
    def block_path(device):
        interface = device / (device.name + ":1.0")
        interface.mkdir()
        (interface / "uevent").write_text("DEVTYPE=usb_interface\n")
        block = interface / "host4/target4:0:0/4:0:0:0/block/sdz"
        block.mkdir(parents=True)
        (block / "uevent").write_text("DEVTYPE=disk\n")
        return block

    def resolve(self, path):
        return subprocess.run(["bash", "-c", self.functions +
                               '\nusb_device_from_sysfs "$1"', "test", str(path)],
                              capture_output=True, text=True)

    def release(self, path):
        # Substitute only absolute sysfs driver paths, and mock device queries.
        # The unmodified vendor control flow writes to regular temporary files.
        functions = self.functions.replace("/dev/.lxc/sys/bus/usb/drivers/usb",
                                            str(self.driver / "absent-fallback"))
        functions = functions.replace("/sys/bus/usb/drivers/usb", str(self.driver))
        mocks = r'''
readlink() { printf '%s\n' "$FAKE_BLOCK_PATH"; }
udisksctl() { return 1; }
sleep() { :; }
FAKE_BLOCK_PATH="$1"
unmount_and_release "" /dev/sdz
'''
        return subprocess.run(["bash", "-c", functions + mocks, "test", str(path)],
                              capture_output=True, text=True)

    def test_direct_port(self):
        device = self.usb_device(self.root_hub / "1-5")
        result = self.resolve(self.block_path(device))
        self.assertEqual((result.returncode, result.stdout), (0, "1-5\n"))

    def test_nested_hub_disconnects_only_target(self):
        hub = self.usb_device(self.root_hub / "1-5", "09")
        sibling = self.usb_device(hub / "1-5.2")
        (sibling / "sentinel").write_text("unrelated equipment")
        device = self.usb_device(hub / "1-5.3")
        result = self.release(self.block_path(device))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.driver / "unbind").read_text(), "1-5.3\n")
        self.assertEqual((self.driver / "bind").read_text(), "1-5.3\n")
        self.assertEqual((sibling / "sentinel").read_text(), "unrelated equipment")

    def test_multiple_hubs_and_multidigit_ports(self):
        root_hub = self.usb_device(self.base / "devices/pci/usb12", "09")
        hub = self.usb_device(root_hub / "12-10", "09")
        hub2 = self.usb_device(hub / "12-10.3", "09")
        device = self.usb_device(hub2 / "12-10.3.11")
        result = self.resolve(self.block_path(device))
        self.assertEqual((result.returncode, result.stdout), (0, "12-10.3.11\n"))

    def assert_refuses_release(self, path):
        result = self.release(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.driver / "unbind").read_text(), "")
        self.assertEqual((self.driver / "bind").read_text(), "")

    def test_refuses_hub(self):
        hub = self.usb_device(self.root_hub / "1-5", "09")
        self.assert_refuses_release(self.block_path(hub))

    def test_refuses_root_hub(self):
        self.assert_refuses_release(self.root_hub)

    def test_missing_or_invalid_device_class(self):
        for index, device_class in enumerate((None, "", "invalid")):
            with self.subTest(device_class=device_class):
                device = self.usb_device(self.root_hub / ("1-" + str(index + 1)), device_class)
                self.assert_refuses_release(self.block_path(device))

    def test_disappeared_target_never_falls_back_to_hub(self):
        hub = self.usb_device(self.root_hub / "1-5", "09")
        device = self.usb_device(hub / "1-5.3")
        block = self.block_path(device)
        (device / "uevent").unlink()
        self.assert_refuses_release(block)

    def test_non_usb_path(self):
        block = self.base / "devices/pci/nvme/nvme0/nvme0n1"
        block.mkdir(parents=True)
        self.assert_refuses_release(block)


if __name__ == "__main__":
    unittest.main()
