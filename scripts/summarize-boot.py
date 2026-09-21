#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Sanitize and aggregate measure-boot.py captures without accessing hardware.

Each input directory contains metadata.json and timeline.jsonl. Only an explicit
SCPI command-send reference is accepted; it is not a measured electrical edge.
Directory names, fixture identities, network addresses, UART text and private
configuration are never copied to the output. Input order supplies run indices.
"""
import argparse
import base64
import bisect
import codecs
import json
import math
from pathlib import Path
import re
import statistics

REFERENCE = 'scpi_power_on_command_send'
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_UART_BYTES = 32 * 1024 * 1024
STATUSES = {'ready', 'capture_complete', 'readiness_timeout', 'error', 'interrupted', 'supply_fault'}
GOOD_STATUSES = {'ready', 'capture_complete', 'readiness_timeout'}
MARKERS = {
    'os_ready': re.compile(r'(?<![A-Za-z0-9_])ARK_OS_READY[ \t]+uptime_s=([0-9]+(?:\.[0-9]+)?)[ \t\r\n]'),
    'cuda_ready': re.compile(r'(?<![A-Za-z0-9_])ARK_CUDA_READY[ \t]+uptime_s=([0-9]+(?:\.[0-9]+)?)[ \t\r\n]'),
}
# Use one kernel banner, not every line bearing [0.000000]. A second banner
# prevents accidentally combining OS readiness from one boot with SSH from another.
KERNEL_BANNER = re.compile(r'(?:^|[\r\n])(?:\[[ \t]*0(?:\.0+)?\][ \t]*)?Linux version[ \t]')
DEFAULT_LOGIN = r'(?:^|[\r\n])(?:[A-Za-z0-9_.-]+[ \t]+)?login:[ \t]*'


class InputError(ValueError):
    """Its code is safe to publish: never embed untrusted input or a path."""


def strict_json(data):
    def reject_constant(value):
        raise InputError('invalid_json_number')
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError('duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InputError('invalid_json') from error


def timestamp(value):
    if type(value) is not int or value < 0:
        raise InputError('invalid_monotonic_timestamp')
    return value


def optional_number(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    if value < 0 or (positive and value <= 0):
        return None
    return value


def read_inputs(directory):
    try:
        metadata_path = directory / 'metadata.json'
        timeline_path = directory / 'timeline.jsonl'
        if metadata_path.stat().st_size > MAX_INPUT_BYTES or timeline_path.stat().st_size > MAX_INPUT_BYTES:
            raise InputError('input_too_large')
        metadata = strict_json(metadata_path.read_bytes())
        if not isinstance(metadata, dict):
            raise InputError('metadata_not_object')
        if type(metadata.get('schema_version')) is not int or metadata['schema_version'] != 1:
            raise InputError('unsupported_metadata_schema')
        events = []
        with timeline_path.open('rb') as stream:
            for line in stream:
                if not line.strip():
                    continue
                event = strict_json(line)
                if not isinstance(event, dict) or not isinstance(event.get('event'), str):
                    raise InputError('invalid_timeline_record')
                timestamp(event.get('monotonic_ns'))
                events.append(event)
    except OSError as error:
        raise InputError('input_missing_or_unreadable') from error
    return metadata, sorted(events, key=lambda event: event['monotonic_ns'])


def reference_window(metadata, events):
    references = [event for event in events if event['event'] == 'reference_started']
    power = [event for event in references if event.get('label') == REFERENCE]
    if not power:
        raise InputError('no_scpi_power_reference')
    expected = metadata.get('reference_monotonic_ns')
    if expected is not None:
        timestamp(expected)
        matches = [event for event in power if event['monotonic_ns'] == expected]
        if len(matches) != 1 or metadata.get('reference_label') != REFERENCE:
            raise InputError('reference_metadata_mismatch')
        selected = matches[0]
    elif len(power) == 1:
        selected = power[0]
    else:
        raise InputError('ambiguous_power_reference')
    if selected.get('electrical_edge_measured') is not False:
        raise InputError('unexpected_reference_definition')
    start = selected['monotonic_ns']
    later = [event['monotonic_ns'] for event in references if event['monotonic_ns'] > start]
    end = min(later) if later else None
    return start, end, len(power)


def uart_text(events):
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    chunks, ends, times = [], [], []
    characters = byte_count = 0
    expected_offset = None
    for event in events:
        if event['event'] != 'uart_received':
            continue
        try:
            if not isinstance(event.get('data_base64'), str):
                raise InputError('missing_uart_base64')
            data = base64.b64decode(event['data_base64'], validate=True)
        except ValueError as error:
            if isinstance(error, InputError):
                raise
            raise InputError('invalid_uart_base64') from error
        offset = event.get('raw_offset')
        if type(offset) is not int or offset < 0 or type(event.get('length')) is not int or event['length'] != len(data):
            raise InputError('invalid_uart_span')
        if expected_offset is not None and offset != expected_offset:
            raise InputError('uart_capture_gap')
        expected_offset = offset + len(data)
        byte_count += len(data)
        if byte_count > MAX_UART_BYTES:
            raise InputError('uart_input_too_large')
        text = decoder.decode(data)
        if text:
            chunks.append(text)
            characters += len(text)
            ends.append(characters)
            times.append(event['monotonic_ns'])
    return ''.join(chunks), ends, times


def character_timestamp(position, ends, times):
    return times[bisect.bisect_right(ends, position)]


def observation(timestamp_ns, reference_ns, source, linux_uptime=None):
    result = {'elapsed_s': (timestamp_ns - reference_ns) / 1e9, 'source': source}
    if linux_uptime is not None:
        result['reported_linux_uptime_s'] = linux_uptime
    return result


def carrier_observations(metadata, all_events, reference, end):
    """Allowlist only carrier times/states; never copy host interface identity."""
    info = metadata.get('carrier_observer')
    if not isinstance(info, dict):
        raise InputError('missing_carrier_observer_metadata')
    baseline = timestamp(info.get('baseline_monotonic_ns'))
    prior_refs = [e['monotonic_ns'] for e in all_events if e['event'] == 'reference_started'
                  and e['monotonic_ns'] < reference]
    matches = [e for e in all_events if e['event'] == 'carrier_down_baseline'
               and e['monotonic_ns'] == baseline and type(e.get('carrier')) is int
               and e['carrier'] == 0 and e.get('administratively_up') is True
               and e.get('supply_output_off_verified') is True]
    if len(matches) != 1 or baseline > reference or (prior_refs and baseline <= max(prior_refs)):
        raise InputError('invalid_carrier_down_baseline')
    events = [e for e in all_events if e['monotonic_ns'] >= reference
              and (end is None or e['monotonic_ns'] < end)]
    transitions = []
    state = 0
    for event in events:
        if event['event'] != 'carrier_transition':
            continue
        current = event.get('carrier')
        if type(current) is not int or current not in (0, 1) or current == state:
            raise InputError('invalid_carrier_transition')
        state = current
        transitions.append({'elapsed_s': (event['monotonic_ns'] - reference) / 1e9,
                            'carrier': current})
    ready = [e for e in events if e['event'] == 'carrier_ready']
    readiness = metadata.get('readiness', {})
    if not isinstance(readiness, dict):
        raise InputError('carrier_readiness_metadata_mismatch')
    metadata_ready = readiness.get('carrier')
    first = None
    if ready or metadata_ready is not None:
        if len(ready) != 1 or not isinstance(metadata_ready, dict):
            raise InputError('carrier_readiness_metadata_mismatch')
        when = ready[0]['monotonic_ns']
        if timestamp(metadata_ready.get('monotonic_ns')) != when:
            raise InputError('carrier_readiness_metadata_mismatch')
        first_up = next((e['monotonic_ns'] for e in events
                         if e['event'] == 'carrier_transition' and e.get('carrier') == 1), None)
        if first_up != when:
            raise InputError('carrier_readiness_transition_mismatch')
        first = observation(when, reference, 'host_sysfs_carrier_read')
    last_sample = timestamp(info.get('last_sample_monotonic_ns'))
    if last_sample < reference or (end is not None and last_sample >= end):
        raise InputError('carrier_final_sample_outside_reference_window')
    if type(info.get('last_carrier')) is not int or info['last_carrier'] != state:
        raise InputError('carrier_final_state_mismatch')
    finished = [e for e in events if e['event'] == 'carrier_monitor_finished']
    if len(finished) != 1 or type(finished[0].get('carrier')) is not int or finished[0].get('carrier') != state or finished[0].get('last_sample_monotonic_ns') != last_sample:
        raise InputError('carrier_final_state_mismatch')
    if any(e['monotonic_ns'] > last_sample for e in events if e['event'] == 'carrier_transition'):
        raise InputError('carrier_final_state_mismatch')
    interval = optional_number(info.get('poll_interval_s'), positive=True)
    if interval != 0.020:
        raise InputError('unexpected_carrier_poll_interval')
    count = info.get('post_reference_sample_count')
    gap = optional_number(info.get('max_completion_gap_s'))
    read_duration = optional_number(info.get('max_read_duration_s'))
    span = (last_sample - reference) / 1e9
    if type(count) is not int or count < max(1, len(transitions)) or gap is None or read_duration is None:
        raise InputError('invalid_carrier_sampling_statistics')
    if gap > span or gap * count + 1e-9 < span or read_duration > gap + 1e-9:
        raise InputError('invalid_carrier_sampling_statistics')
    ups = [item['elapsed_s'] for item in transitions if item['carrier'] == 1]
    drops = sum(item['carrier'] == 0 and item['elapsed_s'] >= first['elapsed_s']
                for item in transitions) if first is not None else 0
    return first, {'down_baseline_verified': True, 'poll_interval_s': interval,
                   'post_reference_sample_count': count, 'max_completion_gap_s': gap,
                   'max_read_duration_s': read_duration,
                   'transitions': transitions, 'final_observed_carrier': state,
                   'final_observation_elapsed_s': (last_sample - reference) / 1e9,
                   'last_up_elapsed_s': ups[-1] if ups else None,
                   'down_transitions_after_first_up': drops,
                   'stable_after_first_up': bool(first is not None and state == 1 and drops == 0)}


def summarize_run(directory, index, terminal_pattern=None):
    result = {'run_index': index, 'capture_status': 'unavailable', 'eligible_for_aggregate': False,
              'issues': [], 'observations': {'os_ready': None, 'cuda_ready': None,
                                            'uart_terminal': None, 'ssh_banner': None}}
    try:
        metadata, all_events = read_inputs(directory)
        status = metadata.get('status')
        if not isinstance(status, str):
            status = 'unrecognized'
        result['capture_status'] = status if status in STATUSES else 'unrecognized'
        if status not in GOOD_STATUSES:
            result['issues'].append('capture_not_completed_cleanly')
        reference, end, reference_count = reference_window(metadata, all_events)
        result['power_references_in_capture'] = reference_count
        events = [event for event in all_events if event['monotonic_ns'] >= reference
                  and (end is None or event['monotonic_ns'] < end)]
        if any(event['event'] == 'error' for event in events):
            result['issues'].append('capture_error_event')
        final_supply = metadata.get('final_supply')
        if isinstance(final_supply, dict) and (final_supply.get('ocp_tripped') is True
                or final_supply.get('ovp_tripped') is True or final_supply.get('output') == 'OFF'):
            result['issues'].append('supply_fault')
        config = metadata.get('configuration')
        if isinstance(config, dict):
            result['probe_poll_interval_s'] = optional_number(config.get('poll_interval'), positive=True)
            result['requested_capture_duration_s'] = optional_number(config.get('duration'), positive=True)
        text, ends, times = uart_text(events)
        banners = list(KERNEL_BANNER.finditer(text))
        result['kernel_boot_banners_observed'] = len(banners)
        if len(banners) > 1:
            second = banners[1]
            end = character_timestamp(second.start(), ends, times)
            text = text[:second.start()]
            result['issues'].append('multiple_kernel_boots_in_reference_window')
        for name, pattern in MARKERS.items():
            match = pattern.search(text)
            if match:
                uptime = optional_number(float(match.group(1)))
                if uptime is None:
                    raise InputError('invalid_marker_uptime')
                observed = character_timestamp(match.end() - 1, ends, times)
                result['observations'][name] = observation(observed, reference, 'uart_chunk_receive', uptime)
        if terminal_pattern is not None:
            match = terminal_pattern.search(text)
            if match:
                if match.end() == match.start():
                    raise InputError('empty_terminal_match')
                observed = character_timestamp(match.end() - 1, ends, times)
                result['observations']['uart_terminal'] = observation(observed, reference, 'uart_chunk_receive')
        network_kind = metadata.get('network_readiness_kind')
        ssh_events = [event['monotonic_ns'] for event in events
                      if event['event'] == 'ssh_banner_ready' and (end is None or event['monotonic_ns'] < end)]
        readiness = metadata.get('readiness', {})
        ssh_metadata = readiness.get('ssh_banner') if isinstance(readiness, dict) else None
        metadata_time = None
        if isinstance(ssh_metadata, dict):
            candidate = timestamp(ssh_metadata.get('monotonic_ns'))
            if candidate >= reference and (end is None or candidate < end):
                metadata_time = candidate
        if network_kind not in (None, 'ssh_banner') and (ssh_events or metadata_time is not None):
            result['issues'].append('ssh_probe_definition_conflict')
        elif ssh_events:
            candidate = min(ssh_events)
            if metadata_time is not None and metadata_time != candidate:
                result['issues'].append('ssh_timestamp_metadata_mismatch')
            else:
                result['observations']['ssh_banner'] = observation(candidate, reference, 'timeline_ssh_banner')
        elif metadata_time is not None and network_kind == 'ssh_banner':
            result['observations']['ssh_banner'] = observation(metadata_time, reference, 'metadata_ssh_banner')
        carrier_requested = isinstance(config, dict) and bool(config.get('carrier_interface'))
        if carrier_requested or 'carrier_observer' in metadata:
            result['observations']['carrier'] = None
            first, details = carrier_observations(metadata, all_events, reference, end)
            result['observations']['carrier'] = first
            result['carrier'] = details
        result['eligible_for_aggregate'] = not result['issues']
    except InputError as error:
        result['issues'].append(str(error))
    return result


def aggregate(runs, terminal_kind):
    metrics = ['os_ready', 'cuda_ready', 'ssh_banner']
    if any('carrier' in run['observations'] for run in runs):
        metrics.append('carrier')
    if terminal_kind != 'none':
        metrics.append('uart_terminal')
    result = {}
    for metric in metrics:
        included = [{'run_index': run['run_index'], 'elapsed_s': run['observations'][metric]['elapsed_s']}
                    for run in runs if run['eligible_for_aggregate'] and run['observations'].get(metric) is not None]
        samples = [item['elapsed_s'] for item in included]
        result[metric] = {
            'included_samples': included, 'sample_count': len(samples),
            'minimum_three_samples_met': len(samples) >= 3,
            'missing_count': sum(run['eligible_for_aggregate'] and run['observations'].get(metric) is None for run in runs),
            'excluded_run_count': sum(not run['eligible_for_aggregate'] for run in runs),
            'median_s': statistics.median(samples) if samples else None,
            'minimum_s': min(samples) if samples else None,
            'maximum_s': max(samples) if samples else None,
        }
    return result


def make_report(directories, terminal_kind='none', terminal_regex=None):
    if terminal_kind == 'none' and terminal_regex is not None:
        raise ValueError('A terminal regex requires --terminal-kind login or shell')
    if terminal_kind == 'shell' and terminal_regex is None:
        raise ValueError('Shell readiness requires an explicit --terminal-regex')
    pattern = re.compile(terminal_regex if terminal_regex is not None else DEFAULT_LOGIN) if terminal_kind != 'none' else None
    if pattern is not None and pattern.search('') is not None:
        raise ValueError('Terminal regex must not match an empty string')
    runs = [summarize_run(Path(directory), index, pattern) for index, directory in enumerate(directories, 1)]
    definitions = {
        'os_ready': 'First ARK_OS_READY with a complete numeric uptime_s after the selected reference; multi-user observer, not application readiness.',
        'cuda_ready': 'First ARK_CUDA_READY with a complete numeric uptime_s after the selected reference; a verified CUDA integer computation.',
        'ssh_banner': 'First valid SSH identification banner observed by the capture probe; authentication and an interactive session are not tested.',
        'uart_terminal': ('Not requested.' if terminal_kind == 'none' else
                          'First matching UART login prompt; authentication has not been performed.' if terminal_kind == 'login' else
                          'First UART match of the caller-supplied shell-prompt expression; no command execution is tested.'),
    }
    if any('carrier' in run['observations'] for run in runs):
        definitions['carrier'] = 'First host sysfs carrier=1 after a verified output-OFF/carrier-down baseline, with the physical host interface administratively UP. 20 ms polling plus scheduling, USB adapter/driver and read latency apply. This is not an electrical link edge, IP readiness, or completion of unspecified POST checks; later flaps and final state are reported separately. Stability means no observed later down sample; shorter flaps may be missed.'
    return {
        'schema_version': 1, 'reference': REFERENCE, 'electrical_edge_measured': False,
        'timing_note': 'Elapsed times start immediately before the host SCPI power-on command write. Command/output latency and any board POR holdoff (including an approximately 2-second holdoff) remain included; no delay is subtracted.',
        'uart_timing_note': 'UART observations use the host receive timestamp of the chunk containing the completed match, not individual wire-byte timing. Reported Linux uptime is retained separately.',
        'reboot_note': 'A repeated Linux-start banner makes the run ineligible; only first-boot UART observations are retained. Reboots with no observable banner cannot be inferred.',
        'sanitization': 'Only fixed definitions, numeric measurements and allowlisted status/issue codes are retained. Input paths, identities, addresses, raw UART and private configuration are omitted.',
        'terminal_kind': terminal_kind, 'terminal_pattern_source': 'caller' if terminal_regex is not None else 'default' if terminal_kind == 'login' else 'none',
        'definitions': definitions, 'run_count': len(runs), 'runs': runs,
        'aggregates': aggregate(runs, terminal_kind),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dirs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new sanitized JSON file; never overwrite')
    parser.add_argument('--terminal-kind', choices=('none', 'login', 'shell'), default='none')
    parser.add_argument('--terminal-regex', help='UART prompt regex; required for shell, optional for login; never copied to output')
    args = parser.parse_args()
    try:
        report = make_report(args.run_dirs, args.terminal_kind, args.terminal_regex)
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n')
    except (OSError, ValueError, re.error) as error:
        # Do not echo regexes or input paths in a publishable console result.
        parser.exit(2, 'Cannot summarize: invalid arguments, invalid regex, or output unavailable.\n')
    print(json.dumps({'run_count': report['run_count'],
                      'eligible_runs': sum(run['eligible_for_aggregate'] for run in report['runs']),
                      'sample_counts': {key: value['sample_count'] for key, value in report['aggregates'].items()}}))
    return 0 if all(run['eligible_for_aggregate'] for run in report['runs']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
