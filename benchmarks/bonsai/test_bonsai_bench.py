#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline protocol tests; starts only a synthetic HTTP server on host loopback."""
from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bonsai_bench', ROOT / 'bonsai_bench.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def event(item):
    return ('data: ' + json.dumps(item) + '\r\n\r\n').encode()


def answer_events(text='391', done=True, reasoning='', reason='stop'):
    chunks = [b': keepalive\r\n\r\n', event({'choices': [{'index': 0, 'delta': {'role': 'assistant'}}]})]
    if reasoning:
        chunks.append(event({'choices': [{'index': 0, 'delta': {'reasoning_content': reasoning}}]}))
    for content in (text[:2], text[2:]):
        chunks.append(event({'choices': [{'index': 0, 'delta': {'content': content}}]}))
    chunks.append(event({'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}]}))
    chunks.append(event({'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 3},
                         'timings': {'prompt_n': 12, 'prompt_ms': 10.0, 'predicted_n': 3,
                                     'predicted_ms': 30.0, 'predicted_per_second': 100.0}}))
    if done:
        chunks.append(b'data: [DONE]\r\n\r\n')
    return chunks


@contextmanager
def mock_server(chunks=None, heartbeat=False):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            data = {'/health': {'status': 'ok'},
                    '/v1/models': {'data': [{'id': 'bonsai-fixture'}]},
                    '/props': {'default_generation_settings': {'n_ctx': 4096}}}
            encoded = json.dumps(data[self.path]).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append(body)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                if heartbeat:
                    for _ in range(100):
                        self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                        time.sleep(0.02)
                    return
                if chunks is not None:
                    response = chunks
                else:
                    prompt = body['messages'][-1]['content']
                    if isinstance(prompt, list):
                        text = '{"code":"JAJ27","circle_count":3,"circle_color":"red"}'
                    elif '17 multiplied' in prompt:
                        text = '391'
                    elif 'JAJ-READY' in prompt:
                        text = 'JAJ-READY'
                    elif 'one valid JSON object' in prompt:
                        text = '{"device":"JAJ","sum":42,"ready":true}'
                    else:
                        text = 'A camera captures the scene. A neural network finds objects. A motor controller moves the robot.'
                    response = answer_events(text)
                for chunk in response:
                    # Fragment HTTP writes independently of SSE/event boundaries.
                    split = max(1, len(chunk) // 2)
                    self.wfile.write(chunk[:split])
                    self.wfile.flush()
                    self.wfile.write(chunk[split:])
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address, received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ProtocolTests(unittest.TestCase):
    def run_request(self, chunks=None, heartbeat=False, timeout=2):
        with tempfile.TemporaryDirectory() as temp, mock_server(chunks, heartbeat) as (address, received):
            path = Path(temp) / 'events.jsonl'
            result = bench.chat_request(address, {'messages': [{'content': '17 multiplied'}]}, timeout, path)
            logs = [bench.strict_json(line) for line in path.read_text().splitlines()]
            return result, logs

    def test_complete_stream_preserves_usage_and_server_timings(self):
        result, logs = self.run_request(answer_events())
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['content'], '391')
        self.assertEqual(result['finish_reasons'], ['stop'])
        self.assertEqual(result['usage']['completion_tokens'], 3)
        self.assertEqual(result['server_timings']['predicted_per_second'], 100)
        self.assertGreater(result['ttft_content_s'], 0)
        self.assertLessEqual(result['first_event_s'], result['ttft_content_s'])
        self.assertLessEqual(result['ttft_content_s'], result['wall_s'])
        self.assertTrue(logs[-1]['done'])
        self.assertNotEqual(result['events'], result['usage']['completion_tokens'])

    def test_incomplete_stream_fails_even_with_finish_reason(self):
        result, _ = self.run_request(answer_events(done=False))
        self.assertEqual(result['status'], 'error')
        self.assertIn('without [DONE]', result['error'])

    def test_reasoning_has_separate_latency_and_fails_thinking_off_check(self):
        result, _ = self.run_request(answer_events(reasoning='Compute carefully.'))
        self.assertLess(result['ttft_generated_s'], result['ttft_content_s'])
        self.assertFalse(bench.validate({'kind': 'exact', 'expected': '391'}, result))

    def test_absolute_deadline_bounds_keepalive_stream(self):
        result, _ = self.run_request(heartbeat=True, timeout=0.15)
        self.assertEqual(result['status'], 'error')
        self.assertIn('deadline', result['error'])
        self.assertLess(result['wall_s'], 1)

    def test_wrong_structural_types_record_protocol_error(self):
        for item in ({'choices': None}, {'choices': [None]},
                     {'choices': [{'delta': None}]},
                     {'choices': [{'delta': {'content': 0}}]},
                     {'choices': [{'delta': {}, 'finish_reason': 123}]}):
            with self.subTest(item=item):
                result, _ = self.run_request([event(item)])
                self.assertEqual(result['status'], 'error')
                self.assertIn('ValueError', result['error'])

    def test_invalid_nan_in_stream_fails(self):
        result, _ = self.run_request([b'data: {"timings":{"prompt_ms":NaN}}\n\n'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('Non-JSON', result['error'])

    def test_tool_calls_rejected_not_executed(self):
        result, _ = self.run_request([event({'choices': [{'delta': {'tool_calls': [{'name': 'anything'}]}}]})])
        self.assertEqual(result['status'], 'error')
        self.assertIn('no tools are executed', result['error'])

    def test_multiline_and_truncated_sse(self):
        self.assertEqual(list(bench.sse_events(io.BytesIO(b':x\n\ndata: {\ndata: "x": 1}\n\n'))), ['{\n"x": 1}'])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            list(bench.sse_events(io.BytesIO(b'data: {"x":1}\n')))

    def test_strict_json_rejects_duplicates_nonfinite_and_wrong_types(self):
        for text in ('{"x":1,"x":1}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                bench.strict_json(text)
        base = {'status': 'ok', 'done_received': True, 'finish_reasons': ['stop'], 'reasoning_content': ''}
        case = {'kind': 'json', 'expected': {'n': 1}}
        for text in ('{"n":true}', '{"n":1.0}', '```json\n{"n":1}\n```', '{"n":1,"extra":0}'):
            self.assertFalse(bench.validate(case, {**base, 'content': text}))
        self.assertTrue(bench.validate(case, {**base, 'content': ' {"n":1}\n'}))
        self.assertFalse(bench.validate(case, {**base, 'finish_reasons': ['length'], 'content': '{"n":1}'}))

    def test_only_loopback_no_credentials_or_nonlocal_paths(self):
        self.assertEqual(bench.endpoint('http://localhost:8081/v1'), ('127.0.0.1', 8081))
        for url in ('https://127.0.0.1:8081', 'http://192.168.55.1:8081',
                    'http://user:pass@127.0.0.1:8081', 'http://127.0.0.1:8081/other'):
            with self.assertRaises(ValueError):
                bench.endpoint(url)

    def test_image_manifest_rejects_changed_card(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'card.png'
            image.write_bytes((ROOT / 'vision-card.png').read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'manifest hash'):
                bench.make_cases('vision', 3, image, ROOT / 'vision-card.json')

    def test_cli_all_seven_requests_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp, mock_server() as (address, received):
            output = Path(temp) / 'results'
            process = subprocess.run([sys.executable, str(ROOT / 'bonsai_bench.py'),
                                      '--base-url', f'http://127.0.0.1:{address[1]}',
                                      '--output-dir', str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = bench.strict_json((output / 'summary.json').read_bytes())
            self.assertTrue(report['all_selected_checks_passed'])
            self.assertEqual(len(received), 7)
            self.assertEqual(report['benchmark_summary']['successful_repeats'], 3)
            for body in received:
                self.assertEqual(body['chat_template_kwargs'], {'enable_thinking': False})
                self.assertFalse(body['cache_prompt'])
                self.assertEqual(body['max_tokens'], 128)
                self.assertTrue(body['stream_options']['include_usage'])
            image_url = received[-1]['messages'][-1]['content'][1]['image_url']['url']
            self.assertTrue(image_url.startswith('data:image/png;base64,iVBORw0KGgo'))
            process = subprocess.run([sys.executable, str(ROOT / 'bonsai_bench.py'),
                                      '--output-dir', str(output)], capture_output=True, text=True, timeout=3)
            self.assertEqual(process.returncode, 2)
            self.assertIn('File exists', process.stderr)


if __name__ == '__main__':
    unittest.main()
