#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collect fixed, read-only metadata and execute installed ARK benchmarks over SSH.

SSH keys and a verified known_hosts entry must already be configured. This tool
never changes power mode, clocks, services, authentication or target storage.
It records Linux uptime milestones, not power-on boot time.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time


def strict_json(text):
    def reject(value):
        raise ValueError('Non-JSON numeric value: ' + value)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(text, parse_constant=reject, object_pairs_hook=pairs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, help='USER@HOST with existing key access')
    parser.add_argument('--output-dir', required=True, type=Path, help='new directory; never overwrite')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--identity', type=Path, help='optional existing SSH private key')
    parser.add_argument('--known-hosts', type=Path, help='verified host-key file for this fixture; defaults to SSH configuration')
    parser.add_argument('--sudo', action='store_true', help='use noninteractive sudo for power/clock queries and benchmarks')
    parser.add_argument('--timeout', type=float, default=180, help='seconds allowed per remote command')
    parser.add_argument('--cpu-mib', type=int, choices=(64, 256, 1024), default=256)
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    if args.target.startswith('-') or any(c.isspace() for c in args.target) or '@' not in args.target:
        parser.error('--target must be USER@HOST, without whitespace')
    if not 1 <= args.port <= 65535 or not math.isfinite(args.timeout) or not 0 < args.timeout <= 3600:
        parser.error('invalid port or timeout (maximum 3600 seconds)')
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    except OSError as error:
        parser.error(str(error))
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5',
           '-o', 'ServerAliveCountMax=2', '-p', str(args.port)]
    if args.known_hosts:
        host_file = str(args.known_hosts.resolve())
        if any(c in host_file for c in ('\n', '\r', '$', '%')):
            parser.error('--known-hosts cannot contain line breaks or SSH expansion tokens')
        if not args.known_hosts.is_file():
            parser.error('--known-hosts must be an existing verified host-key file')
        quoted = host_file.replace('\\', '\\\\').replace('"', '\\"')
        ssh += ['-o', 'UserKnownHostsFile="' + quoted + '"']
    if args.identity:
        ssh += ['-i', str(args.identity)]
    ssh += ['--', args.target]
    prefix = 'sudo -n ' if args.sudo else ''
    commands = [
        ('boot_id_before', 'cat /proc/sys/kernel/random/boot_id', False),
        ('kernel', 'uname -r', False),
        ('os_release', 'cat /etc/os-release', False),
        ('uptime_before', 'cat /proc/uptime', False),
        ('power_mode', prefix + 'nvpmodel -q', False),
        ('clock_settings', prefix + 'jetson_clocks --show', False),
        ('os_ready', 'cat /run/ark-bench/os-ready.json', True),
        ('cuda_ready', 'cat /run/ark-bench/cuda-ready.json', True),
        ('startup_cuda_smoke', 'cat /run/ark-bench/cuda-smoke.json', True),
        ('cpu', prefix + f'ark-cpu-bench --mib {args.cpu_mib} --repeats {args.repeats}', True),
        ('cuda', prefix + f'ark-cuda-bench --repeats {args.repeats}', True),
        ('uptime_after', 'cat /proc/uptime', False),
        ('boot_id_after', 'cat /proc/sys/kernel/random/boot_id', False),
    ]
    report = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'target': args.target, 'clock': 'remote Linux uptime; no power-on timestamp', 'results': {}}
    for name, command, parse in commands:
        begin = time.monotonic()
        result = {'remote_command': command}
        try:
            completed = subprocess.run(ssh + [command], capture_output=True, timeout=args.timeout)
            stdout, stderr = completed.stdout, completed.stderr
            result['exit_status'] = completed.returncode
            if parse and completed.returncode == 0:
                try:
                    parsed = strict_json(stdout)
                    if not isinstance(parsed, dict):
                        raise ValueError('Expected one JSON object')
                    result['json'] = parsed
                except (ValueError, UnicodeError) as error:
                    result['parse_error'] = str(error)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            result['error'] = 'SSH command timed out; remote process may still be stopping'
            result['exit_status'] = 124
        except OSError as error:
            stdout, stderr = b'', b''
            result.update(exit_status=127, error=str(error))
        result['host_request_wall_s'] = time.monotonic() - begin
        (args.output_dir / (name + '.stdout.txt')).write_bytes(stdout)
        (args.output_dir / (name + '.stderr.txt')).write_bytes(stderr)
        report['results'][name] = result
        (args.output_dir / 'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        # Avoid submitting new workloads after a timed-out SSH process or a
        # failed transport; inspect/reconnect before deciding what to run next.
        if result['exit_status'] in (124, 127, 255):
            break
    results = report['results']
    before = args.output_dir / 'boot_id_before.stdout.txt'
    after = args.output_dir / 'boot_id_after.stdout.txt'
    report['same_boot'] = (before.exists() and after.exists() and bool(before.read_bytes().strip())
                           and before.read_bytes().strip() == after.read_bytes().strip())
    report['benchmarks_passed'] = (report['same_boot'] and all(
        results.get(name, {}).get('exit_status') == 0
        and results.get(name, {}).get('json', {}).get('passed') is True
        and 'parse_error' not in results.get(name, {}) for name in ('cpu', 'cuda')))
    (args.output_dir / 'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'benchmarks_passed': report['benchmarks_passed'],
                      'same_boot': report['same_boot'], 'summary': str(args.output_dir / 'summary.json')}))
    return 0 if report['benchmarks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
