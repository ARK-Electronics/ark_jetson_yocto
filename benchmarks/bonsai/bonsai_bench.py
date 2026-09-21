#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stdlib-only Linux client for a local Prism llama-server.

Model outputs are saved and checked as strings/JSON, never executed. Every
request has an absolute wall-clock deadline. This does not start/change a server.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import signal
import statistics
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SYSTEM = 'Follow the requested output format exactly. Give only the final answer.'
BENCH_PROMPT = ('Explain in exactly three short sentences how a camera, a neural network, '
                'and a motor controller work together in an autonomous robot. '
                'Do not use headings or lists.')
MAX_BODY = 8 * 1024 * 1024
MAX_LINE = 1024 * 1024


def strict_json(data):
    def reject_constant(value):
        raise ValueError('Non-JSON numeric constant: ' + value)
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_pairs)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


@contextmanager
def deadline(seconds):
    # A socket timeout alone is an inactivity timer: a stalled server could
    # send keepalive comments forever. SIGALRM also bounds such a live stream.
    def expired(signum, frame):
        raise TimeoutError('absolute request deadline exceeded')
    previous_handler = signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] or previous_timer[1]:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/', '/v1', '/v1/')):
        raise ValueError('Use a loopback HTTP URL, optionally ending in /v1')
    # Avoid proxies and hostname resolution altogether for localhost.
    return ('127.0.0.1' if parsed.hostname == 'localhost' else parsed.hostname,
            parsed.port or 80)


def get_json(address, path, timeout=10):
    connection = http.client.HTTPConnection(*address, timeout=timeout)
    try:
        with deadline(timeout):
            connection.request('GET', path)
            response = connection.getresponse()
            payload = response.read(MAX_BODY + 1)
            if len(payload) > MAX_BODY:
                raise ValueError('oversized preflight response')
            if response.status != 200:
                raise ValueError(f'{path}: HTTP {response.status}: {payload[:500]!r}')
            return strict_json(payload)
    finally:
        connection.close()


def sse_events(response):
    """Yield complete SSE data records; tolerate comments and CRLF/multiline data."""
    lines, byte_count = [], 0
    while True:
        raw = response.readline(MAX_LINE + 1)
        if len(raw) > MAX_LINE:
            raise ValueError('oversized SSE line')
        byte_count += len(raw)
        if byte_count > MAX_BODY:
            raise ValueError('oversized SSE stream')
        if not raw:
            if lines:
                raise ValueError('truncated final SSE event')
            return
        line = raw.decode('utf-8').rstrip('\r\n')
        if line == '':
            if lines:
                yield '\n'.join(lines)
                lines = []
        elif line.startswith('data:'):
            lines.append(line[5:].removeprefix(' '))
        # Ignore SSE comments, event/id/retry fields. Error JSON is checked below.


