#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

BASE = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("ark_grow_rootfs", str(BASE / "files/ark-grow-rootfs"))
spec = importlib.util.spec_from_loader(loader.name, loader)
growfs = importlib.util.module_from_spec(spec)
loader.exec_module(growfs)


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ark-grow-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mountinfo = self.root / "mountinfo"
        self.mountinfo.write_text("40 1 259:1 / / rw,relatime shared:1 - ext4 /dev/root rw\n")
        self.sys_blocks = self.root / "sys/dev/block"
        self.block = self.sys_blocks / "259:1"
        self.block.mkdir(parents=True)
        self.properties = {"DEVNAME": "nvme0n1p1", "DEVTYPE": "partition", "PARTN": "1", "PARTNAME": "APP"}
        self.write_properties()
        (self.block / "partition").write_text("1\n")
        self.dev_dir = self.root / "dev"
        self.device = self.dev_dir / "nvme0n1p1"
        self.device_stat = SimpleNamespace(st_mode=stat.S_IFBLK | 0o660, st_rdev=os.makedev(259, 1))
        self.root_stat = SimpleNamespace(st_dev=os.makedev(259, 1))
        self.marker = self.root / "completed"
        self.run = Mock()

    def write_properties(self):
        (self.block / "uevent").write_text("".join(key + "=" + value + "\n" for key, value in self.properties.items()))

    def stat_path(self, path):
        if path == "/":
            return self.root_stat
        self.assertEqual(path, self.device)
        return self.device_stat

    def identify(self):
        return growfs.mounted_app(self.mountinfo, self.sys_blocks, self.dev_dir, self.stat_path)

    def grow(self):
        growfs.grow(self.marker, self.identify, self.run, "/usr/sbin/resize2fs")

    def assert_rejected(self):
        with self.assertRaises((growfs.RootfsError, OSError, ValueError)):
            self.grow()
        self.run.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_grows_only_mounted_app_and_records_after_success(self):
        def resize(command, **kwargs):
            self.assertFalse(self.marker.exists())
            self.assertEqual(command, ["/usr/sbin/resize2fs", str(self.device)])
            self.assertEqual(kwargs, {"check": True})
        self.run.side_effect = resize
        self.grow()
        self.run.assert_called_once()
        self.assertIn(str(self.device), self.marker.read_text())
        self.assertFalse((self.root / ".completed.tmp").exists())

    def test_resize_failure_leaves_next_boot_retryable(self):
        self.run.side_effect = subprocess.CalledProcessError(1, "resize2fs")
        with self.assertRaises(subprocess.CalledProcessError):
            self.grow()
        self.assertFalse(self.marker.exists())
        self.run.side_effect = None
        self.grow()
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.run.call_count, 2)

    def test_completed_boot_does_not_resize_again(self):
        self.grow()
        self.run.reset_mock()
        self.mountinfo.unlink()
        self.grow()
        self.run.assert_not_called()

    def test_wrong_filesystem_readonly_and_subdirectory_mounts_rejected(self):
        for record in (
            "40 1 259:1 / / rw - btrfs /dev/root rw\n",
            "40 1 259:1 / / ro - ext4 /dev/root rw\n",
            "40 1 259:1 / / rw - ext4 /dev/root ro\n",
            "40 1 259:1 /subdir / rw - ext4 /dev/root rw\n",
            "40 1 259:1 / / rw - ext4 /dev/root\n",
            "40 1 bogus / / rw - ext4 /dev/root rw\n",
            "",
        ):
            with self.subTest(record=record):
                self.mountinfo.write_text(record)
                self.assert_rejected()

    def test_ambiguous_root_mount_rejected(self):
        self.mountinfo.write_text(self.mountinfo.read_text() * 2)
        self.assert_rejected()

    def test_different_mounted_root_device_rejected(self):
        self.root_stat.st_dev = os.makedev(259, 2)
        self.assert_rejected()

    def test_wrong_device_type_nvme_partition_and_label_rejected(self):
        for key, value in (("DEVNAME", "sda1"), ("DEVNAME", "nvme1n1p1"),
                           ("DEVNAME", "nvme0n1p2"), ("DEVTYPE", "disk"),
                           ("PARTN", "2"), ("PARTNAME", "APP_b"), ("PARTNAME", "")):
            with self.subTest(key=key, value=value):
                previous = self.properties[key]
                self.properties[key] = value
                self.write_properties()
                self.assert_rejected()
                self.properties[key] = previous
        self.write_properties()

    def test_partition_number_crosscheck_rejected(self):
        (self.block / "partition").write_text("2\n")
        self.assert_rejected()

    def test_missing_sysfs_identity_rejected(self):
        (self.block / "uevent").unlink()
        self.assert_rejected()

    def test_regular_file_or_mismatched_device_node_rejected(self):
        self.device_stat.st_mode = stat.S_IFREG | 0o660
        self.assert_rejected()
        self.device_stat.st_mode = stat.S_IFBLK | 0o660
        self.device_stat.st_rdev = os.makedev(259, 2)
        self.assert_rejected()

    def test_marker_failure_is_visible_and_leaves_retry(self):
        with patch.object(growfs.os, "replace", side_effect=OSError("read-only state")):
            with self.assertRaises(OSError):
                self.grow()
        self.run.assert_called_once()
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".completed.tmp").exists())
        self.grow()
        self.assertTrue(self.marker.exists())


class UnitTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    def test_readiness_requires_growth_without_ordering_cycle(self):
        bench_files = BASE.parents[1] / "recipes-support/ark-bench/files"
        with tempfile.TemporaryDirectory(prefix="ark-grow-units-") as temporary:
            root = Path(temporary)
            units = root / "etc/systemd/system"
            units.mkdir(parents=True)
            executable = root / "usr/libexec/ark-grow-rootfs"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            shutil.copyfile(executable, executable.with_name("ark-readiness"))
            executable.with_name("ark-readiness").chmod(0o755)
            (units / "ark-grow-rootfs.service").write_text((BASE / "files/ark-grow-rootfs.service").read_text().replace("@LIBEXECDIR@", "/usr/libexec"))
            for name in ("ark-os-ready.service", "ark-cuda-ready.service"):
                shutil.copyfile(bench_files / name, units / name)
                dropin = units / (name + ".d")
                dropin.mkdir()
                shutil.copyfile(BASE / "files/20-grow-rootfs.conf", dropin / "20-grow-rootfs.conf")
            for name in ("basic.target", "sysinit.target", "shutdown.target", "local-fs.target"):
                (units / name).write_text("[Unit]\nDefaultDependencies=no\n")
            (units / "multi-user.target").write_text("[Unit]\nRequires=basic.target\nAfter=basic.target\n")
            for name in ("nvpmodel.service", "systemd-modules-load.service"):
                (units / name).write_text("[Unit]\n[Service]\nType=oneshot\nExecStart=/usr/libexec/ark-readiness\n")
            wants = units / "multi-user.target.wants"
            wants.mkdir()
            for name in ("ark-grow-rootfs.service", "ark-os-ready.service", "ark-cuda-ready.service"):
                (wants / name).symlink_to("../" + name)
            result = subprocess.run(["systemd-analyze", "verify", "--man=no", "--root=" + str(root),
                                     "multi-user.target", "ark-grow-rootfs.service", "ark-os-ready.service", "ark-cuda-ready.service"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("cycle", result.stderr.lower())
            dropin = (BASE / "files/20-grow-rootfs.conf").read_text()
            self.assertIn("Requires=ark-grow-rootfs.service", dropin)
            self.assertIn("After=ark-grow-rootfs.service", dropin)


if __name__ == "__main__":
    unittest.main()
