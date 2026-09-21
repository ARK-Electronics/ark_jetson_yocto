#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host checks for native CPU correctness, marker behavior and systemd ordering.

Requires CMake, a C++ compiler and OpenSSL development files. The CUDA build and
real GPU execution remain target/build validation; no host result substitutes.
"""
import hashlib
import json
import os
import pty
import select
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FILES = Path(__file__).resolve().parent / 'files'


class CpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='ark-bench-cpu-')
        cls.build = Path(cls.temporary.name)
        for command in (["cmake", "-S", str(FILES), "-B", str(cls.build),
                         "-DARK_ENABLE_CUDA=OFF", "-DCMAKE_BUILD_TYPE=Release"],
                        ["cmake", "--build", str(cls.build), "-j2"]):
            subprocess.run(command, check=True, capture_output=True, text=True)
        cls.binary = cls.build / 'ark-cpu-bench'

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_workloads_match_independent_hashlib(self):
        block = bytes(range(256)) * 4096
        for mib in (64, 256, 1024):
            with self.subTest(mib=mib):
                result = subprocess.run([str(self.binary), '--mib', str(mib), '--repeats', '2'],
                                        check=True, capture_output=True, text=True, timeout=60)
                report = json.loads(result.stdout)
                digest = hashlib.sha256()
                for _ in range(mib):
                    digest.update(block)
                self.assertTrue(report['passed'])
                self.assertEqual(report['expected_sha256'], digest.hexdigest())
                self.assertEqual(report['bytes_per_repeat'], mib * 1024 * 1024)
                self.assertEqual(len(report['samples']), 2)
                for sample in report['samples']:
                    self.assertGreater(sample['wall_ms'], 0)
                    self.assertAlmostEqual(sample['mib_per_second'], mib * 1000 / sample['wall_ms'], places=5)

    def test_invalid_or_unbounded_workloads_fail_with_json(self):
        for args in (['--mib', '1'], ['--mib', '-1'], ['--repeats', '0'],
                     ['--repeats', '999999999999999999999999'], ['--other'], ['--mib']):
            with self.subTest(args=args):
                result = subprocess.run([str(self.binary), *args], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(json.loads(result.stdout)['passed'])


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ark-bench-marker-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.uptime = self.root / 'uptime'
        self.uptime.write_text('12.34 55.66\n')
        self.probe = self.root / 'fake-cuda-bench'
        self.script = self.root / 'ark-readiness'
        text = (FILES / 'ark-readiness').read_text()
        text = text.replace('/run/ark-bench', str(self.root)).replace('/proc/uptime', str(self.uptime))
        text = text.replace('/usr/bin/ark-cuda-bench', str(self.probe))
        self.script.write_text(text)
        self.probe.write_text('#!/bin/sh\nprintf \'{"passed":true}\\n\'\n')
        self.probe.chmod(0o755)

    def run_marker(self, name, tty='/dev/null'):
        return subprocess.run(['/bin/sh', str(self.script), name], capture_output=True, text=True, timeout=5,
                              env={**os.environ, 'ARK_READINESS_TTY': tty})

    def test_os_marker_is_linux_uptime_with_explicit_milestone(self):
        result = self.run_marker('os')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'ARK_OS_READY uptime_s=12.34 milestone=multi_user_target\n')
        self.assertEqual(json.loads((self.root / 'os-ready.json').read_text())['uptime_s'], 12.34)

    def test_explicit_character_console_receives_same_marker(self):
        master, slave = pty.openpty()
        try:
            result = self.run_marker('os', os.ttyname(slave))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(select.select([master], [], [], 1)[0])
            received = os.read(master, 4096).decode().replace('\r\n', '\n')
            self.assertEqual(received, result.stdout)
        finally:
            os.close(master)
            os.close(slave)

    def test_regular_file_cannot_be_clobbered_as_console(self):
        candidate = self.root / 'not-a-tty'
        candidate.write_text('preserve')
        result = self.run_marker('os', str(candidate))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(candidate.read_text(), 'preserve')
        self.assertIn('ARK_READINESS_UART_UNAVAILABLE', result.stderr)
        self.assertIn('ARK_OS_READY', result.stdout)

    def test_cuda_success_and_later_failure_cannot_leave_stale_ready(self):
        result = self.run_marker('cuda')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ARK_CUDA_READY uptime_s=12.34', result.stdout)
        self.assertTrue((self.root / 'cuda-ready.json').exists())
        self.probe.write_text('#!/bin/sh\nprintf \'{"passed":false}\\n\'\nexit 9\n')
        result = self.run_marker('cuda')
        self.assertEqual(result.returncode, 9)
        self.assertIn('ARK_CUDA_FAILED uptime_s=12.34 status=9', result.stdout)
        self.assertNotIn('ARK_CUDA_READY', result.stdout)
        self.assertFalse((self.root / 'cuda-ready.json').exists())
        self.assertFalse(json.loads((self.root / 'cuda-smoke.json').read_text())['passed'])

    def test_no_ready_marker_when_uptime_is_invalid(self):
        self.uptime.write_text('not-a-time 0\n')
        result = self.run_marker('os')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('ARK_OS_READY', result.stdout)


class UnitTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze not installed')
    def test_multiuser_wants_observer_units_has_no_dependency_cycle(self):
        with tempfile.TemporaryDirectory(prefix='ark-bench-units-') as temporary:
            root = Path(temporary)
            units = root / 'etc/systemd/system'
            units.mkdir(parents=True)
            (root / 'usr/libexec').mkdir(parents=True)
            executable = root / 'usr/libexec/ark-readiness'
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            for name in ('ark-os-ready.service', 'ark-cuda-ready.service'):
                shutil.copyfile(FILES / name, units / name)
                wants = units / 'multi-user.target.wants'
                wants.mkdir(exist_ok=True)
                (wants / name).symlink_to('../' + name)
            for name in ('basic.target', 'sysinit.target', 'shutdown.target'):
                (units / name).write_text('[Unit]\nDefaultDependencies=no\n')
            (units / 'multi-user.target').write_text('[Unit]\nRequires=basic.target\nAfter=basic.target\n')
            for name in ('nvpmodel.service', 'systemd-modules-load.service'):
                (units / name).write_text('[Unit]\n[Service]\nType=oneshot\nExecStart=/usr/libexec/ark-readiness\n')
            result = subprocess.run(['systemd-analyze', 'verify', '--man=no', '--root=' + str(root),
                                     'multi-user.target', 'ark-os-ready.service', 'ark-cuda-ready.service'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('cycle', result.stderr.lower())


if __name__ == '__main__':
    unittest.main()