def chat_request(address, body, timeout, event_path):
    result = {'status': 'error', 'content': '', 'reasoning_content': '',
              'finish_reasons': [], 'usage_events': [], 'timing_events': [],
              'first_event_s': None, 'ttft_generated_s': None, 'ttft_content_s': None,
              'done_received': False, 'events': 0}
    payload = json.dumps(body, allow_nan=False).encode()
    connection = http.client.HTTPConnection(*address, timeout=timeout)
    start = time.perf_counter()
    try:
        with deadline(timeout), event_path.open('x') as stream:
            connection.request('POST', '/v1/chat/completions', body=payload,
                               headers={'Content-Type': 'application/json',
                                        'Accept': 'text/event-stream'})
            response = connection.getresponse()
            result['http_status'] = response.status
            result['headers_s'] = time.perf_counter() - start
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}: {response.read(8192)!r}')
            if 'text/event-stream' not in response.getheader('Content-Type', ''):
                raise ValueError('server did not return the requested SSE content type')
            for data in sse_events(response):
                elapsed = time.perf_counter() - start
                if data == '[DONE]':
                    result['done_received'] = True
                    stream.write(json.dumps({'elapsed_s': elapsed, 'done': True}) + '\n')
                    break
                item = strict_json(data)
                if not isinstance(item, dict):
                    raise ValueError('SSE data must be a JSON object')
                stream.write(json.dumps({'elapsed_s': elapsed, 'data': item},
                                        ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
                result['events'] += 1
                if result['first_event_s'] is None:
                    result['first_event_s'] = elapsed
                if item.get('error'):
                    raise ValueError('server SSE error: ' + json.dumps(item['error']))
                for key, dest in (('usage', 'usage_events'), ('timings', 'timing_events')):
                    if item.get(key) is not None:
                        result[dest].append(item[key])
                choices = item.get('choices', [])
                if not isinstance(choices, list):
                    raise ValueError('SSE choices must be a list')
                for choice in choices:
                    if not isinstance(choice, dict):
                        raise ValueError('SSE choice must be an object')
                    if choice.get('index', 0) != 0:
                        raise ValueError('unexpected additional completion choice')
                    delta = choice.get('delta', {})
                    if not isinstance(delta, dict):
                        raise ValueError('SSE choice delta must be an object')
                    if delta.get('tool_calls'):
                        raise ValueError('unexpected tool call; no tools are executed')
                    text = delta.get('content')
                    reasoning = delta.get('reasoning_content', delta.get('reasoning'))
                    text = '' if text is None else text
                    reasoning = '' if reasoning is None else reasoning
                    if not isinstance(text, str) or not isinstance(reasoning, str):
                        raise ValueError('unexpected non-string content delta')
                    if (text or reasoning) and result['ttft_generated_s'] is None:
                        result['ttft_generated_s'] = elapsed
                    if text and result['ttft_content_s'] is None:
                        result['ttft_content_s'] = elapsed
                    result['content'] += text
                    result['reasoning_content'] += reasoning
                    reason = choice.get('finish_reason')
                    if reason is not None:
                        if not isinstance(reason, str):
                            raise ValueError('finish reason must be a string or null')
                        result['finish_reasons'].append(reason)
            if not result['done_received']:
                raise ValueError('stream ended without [DONE]')
            if not result['finish_reasons']:
                raise ValueError('stream did not include a finish reason')
            result['status'] = 'ok'
    except (OSError, ValueError, http.client.HTTPException) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        result['wall_s'] = time.perf_counter() - start
        connection.close()
    result['usage'] = result['usage_events'][-1] if result['usage_events'] else None
    result['server_timings'] = result['timing_events'][-1] if result['timing_events'] else None
    # This includes prompt processing/network overhead: it is not decode speed.
    usage = result['usage'] if isinstance(result['usage'], dict) else {}
    tokens = usage.get('completion_tokens')
    result['completion_tokens_per_wall_second'] = (
        tokens / result['wall_s'] if type(tokens) is int and tokens >= 0 else None)
    return result


def make_cases(suite, repeats, image, manifest):
    cases = []
    if suite in ('all', 'text'):
        cases += [
            {'name': 'arithmetic', 'kind': 'exact', 'expected': '391',
             'prompt': 'What is 17 multiplied by 23? Reply with only the integer.'},
            {'name': 'instruction', 'kind': 'exact', 'expected': 'JAJ-READY',
             'prompt': 'Reply with exactly JAJ-READY. No quotes, formatting, or extra words.'},
            {'name': 'json', 'kind': 'json',
             'expected': {'device': 'JAJ', 'sum': 42, 'ready': True},
             'prompt': ('Return only one valid JSON object, without markdown, with exactly '
                        'these fields: device is the string JAJ; sum is the integer result '
                        'of 20 + 22; ready is the boolean true.')},
        ]
    if suite in ('all', 'benchmark'):
        cases += [{'name': f'benchmark-{i + 1}', 'kind': 'benchmark',
                   'prompt': BENCH_PROMPT} for i in range(repeats)]
    if suite in ('all', 'vision'):
        info = strict_json(manifest.read_bytes())
        raw = image.read_bytes()
        if hashlib.sha256(raw).hexdigest() != info['sha256']:
            raise ValueError('vision PNG differs from its expected manifest hash')
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('vision stimulus is not a PNG')
        cases.append({'name': 'vision', 'kind': 'json', 'expected': info['expected'],
                      'image_sha256': info['sha256'], 'image_bytes': len(raw),
                      'prompt': [{'type': 'text', 'text': (
                          'Read the large printed code and count the filled circles in this image. '
                          'Return only valid JSON with exactly these keys: code (string), '
                          'circle_count (integer), circle_color (lowercase string).')},
                          {'type': 'image_url', 'image_url': {'url':
                           'data:image/png;base64,' + base64.b64encode(raw).decode()}}]})
    return cases


def validate(case, result):
    passed = (result['status'] == 'ok' and result['done_received']
              and result['finish_reasons'] == ['stop']
              and not result['reasoning_content'].strip())
    answer = result['content'].strip()
    if case['kind'] == 'exact':
        return passed and answer == case['expected']
    if case['kind'] == 'json':
        try:
            actual = strict_json(answer)
            return passed and json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
                case['expected'], sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            return False
    # Benchmark repetitions check complete nonempty output, not semantic quality.
    return passed and len(answer) >= 20


def request_body(model, case, max_tokens):
    return {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM},
                                       {'role': 'user', 'content': case['prompt']}],
            'temperature': 0, 'seed': 27, 'max_tokens': max_tokens,
            'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False},
            'cache_prompt': False, 'timings_per_token': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8081')
    parser.add_argument('--model', help='otherwise use the sole /v1/models entry')
    parser.add_argument('--suite', choices=('all', 'text', 'benchmark', 'vision'), default='all')
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--max-tokens', type=int, choices=(128, 256), default=128)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--image', type=Path, default=ROOT / 'vision-card.png')
    parser.add_argument('--image-manifest', type=Path, default=ROOT / 'vision-card.json')
    parser.add_argument('--output-dir', type=Path, required=True, help='new directory; will not overwrite')
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error('--timeout must be greater than zero and at most 300 seconds')
    try:
        address = endpoint(args.base_url)
        cases = make_cases(args.suite, args.repeats, args.image, args.image_manifest)
        args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    report = {'schema_version': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'base_url': args.base_url, 'suite': args.suite, 'seed': 27,
              'temperature': 0, 'enable_thinking': False, 'cache_prompt': False,
              'max_tokens': args.max_tokens, 'request_deadline_s': args.timeout,
              'expected_server_context_tokens': 4096,
              'client_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'results': []}
    try:
        report['health'] = get_json(address, '/health')
        models = get_json(address, '/v1/models')
        report['models'] = models
        if not isinstance(models, dict) or not isinstance(models.get('data'), list):
            raise ValueError('/v1/models must contain a data list')
        if any(not isinstance(item, dict) or not isinstance(item.get('id'), str)
               or not item['id'] for item in models['data']):
            raise ValueError('/v1/models entries must contain nonempty string IDs')
        ids = [item['id'] for item in models['data']]
        if args.model:
            model = args.model
            if model not in ids:
                raise ValueError('--model does not match /v1/models')
        elif len(ids) == 1:
            model = ids[0]
        else:
            raise ValueError('choose --model explicitly when the server does not expose exactly one model')
        report['model'] = model
        try:
            report['server_props'] = get_json(address, '/props')
        except (OSError, ValueError, http.client.HTTPException) as error:
            report['server_props_error'] = str(error)
        for case in cases:
            body = request_body(model, case, args.max_tokens)
            write_json(args.output_dir / (case['name'] + '.request.json'), body)
            result = chat_request(address, body, args.timeout,
                                  args.output_dir / (case['name'] + '.events.jsonl'))
            result.update({'name': case['name'], 'kind': case['kind'],
                           'expected': case.get('expected'),
                           'image_sha256': case.get('image_sha256')})
            result['passed'] = validate(case, result)
            report['results'].append(result)
            write_json(args.output_dir / (case['name'] + '.result.json'), result)
            write_json(args.output_dir / 'summary.json', report)
            print(json.dumps({key: result.get(key) for key in (
                'name', 'passed', 'status', 'ttft_content_s', 'wall_s', 'usage',
                'server_timings', 'error')}, allow_nan=False), flush=True)
            # A timed out request might still be cancelling on the server. Do
            # not submit the rest of the suite after a transport/protocol error.
            if result['status'] != 'ok':
                break
    except (OSError, ValueError, KeyError, http.client.HTTPException) as error:
        report['preflight_error'] = f'{type(error).__name__}: {error}'
    bench = [r for r in report['results'] if r['kind'] == 'benchmark' and r['passed']]
    report['benchmark_summary'] = {'successful_repeats': len(bench)}
    for metric in ('ttft_content_s', 'wall_s', 'completion_tokens_per_wall_second'):
        values = [r[metric] for r in bench if r.get(metric) is not None]
        if values:
            report['benchmark_summary'][metric] = {
                'min': min(values), 'median': statistics.median(values), 'max': max(values)}
    report['all_selected_checks_passed'] = (len(report['results']) == len(cases)
                                           and all(r['passed'] for r in report['results']))
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(args.output_dir / 'summary.json', report)
    print(json.dumps({'summary': str(args.output_dir / 'summary.json'),
                      'all_selected_checks_passed': report['all_selected_checks_passed']},
                     allow_nan=False), flush=True)
    return 0 if report['all_selected_checks_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
