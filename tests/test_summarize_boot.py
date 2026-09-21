#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic synthetic captures only; no serial, SSH or power access."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/summarize-boot.py'
spec = importlib.util.spec_from_file_location('summarize_boot', SCRIPT)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)
BASE = 100_000_000_000


class Fixture:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir()
        self.events = []
        self.offset = 0
        self.metadata = {'schema_version': 1, 'status': 'ready',
                         'reference_label': summary.REFERENCE, 'reference_monotonic_ns': BASE,
                         'network_readiness_kind': 'ssh_banner', 'readiness': {},
                         'instrument': {'serial': 'FIXTURE_SERIAL_SECRET'},
                         'configuration': {'serial': '/private/adapter/FIXTURE_SERIAL_SECRET',
                                           'host': '192.0.2.55', 'expected_serial': 'FIXTURE_SERIAL_SECRET',
                                           'poll_interval': .05, 'duration': 60},
                         'final_supply': {'output': 'ON', 'ocp_tripped': False, 'ovp_tripped': False}}
        self.arm(0)

    def event(self, name, at, **fields):
        self.events.append({'event': name, 'monotonic_ns': BASE + round(at * 1e9), **fields})

    def arm(self, at, label=summary.REFERENCE):
        self.event('reference_started', at, label=label, electrical_edge_measured=False)
        self.metadata.update(reference_label=label, reference_monotonic_ns=BASE + round(at * 1e9))

    def uart(self, at, text):
        data = text.encode() if isinstance(text, str) else text
        self.event('uart_received', at, raw_offset=self.offset, length=len(data),
                   data_base64=base64.b64encode(data).decode(), text=data.decode(errors='replace'))
        self.offset += len(data)

    def ssh(self, at, metadata=True):
        self.event('ssh_banner_ready', at)
        if metadata:
            self.metadata['readiness']['ssh_banner'] = {'monotonic_ns': BASE + round(at * 1e9),
                                                       'reference_elapsed_s': 999999}

    def save(self):
        (self.directory / 'metadata.json').write_text(json.dumps(self.metadata))
        (self.directory / 'timeline.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.events))
        return self.directory


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='private-FIXTURE_SERIAL_SECRET-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.number = 0

    def fixture(self):
        self.number += 1
        return Fixture(self.root / ('run-' + str(self.number)))

    def test_split_markers_prompt_utf8_and_pre_reference_noise(self):
        f = self.fixture()
        f.uart(-2, 'ARK_OS_READY uptime_s=999 milestone=old\n')
        f.ssh(-1, metadata=False)
        f.uart(-.1, 'ARK_')
        f.uart(.1, 'OS_READY uptime_s=999 milestone=invalid-fragment\n')
        f.uart(1, b'noise \xe2')
        f.uart(1.1, b'\x82\xac\r\n')
        f.uart(5, 'ARK_OS_RE')
        f.uart(5.2, 'ADY uptime_s=3.')
        f.uart(5.3, '25')
        f.uart(5.4, ' milestone=multi_user_target\n')
        f.uart(5.6, 'ARK_CUDA_READY uptime_s=3.50 milestone=cuda_integer_smoke_passed\n')
        f.uart(6, 'ark')
        f.uart(6.1, '-jaj lo')
        f.uart(6.2, 'gin: ')
        f.ssh(7)
        report = summary.make_report([f.save()], 'login')
        run = report['runs'][0]
        self.assertTrue(run['eligible_for_aggregate'], run['issues'])
        observations = run['observations']
        self.assertEqual(observations['os_ready']['elapsed_s'], 5.4)
        self.assertEqual(observations['os_ready']['reported_linux_uptime_s'], 3.25)
        self.assertEqual(observations['cuda_ready']['elapsed_s'], 5.6)
        self.assertEqual(observations['uart_terminal']['elapsed_s'], 6.2)
        self.assertEqual(observations['ssh_banner']['elapsed_s'], 7)

    def test_three_runs_aggregate_preserves_samples_and_missing_is_null(self):
        directories = []
        for os_time in (10, 14, 12):
            f = self.fixture()
            f.uart(os_time, 'ARK_OS_READY uptime_s=2.50 milestone=multi_user_target\n')
            f.uart(os_time + 1, 'ARK_CUDA_READY uptime_s=3.50 milestone=cuda_integer_smoke_passed\n')
            f.ssh(os_time + 2)
            directories.append(f.save())
        missing = self.fixture()
        missing.metadata['status'] = 'readiness_timeout'
        directories.append(missing.save())
        report = summary.make_report(directories)
        stats = report['aggregates']['os_ready']
        self.assertEqual([item['elapsed_s'] for item in stats['included_samples']], [10, 14, 12])
        self.assertEqual((stats['median_s'], stats['minimum_s'], stats['maximum_s']), (12, 10, 14))
        self.assertTrue(stats['minimum_three_samples_met'])
        self.assertEqual(stats['missing_count'], 1)
        self.assertIsNone(report['runs'][-1]['observations']['os_ready'])
        self.assertEqual(report['aggregates']['cuda_ready']['sample_count'], 3)

    def test_metadata_selected_reference_excludes_prior_boot(self):
        f = self.fixture()
        f.uart(5, 'ARK_OS_READY uptime_s=2.00 milestone=old\n')
        f.ssh(6)
        f.arm(10)
        f.uart(16, 'ARK_OS_READY uptime_s=3.00 milestone=current\n')
        # Old metadata readiness must not turn into current-boot SSH readiness.
        report = summary.make_report([f.save()])
        run = report['runs'][0]
        self.assertEqual(run['power_references_in_capture'], 2)
        self.assertEqual(run['observations']['os_ready']['elapsed_s'], 6)
        self.assertIsNone(run['observations']['ssh_banner'])

    def test_second_kernel_boot_cannot_supply_missing_first_boot_milestones(self):
        f = self.fixture()
        f.uart(1, '[    0.000000] Linux version 6.8-first\n')
        f.uart(5, 'ARK_OS_READY uptime_s=3.00 milestone=multi_user_target\n')
        f.uart(10, '[    0.000000] Linux version 6.8-second\n')
        f.uart(13, 'ARK_CUDA_READY uptime_s=2.00 milestone=cuda_integer_smoke_passed\n')
        f.ssh(14)
        report = summary.make_report([f.save()])
        run = report['runs'][0]
        self.assertFalse(run['eligible_for_aggregate'])
        self.assertIn('multiple_kernel_boots_in_reference_window', run['issues'])
        self.assertEqual(run['observations']['os_ready']['elapsed_s'], 5)
        self.assertIsNone(run['observations']['cuda_ready'])
        self.assertIsNone(run['observations']['ssh_banner'])
        self.assertIsNone(report['aggregates']['os_ready']['median_s'])

    def test_capture_only_reference_is_not_power_boot_time(self):
        f = self.fixture()
        f.events = []
        f.arm(0, 'capture_start_boot_edge_unknown')
        f.uart(5, 'ARK_OS_READY uptime_s=999\n')
        run = summary.make_report([f.save()])['runs'][0]
        self.assertFalse(run['eligible_for_aggregate'])
        self.assertIn('no_scpi_power_reference', run['issues'])
        self.assertIsNone(run['observations']['os_ready'])

    def test_metadata_ssh_fallback_and_tcp_are_distinct(self):
        f = self.fixture()
        f.metadata['readiness']['ssh_banner'] = {'monotonic_ns': BASE + 8_000_000_000}
        run = summary.make_report([f.save()])['runs'][0]
        self.assertEqual(run['observations']['ssh_banner']['elapsed_s'], 8)
        self.assertEqual(run['observations']['ssh_banner']['source'], 'metadata_ssh_banner')
        f.metadata['network_readiness_kind'] = 'tcp'
        f.metadata['readiness'] = {'tcp': {'monotonic_ns': BASE + 8_000_000_000}}
        f.event('tcp_ready', 8)
        run = summary.make_report([f.save()])['runs'][0]
        self.assertIsNone(run['observations']['ssh_banner'])

    def test_conflicting_ssh_timestamps_are_not_published_as_ready(self):
        f = self.fixture()
        f.ssh(8)
        f.metadata['readiness']['ssh_banner']['monotonic_ns'] += 1
        run = summary.make_report([f.save()])['runs'][0]
        self.assertIsNone(run['observations']['ssh_banner'])
        self.assertIn('ssh_timestamp_metadata_mismatch', run['issues'])
        self.assertFalse(run['eligible_for_aggregate'])

    def test_faults_excluded_but_observed_samples_retained(self):
        f = self.fixture()
        f.uart(5, 'ARK_OS_READY uptime_s=3\n')
        f.metadata['status'] = 'supply_fault'
        f.metadata['final_supply']['ocp_tripped'] = True
        report = summary.make_report([f.save()])
        self.assertEqual(report['runs'][0]['observations']['os_ready']['elapsed_s'], 5)
        self.assertFalse(report['runs'][0]['eligible_for_aggregate'])
        self.assertEqual(report['aggregates']['os_ready']['excluded_run_count'], 1)
        self.assertEqual(report['aggregates']['os_ready']['sample_count'], 0)

    def test_sanitized_report_omits_paths_identities_addresses_and_regex(self):
        f = self.fixture()
        f.uart(4, 'serial=FIXTURE_SERIAL_SECRET MAC=aa:bb:cc:dd:ee:ff\nroot@PRIVATE_HOST:~# ')
        report = summary.make_report([f.save()], 'shell', r'root@PRIVATE_HOST:~# ')
        text = json.dumps(report)
        for secret in ('FIXTURE_SERIAL_SECRET', '192.0.2.55', 'aa:bb:cc:dd:ee:ff',
                       'PRIVATE_HOST', str(self.root), '/private/adapter'):
            self.assertNotIn(secret, text)
        self.assertEqual(report['runs'][0]['observations']['uart_terminal']['elapsed_s'], 4)
        self.assertIn('no command execution', report['definitions']['uart_terminal'])

    def test_shell_requires_explicit_nonempty_pattern(self):
        for kind, pattern in (('shell', None), ('none', 'x'), ('login', '')):
            with self.subTest(kind=kind, pattern=pattern), self.assertRaises(ValueError):
                summary.make_report([], kind, pattern)

    def test_malformed_uart_and_nonfinite_json_fail_closed(self):
        f = self.fixture()
        f.uart(5, 'ARK_OS_READY uptime_s=3\n')
        f.events[-1]['data_base64'] = 'invalid==!'
        run = summary.make_report([f.save()])['runs'][0]
        self.assertIn('invalid_uart_base64', run['issues'])
        self.assertFalse(run['eligible_for_aggregate'])
        (f.directory / 'metadata.json').write_text('{"schema_version":1,"value":NaN}')
        run = summary.make_report([f.directory])['runs'][0]
        self.assertIn('invalid_json_number', run['issues'])
        self.assertFalse(run['eligible_for_aggregate'])

    def test_ambiguous_or_conflicting_power_reference_rejected(self):
        f = self.fixture()
        f.arm(10)
        f.metadata.pop('reference_monotonic_ns')
        run = summary.make_report([f.save()])['runs'][0]
        self.assertIn('ambiguous_power_reference', run['issues'])
        f.metadata['reference_monotonic_ns'] = BASE + 12
        run = summary.make_report([f.save()])['runs'][0]
        self.assertIn('reference_metadata_mismatch', run['issues'])

    def test_cli_refuses_to_overwrite_sanitized_report(self):
        f = self.fixture()
        output = self.root / 'summary.json'
        command = [sys.executable, str(SCRIPT), str(f.save()), '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = output.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
