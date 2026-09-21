#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline SSH collector checks with an explicitly fake executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

COLLECTOR = Path(__file__).resolve().parents[3] / 'scripts/bench-target.py'
FAKE_SSH = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
command=sys.argv[-1]
with Path(os.environ['FAKE_LOG']).open('a') as log:
 log.write(json.dumps(sys.argv[1:])+'\\n')
mode=os.environ.get('FAKE_MODE','ok')
if command.startswith('ark-cuda-bench'):
 print('null' if mode=='null' else '{"passed":true,"benchmark":"fake_cuda"}')
elif command.startswith('ark-cpu-bench'):
 print('{"passed":true,"benchmark":"fake_cpu"}')
elif 'boot_id' in command:
 count=sum('boot_id' in line for line in Path(os.environ['FAKE_LOG']).read_text().splitlines())
 print('second-boot' if mode=='reboot' and count>1 else 'first-boot')
elif command.endswith('.json'):
 print('{"uptime_s":12.34,"milestone":"fake_only"}')
else:
 print('fixture metadata')
'''


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ark-bench-ssh-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fake = self.root / 'ssh'
        fake.write_text(FAKE_SSH)
        fake.chmod(0o755)
        self.output = self.root / 'result'
        self.log = self.root / 'requests.jsonl'
        self.env = {**os.environ, 'PATH': str(self.root) + ':' + os.environ['PATH'], 'FAKE_LOG': str(self.log)}

    def run_collector(self, mode='ok'):
        return subprocess.run([sys.executable, str(COLLECTOR), '--target', 'root@example.invalid',
                               '--output-dir', str(self.output)], capture_output=True, text=True,
                              env={**self.env, 'FAKE_MODE': mode}, timeout=10)

    def test_fixed_commands_results_and_verified_key_options(self):
        result = self.run_collector()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.output / 'summary.json').read_text())
        self.assertTrue(report['benchmarks_passed'])
        self.assertTrue(report['same_boot'])
        requests = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(requests), 13)
        for request in requests:
            self.assertIn('StrictHostKeyChecking=yes', request)
            self.assertIn('BatchMode=yes', request)
        self.assertIn('ark-cuda-bench --repeats 3', [request[-1] for request in requests])

    def test_nonobject_json_reports_failure_without_exception(self):
        result = self.run_collector('null')
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.output / 'summary.json').read_text())
        self.assertFalse(report['benchmarks_passed'])
        self.assertIn('parse_error', report['results']['cuda'])

    def test_reboot_during_collection_invalidates_comparison(self):
        result = self.run_collector('reboot')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads((self.output / 'summary.json').read_text())['same_boot'])

    def test_existing_directory_refused_before_ssh(self):
        self.output.mkdir()
        result = self.run_collector()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
