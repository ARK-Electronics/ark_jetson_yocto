#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline fake-sysfs/fake-supply checks; never access an interface or instrument."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measure_boot_carrier', ROOT / 'scripts/measure-boot.py')
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)
spec = importlib.util.spec_from_file_location('summarize_boot_carrier', ROOT / 'scripts/summarize-boot.py')
summarize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summarize)
BASE = 10_000_000_000


class FakeNetdev:
    def __init__(self, root):
        self.root = root
        self.classes = root / 'class/net'
        self.device = root / 'devices/usb-test/adapter'
        self.netdev = self.device / 'net/ethTEST'
        self.classes.mkdir(parents=True)
        self.netdev.mkdir(parents=True)
        (self.classes / 'ethTEST').symlink_to(self.netdev, target_is_directory=True)
        (self.netdev / 'device').symlink_to(self.device, target_is_directory=True)
        for name, value in {'ifindex': '17', 'iflink': '17', 'type': '1', 'flags': '0x1003', 'carrier': '0'}.items():
            self.write(name, value)

    def write(self, name, value):
        (self.netdev / name).write_text(value + '\n')

    def observer(self, duration=1):
        return measure.CarrierObserver('ethTEST', duration, self.classes)


class CarrierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carrier-offline-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.net = FakeNetdev(self.root / 'sys')

    def capture(self):
        with mock.patch.object(measure.time, 'monotonic_ns', return_value=BASE - 2_000_000_000):
            capture = measure.Capture(self.root / 'capture')
        self.addCleanup(capture.close)
        return capture

    def observe_at(self, observer, capture, seconds, **kwargs):
        with mock.patch.object(measure.time, 'monotonic_ns', return_value=BASE + round(seconds * 1e9)):
            observer.observe(capture, **kwargs)

    def test_first_up_flaps_last_state_and_reference(self):
        observer = self.net.observer(duration=10)
        self.addCleanup(observer.close)
        capture = self.capture()
        self.net.write('carrier', '1')
        self.observe_at(observer, capture, -2)  # Old link before supply OFF.
        self.assertNotIn('carrier', capture.ready)
        self.net.write('carrier', '0')
        self.observe_at(observer, capture, -.1, require_down=True)
        capture.arm(summarize.REFERENCE, BASE)
        for at, state in [(1.25, 1), (2, 0), (3.5, 1)]:
            self.net.write('carrier', str(state)); self.observe_at(observer, capture, at)
        self.assertEqual(capture.ready['carrier']['reference_elapsed_s'], 1.25)
        report = observer.summary(capture)
        self.assertEqual(report['last_up_monotonic_ns'], BASE + 3_500_000_000)
        self.assertEqual(report['last_carrier'], 1)
        self.assertEqual(report['down_transitions_after_first_up'], 1)
        self.assertFalse(report['stable_after_first_up'])
        events = [json.loads(line) for line in (capture.directory / 'timeline.jsonl').read_text().splitlines()]
        self.assertEqual([e['carrier'] for e in events if e['event'] == 'carrier_transition'], [1, 0, 1, 0, 1])
        self.assertEqual(len([e for e in events if e['event'] == 'carrier_ready']), 1)

    def test_sampling_statistics_include_reference_gap_and_unchanged_samples(self):
        observer = self.net.observer(duration=10); self.addCleanup(observer.close)
        capture = self.capture()
        self.observe_at(observer, capture, -.1, require_down=True)
        capture.arm(summarize.REFERENCE, BASE)
        # read() results make read cost and scheduling gaps independent.
        samples = [(0, BASE + 10_000_000, BASE + 15_000_000),
                   (0, BASE + 31_000_000, BASE + 34_000_000),
                   (1, BASE + 85_000_000, BASE + 90_000_000)]
        with mock.patch.object(observer, 'read', side_effect=samples):
            for _ in samples: observer.observe(capture)
        info = observer.summary(capture)
        self.assertEqual(info['post_reference_sample_count'], 3)
        self.assertEqual(info['max_completion_gap_s'], .056)
        self.assertEqual(info['max_read_duration_s'], .005)
        # The first completion gap starts at the power reference, not the
        # earlier output-OFF sample; it can be the maximum by itself.
        second = self.net.observer(duration=10); self.addCleanup(second.close)
        with mock.patch.object(second, 'read', return_value=(0, BASE + 90_000_000, BASE + 100_000_000)):
            second.observe(capture)
        self.assertEqual(second.summary(capture)['max_completion_gap_s'], .1)
        self.assertEqual(second.summary(capture)['post_reference_sample_count'], 1)

    def test_stale_up_cannot_arm_down_baseline(self):
        observer = self.net.observer(); self.addCleanup(observer.close)
        self.net.write('carrier', '1')
        with self.assertRaisesRegex(RuntimeError, 'while supply is OFF'):
            observer.observe(self.capture(), require_down=True)
        self.assertIsNone(observer.baseline_ns)

    def test_absent_virtual_down_or_invalid_interface_rejected(self):
        for name, value in [('flags', '0x1002'), ('carrier', '2'), ('carrier', 'garbage'), ('type', '772'), ('iflink', '19')]:
            with self.subTest(name=name, value=value):
                old = (self.net.netdev / name).read_text()
                self.net.write(name, value)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.net.observer()
                (self.net.netdev / name).write_text(old)
        (self.net.netdev / 'device').unlink()
        with self.assertRaises(OSError): self.net.observer()
        with self.assertRaises(ValueError): measure.CarrierObserver('../ethTEST', 1, self.net.classes)
        with self.assertRaises(OSError): measure.CarrierObserver('missing', 1, self.net.classes)

    def test_disappearance_replacement_reused_index_and_device_change_fail(self):
        observer = self.net.observer(); self.addCleanup(observer.close)
        link = self.net.classes / 'ethTEST'
        link.unlink()
        with self.assertRaises(OSError): observer.read()
        replacement = self.root / 'replacement'; replacement.mkdir()
        for name in ('ifindex', 'iflink', 'type', 'flags', 'carrier'):
            (replacement / name).write_bytes((self.net.netdev / name).read_bytes())
        (replacement / 'device').symlink_to(self.net.device, target_is_directory=True)
        link.symlink_to(replacement, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'replaced'): observer.read()
        link.unlink(); link.symlink_to(self.net.netdev, target_is_directory=True)
        self.net.write('ifindex', '18')
        with self.assertRaisesRegex(RuntimeError, 'identity changed'): observer.read()
        self.net.write('ifindex', '17')
        other = self.root / 'other-device'; other.mkdir()
        (self.net.netdev / 'device').unlink(); (self.net.netdev / 'device').symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'replaced'): observer.read()

    def test_admin_down_after_initial_up_fails_worker(self):
        observer = self.net.observer(); self.addCleanup(observer.close)
        capture = self.capture(); stop = measure.threading.Event()
        self.net.write('flags', '0x1002')
        measure.carrier_worker(observer, capture, stop)
        self.assertTrue(stop.is_set())
        self.assertEqual(capture.errors[0]['source'], 'carrier_monitor')

    def test_late_final_read_cannot_fabricate_in_duration_readiness(self):
        observer = self.net.observer(duration=1); self.addCleanup(observer.close)
        capture = self.capture()
        self.observe_at(observer, capture, -.1, require_down=True)
        capture.arm(summarize.REFERENCE, BASE)
        self.net.write('carrier', '1'); self.observe_at(observer, capture, 1.01)
        self.assertNotIn('carrier', capture.ready)
        self.assertFalse(observer.summary(capture)['stable_after_first_up'])

    def test_cli_requires_power_reference_but_allows_carrier_only(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            measure.arguments(['--output-dir', 'unused', '--carrier-interface', 'ethTEST'])
        args = self.args()
        self.assertEqual(args.carrier_interface, 'ethTEST')
        old = measure.arguments(['--output-dir', 'unused', '--host', '192.0.2.10'])
        self.assertIsNone(old.carrier_interface)

    def args(self):
        return measure.arguments(['--output-dir', str(self.root / 'run'), '--rigol', '/fake/supply',
                                  '--expected-serial', 'SYNTHETIC_FIXTURE', '--channel', '1', '--power-on',
                                  '--carrier-interface', 'ethTEST', '--duration', '.06'])

    def run_fake(self, initial_carrier='0', identity='SYNTHETIC_FIXTURE', drop_after_on=False, cycle=False):
        self.net.write('carrier', initial_carrier)
        net = self.net
        commands = []
        class FakeRigol:
            def __init__(self, path, capture): self.capture = capture; self.on = cycle
            def query(self, command):
                if command == '*IDN?': return 'RIGOL TECHNOLOGIES,DP811,' + identity + ',TEST'
                if command == 'OUTP? CH1': return 'ON' if self.on else 'OFF'
                if ':ALAR?' in command: return 'NO'
                if ':STAT?' in command: return 'ON'
                if ':VAL?' in command: return '5'
                if command == 'APPL? CH1': return '25,5'
                raise AssertionError(command)
            def send(self, command, power_reference=False):
                commands.append(command)
                if command == 'OUTP CH1,OFF':
                    self.on = False
                    net.write('carrier', '0')
                if power_reference:
                    self.capture.arm(summarize.REFERENCE)
                    self.on = True
                    net.write('carrier', '1')
                    if drop_after_on: net.write('flags', '0x1002')
            def close(self): pass
        original = measure.CarrierObserver
        factory = lambda interface, duration: original(interface, duration, net.classes)
        with mock.patch.object(measure, 'Rigol', FakeRigol), mock.patch.object(measure, 'CarrierObserver', factory), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = self.args()
            if cycle:
                args.power_on = False; args.power_cycle = True; args.off_seconds = .002
            code = measure.run(args)
        metadata = json.loads((self.root / 'run/metadata.json').read_text())
        return code, metadata, commands

    def test_fake_capture_power_reference_and_sanitized_result(self):
        code, metadata, commands = self.run_fake()
        self.assertEqual(code, 0)
        self.assertEqual(commands, ['OUTP CH1,ON'])
        self.assertLessEqual(metadata['carrier_observer']['baseline_monotonic_ns'], metadata['reference_monotonic_ns'])
        report = summarize.make_report([self.root / 'run'])
        self.assertTrue(report['runs'][0]['eligible_for_aggregate'], report)
        self.assertIsNotNone(report['runs'][0]['observations']['carrier'])
        self.assertEqual(report['runs'][0]['carrier']['final_observed_carrier'], 1)
        encoded = json.dumps(report)
        for secret in ('ethTEST', 'SYNTHETIC_FIXTURE', str(self.root), '/fake/supply'):
            self.assertNotIn(secret, encoded)

    def test_stale_link_prevents_power_on_in_real_run_flow(self):
        code, metadata, commands = self.run_fake(initial_carrier='1')
        self.assertEqual(code, 1); self.assertEqual(metadata['status'], 'error')
        self.assertEqual(commands, [])
        self.assertIsNone(metadata['reference_monotonic_ns'])

    def test_wrong_supply_identity_prevents_power_actions(self):
        code, metadata, commands = self.run_fake(identity='WRONG_FIXTURE')
        self.assertEqual(code, 1); self.assertEqual(commands, [])
        self.assertNotIn('carrier_observer', metadata)

    def test_power_cycle_requires_new_down_baseline_after_off(self):
        code, metadata, commands = self.run_fake(initial_carrier='1', cycle=True)
        self.assertEqual(code, 0)
        self.assertEqual(commands, ['OUTP CH1,OFF', 'OUTP CH1,ON'])
        self.assertLessEqual(metadata['carrier_observer']['baseline_monotonic_ns'], metadata['reference_monotonic_ns'])
        report = summarize.make_report([self.root / 'run'])
        self.assertTrue(report['runs'][0]['eligible_for_aggregate'], report)

    def summary_fixture(self, transitions):
        observer = self.net.observer(duration=10); self.addCleanup(observer.close)
        capture = self.capture()
        self.observe_at(observer, capture, -.1, require_down=True)
        capture.arm(summarize.REFERENCE, BASE)
        for at, state in transitions:
            self.net.write('carrier', str(state)); self.observe_at(observer, capture, at)
        self.observe_at(observer, capture, 8)
        capture.event('carrier_monitor_finished', BASE + 8_000_000_000,
                      carrier=observer.last_state, last_sample_monotonic_ns=observer.last_sample_ns)
        metadata = {'schema_version': 1, 'status': 'ready' if observer.last_state else 'readiness_timeout',
                    'reference_label': summarize.REFERENCE, 'reference_monotonic_ns': BASE,
                    'readiness': capture.ready, 'configuration': {'carrier_interface': 'ethTEST', 'duration': 10},
                    'carrier_observer': observer.summary(capture)}
        (capture.directory / 'metadata.json').write_text(json.dumps(metadata))
        return capture.directory, metadata

    def test_summary_preserves_flaps_final_down_and_last_up(self):
        directory, metadata = self.summary_fixture([(1.25, 1), (2, 0), (3.5, 1), (4, 0)])
        report = summarize.make_report([directory])
        run = report['runs'][0]
        self.assertTrue(run['eligible_for_aggregate'], run['issues'])
        self.assertEqual(run['observations']['carrier']['elapsed_s'], 1.25)
        self.assertEqual(run['carrier']['final_observed_carrier'], 0)
        self.assertEqual(run['carrier']['last_up_elapsed_s'], 3.5)
        self.assertEqual(run['carrier']['down_transitions_after_first_up'], 2)
        self.assertEqual(run['carrier']['post_reference_sample_count'], 5)
        self.assertEqual(run['carrier']['max_completion_gap_s'], 4)
        self.assertEqual(run['carrier']['max_read_duration_s'], 0)
        self.assertFalse(run['carrier']['stable_after_first_up'])
        self.assertEqual([x['carrier'] for x in run['carrier']['transitions']], [1, 0, 1, 0])
        self.assertEqual(report['aggregates']['carrier']['included_samples'], [{'run_index': 1, 'elapsed_s': 1.25}])

    def test_summary_never_invents_missing_link(self):
        directory, _ = self.summary_fixture([])
        run = summarize.make_report([directory])['runs'][0]
        self.assertTrue(run['eligible_for_aggregate'], run['issues'])
        self.assertIsNone(run['observations']['carrier'])
        self.assertIsNone(run['carrier']['last_up_elapsed_s'])
        self.assertEqual(run['carrier']['final_observed_carrier'], 0)
        self.assertFalse(run['carrier']['stable_after_first_up'])

    def test_summary_rejects_missing_baseline_or_fabricated_final_state(self):
        directory, metadata = self.summary_fixture([(1, 1)])
        original = (directory / 'timeline.jsonl').read_text()
        events = [json.loads(line) for line in original.splitlines()]
        (directory / 'timeline.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events if e['event'] != 'carrier_down_baseline'))
        run = summarize.make_report([directory])['runs'][0]
        self.assertFalse(run['eligible_for_aggregate'])
        self.assertIn('invalid_carrier_down_baseline', run['issues'])
        (directory / 'timeline.jsonl').write_text(original)
        metadata['carrier_observer']['last_carrier'] = 0
        (directory / 'metadata.json').write_text(json.dumps(metadata))
        run = summarize.make_report([directory])['runs'][0]
        self.assertFalse(run['eligible_for_aggregate'])
        self.assertIn('carrier_final_state_mismatch', run['issues'])

    def test_summary_rejects_impossible_or_invalid_sampling_statistics(self):
        directory, metadata = self.summary_fixture([(1, 1)])
        original = metadata['carrier_observer'].copy()
        for field, value in [('post_reference_sample_count', True),
                             ('post_reference_sample_count', 0),
                             ('max_completion_gap_s', .001),
                             ('max_completion_gap_s', -1),
                             ('max_read_duration_s', 9)]:
            with self.subTest(field=field, value=value):
                metadata['carrier_observer'] = {**original, field: value}
                (directory / 'metadata.json').write_text(json.dumps(metadata))
                run = summarize.make_report([directory])['runs'][0]
                self.assertFalse(run['eligible_for_aggregate'])
                self.assertIn('invalid_carrier_sampling_statistics', run['issues'])

    def test_admin_down_during_capture_is_error_even_after_power_on(self):
        code, metadata, commands = self.run_fake(drop_after_on=True)
        self.assertEqual(code, 1); self.assertEqual(metadata['status'], 'error')
        self.assertEqual(commands, ['OUTP CH1,ON'])


if __name__ == '__main__': unittest.main()
