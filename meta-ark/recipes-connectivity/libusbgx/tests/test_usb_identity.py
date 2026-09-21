#!/usr/bin/env python3
"""Exercise the patched native setup against a synthetic sysfs/DT/runtime tree."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[4]
SOURCE = REPO / "repos/meta-tegra/external/openembedded-layer/recipes-support/libusbgx/libusbgx-config"
PATCH = Path(__file__).resolve().parents[1] / "libusbgx-config/0001-stable-usb-network-addresses.patch"
ROLES = ("rndis-device", "rndis-host", "ecm-device", "ecm-host")


class USBIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = tempfile.TemporaryDirectory()
        cls.patched = Path(cls.sources.name)
        for filename in ("l4t-gadget-config-setup.sh", "l4t.schema.in"):
            shutil.copyfile(SOURCE / filename, cls.patched / filename)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
                       cwd=cls.patched, check=True, capture_output=True)
        cls.setup_script = (cls.patched / "l4t-gadget-config-setup.sh").read_text()
        subprocess.run(["sh", "-n", str(cls.patched / "l4t-gadget-config-setup.sh")], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.sources.cleanup()

    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name)
        for name in ("sys/module/libcomposite", "sys/module/bridge", "run", "proc/device-tree",
                     "usr/share/usbgx", "bin"):
            (self.root / name).mkdir(parents=True)
        self.serial = self.root / "proc/device-tree/serial-number"
        self.serial.write_bytes(b"ARK-TEST-000001\0")
        self.schema = self.root / "run/usbgx/l4t.schema"
        shutil.copyfile(self.patched / "l4t.schema.in", self.root / "usr/share/usbgx/l4t.schema.in")
        script = self.setup_script
        for path in ("/sys/module/", "/run/usbgx", "/proc/device-tree/", "/usr/share/usbgx/"):
            script = script.replace(path, str(self.root) + path)
        self.script = self.root / "setup.sh"
        self.script.write_text(script)
        self.environment = dict(os.environ, LC_ALL="C", PATH=str(self.root / "bin") + ":" + os.environ["PATH"])

    def run_setup(self, success=True):
        result = subprocess.run(["sh", str(self.script)], env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def macs(self):
        output = self.schema.read_text()
        self.assertNotIn("@", output)
        addresses = re.findall(r'(?:dev_addr|host_addr) = "([0-9a-f:]+)";', output)
        self.assertEqual(len(addresses), 4)
        self.assertEqual(len(set(addresses)), 4)
        for address in addresses:
            self.assertRegex(address, r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
            self.assertEqual(int(address[:2], 16) & 3, 2)
        return addresses

    def fake_command(self, name, body):
        command = self.root / "bin" / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
        return command

    def assert_no_partial_schema(self):
        self.assertFalse(self.schema.exists())
        self.assertEqual(list((self.root / "run/usbgx").glob(".l4t.schema.*")), [])

    def test_stable_cold_boot_identity_and_independent_reference(self):
        self.run_setup()
        first = self.schema.read_text()
        expected = []
        for role in ROLES:
            address = bytearray(hashlib.sha256(f"ark-jaj-usb-mac-v1:ARK-TEST-000001:{role}".encode()).digest()[:6])
            address[0] = (address[0] | 2) & 254
            expected.append(":".join(f"{byte:02x}" for byte in address))
        self.assertEqual(self.macs(), expected)
        self.assertEqual(stat.S_IMODE(self.schema.stat().st_mode), 0o644)
        self.schema.unlink()
        self.run_setup()
        self.assertEqual(self.schema.read_text(), first)

    def test_distinct_module_and_function_addresses(self):
        seen = set()
        for module in range(32):
            self.serial.write_bytes(f"ARK-TEST-{module:06d}".encode() + b"\0")
            self.schema.unlink(missing_ok=True)
            self.run_setup()
            addresses = set(self.macs())
            self.assertFalse(seen & addresses)
            seen.update(addresses)

    def test_missing_serial_fails_without_shared_identity(self):
        self.serial.unlink()
        self.run_setup(success=False)
        self.assert_no_partial_schema()

    def test_invalid_serial_fails_without_partial_schema(self):
        for serial in (b"\0", b"UNKNOWN\0", b'bad"serial\0', b"bad,serial\0", b"x" * 129):
            with self.subTest(serial=serial):
                self.serial.write_bytes(serial)
                self.run_setup(success=False)
                self.assert_no_partial_schema()

    def test_missing_template_fails(self):
        (self.root / "usr/share/usbgx/l4t.schema.in").unlink()
        self.run_setup(success=False)
        self.assert_no_partial_schema()

    def test_hash_failure_is_not_silently_accepted(self):
        self.fake_command("sha256sum", "exit 2")
        self.run_setup(success=False)
        self.assert_no_partial_schema()

    def test_malformed_hash_is_rejected(self):
        self.fake_command("sha256sum", "printf 'not-a-hash\\n'")
        self.run_setup(success=False)
        self.assert_no_partial_schema()

    def test_duplicate_role_addresses_are_rejected(self):
        self.fake_command("sha256sum", "printf '%064d  -\\n' 0")
        self.run_setup(success=False)
        self.assert_no_partial_schema()

    def test_failed_render_is_atomic_and_can_retry(self):
        sed = self.fake_command("sed", f'if [ "$#" -gt 2 ]; then exit 2; fi\nexec {shutil.which("sed")} "$@"')
        self.run_setup(success=False)
        self.assert_no_partial_schema()
        sed.unlink()
        self.run_setup()
        self.macs()

    def test_failed_permissions_are_atomic_and_can_retry(self):
        chmod = self.fake_command("chmod", "exit 2")
        self.run_setup(success=False)
        self.assert_no_partial_schema()
        chmod.unlink()
        self.run_setup()
        self.macs()

    def test_existing_schema_is_kept_for_service_restart(self):
        self.run_setup()
        first = self.schema.read_bytes()
        self.serial.unlink()
        self.run_setup()
        self.assertEqual(self.schema.read_bytes(), first)

    def test_network_pool_covers_both_usb_functions(self):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(REPO / "repos/meta-tegra/recipes-bsp/l4t-usb-device-mode/l4t-usb-device-mode/70-l4tbr0.network")
        config.read(REPO / "meta-ark/recipes-connectivity/l4t-usb-device-mode/files/10-ark-usb-dhcp.conf")
        self.assertEqual(config["Network"]["Address"], "192.168.55.1/24")
        self.assertEqual(config["DHCPServer"]["PoolOffset"], "100")
        self.assertEqual(config["DHCPServer"]["PoolSize"], "2")
        self.assertEqual(config["DHCPServer"]["EmitRouter"], "no")


if __name__ == "__main__":
    unittest.main()
