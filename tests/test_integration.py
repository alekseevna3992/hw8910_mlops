"""Интеграционные тесты ДЗ 8+9+10. Не заменяют tests/test_release.py."""
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _workspace(tmp_path):
    ws = tmp_path / '.lab'
    subprocess.run(
        [sys.executable, str(REPO / 'lab.py'), '--workspace', str(ws), 'init'],
        check=True, capture_output=True,
    )
    return ws


def _run(ws, *args):
    return subprocess.run(
        [sys.executable, str(REPO / 'lab.py'), '--workspace', str(ws), *args],
        capture_output=True, text=True,
    )


def _start_service(ws, port, warmup):
    proc = subprocess.Popen(
        [sys.executable, str(REPO / 'service.py'),
         '--workspace', str(ws), '--port', str(port),
         '--warmup-seconds', str(warmup)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1)
            return proc
        except Exception:
            time.sleep(0.05)
    proc.terminate()
    raise RuntimeError('service did not start')


def _get(url):
    try:
        r = urllib.request.urlopen(url, timeout=3)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    try:
        r = urllib.request.urlopen(req, timeout=3)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class HttpTests(unittest.TestCase):
    """Минимум 3 HTTP-теста."""

    def test_ready_false_before_warmup(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ws = _workspace(Path(td))
            port = _free_port()
            proc = _start_service(ws, port, warmup=3)
            try:
                status, body = _get(f'http://127.0.0.1:{port}/ready')
                self.assertEqual(status, 503, body)
                self.assertFalse(body['ready'])
                status, _ = _post(f'http://127.0.0.1:{port}/generate',
                                  {'prompt': 'hi', 'max_new_tokens': 4})
                self.assertIn(status, (503, 400))
                time.sleep(3.5)
                status, body = _get(f'http://127.0.0.1:{port}/ready')
                self.assertEqual(status, 200)
                self.assertTrue(body['ready'])
            finally:
                proc.terminate(); proc.wait(timeout=5)

    def test_invalid_request_does_not_call_backend(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ws = _workspace(Path(td))
            port = _free_port()
            proc = _start_service(ws, port, warmup=0.5)
            try:
                time.sleep(1.0)
                _, d0 = _get(f'http://127.0.0.1:{port}/debug')
                calls0 = d0['calls']
                for bad in (
                    {'prompt': '', 'max_new_tokens': 4},
                    {'prompt': 'hi', 'max_new_tokens': 0},
                    {'prompt': 'hi', 'max_new_tokens': 100000},
                    {'prompt': 'hi', 'max_new_tokens': 'many'},
                ):
                    status, _ = _post(f'http://127.0.0.1:{port}/generate', bad)
                    self.assertEqual(status, 400, bad)
                _, d1 = _get(f'http://127.0.0.1:{port}/debug')
                self.assertEqual(d1['calls'], calls0)
                status, body = _post(f'http://127.0.0.1:{port}/generate',
                                     {'prompt': 'hi', 'max_new_tokens': 4})
                self.assertEqual(status, 200)
                for k in ('answer', 'request_id', 'model_id',
                          'runtime_sha256', 'output_tokens', 'generation_seconds'):
                    self.assertIn(k, body)
                _, d2 = _get(f'http://127.0.0.1:{port}/debug')
                self.assertEqual(d2['calls'], calls0 + 1)
            finally:
                proc.terminate(); proc.wait(timeout=5)

    def test_version_reflects_loaded_not_advertised(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ws = _workspace(Path(td))
            port = _free_port()
            proc = _start_service(ws, port, warmup=0.5)
            try:
                time.sleep(1.0)
                _, body = _post(f'http://127.0.0.1:{port}/generate',
                                {'prompt': 'hi', 'max_new_tokens': 2})
                self.assertEqual(body['model_id'], 'fixture-A')
                # публикуем B из другого процесса
                r = _run(ws, 'run')
                self.assertEqual(r.returncode, 0, r.stderr)
                # старый сервис должен по-прежнему отдавать A
                _, body = _post(f'http://127.0.0.1:{port}/generate',
                                {'prompt': 'hi', 'max_new_tokens': 2})
                self.assertEqual(body['model_id'], 'fixture-A')
                _, d = _get(f'http://127.0.0.1:{port}/debug')
                self.assertEqual(d['loaded_id'], 'fixture-A')
            finally:
                proc.terminate(); proc.wait(timeout=5)
            # перезапуск — теперь B
            proc = _start_service(ws, port, warmup=0.5)
            try:
                time.sleep(1.0)
                _, body = _post(f'http://127.0.0.1:{port}/generate',
                                {'prompt': 'hi', 'max_new_tokens': 2})
                self.assertEqual(body['model_id'], 'fixture-B')
            finally:
                proc.terminate(); proc.wait(timeout=5)


class ProcessTests(unittest.TestCase):
    """Минимум 2 subprocess-теста; здесь их 5."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.ws = _workspace(Path(self._td.name))
        self.accepted = self.ws / 'accepted.json'
        self.log = self.ws / 'publications.jsonl'

    def tearDown(self):
        self._td.cleanup()

    def test_fail_after_prepare_leaves_accepted(self):
        before = self.accepted.read_bytes()
        r = _run(self.ws, 'run', '--fail-after-prepare')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.accepted.read_bytes(), before)
        r = _run(self.ws, 'run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('CACHE_HIT', r.stdout)
        self.assertEqual(json.loads(self.accepted.read_text())['model_id'], 'fixture-B')

    def test_cache_invalidated_on_data_change(self):
        r = _run(self.ws, 'run')
        self.assertIn('PREPARED', r.stdout)
        r = _run(self.ws, 'run')
        self.assertIn('CACHE_HIT', r.stdout)
        (self.ws / 'input.txt').write_text('совсем другой текст\n')
        r = _run(self.ws, 'run')
        self.assertIn('PREPARED', r.stdout)

    def test_no_duplicate_publications(self):
        for _ in range(2):
            r = _run(self.ws, 'run')
            self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in self.log.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, lines)

    def test_reject_and_incomplete_and_foreign_report(self):
        before = self.accepted.read_bytes()
        # отказ
        r = _run(self.ws, 'run', '--report', 'report-reject.json')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.accepted.read_bytes(), before)
        # неполный
        r = _run(self.ws, 'run', '--report', 'report-incomplete.json')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.accepted.read_bytes(), before)
        # чужой (A-отчёт для B)
        (self.ws / 'report-foreign.json').write_text(
            (self.ws / 'report-A.json').read_text()
        )
        r = _run(self.ws, 'run', '--report', 'report-foreign.json')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.accepted.read_bytes(), before)

    def test_crash_between_pointer_and_log_recovered(self):
        r = _run(self.ws, 'run', '--fail-after-publish')
        self.assertNotEqual(r.returncode, 0)
        # указатель уже B, но журнала ещё нет
        self.assertEqual(json.loads(self.accepted.read_text())['model_id'], 'fixture-B')
        self.assertFalse(self.log.exists() and
                         [l for l in self.log.read_text().splitlines() if l.strip()])
        # повтор восстанавливает согласованность без дубля
        r = _run(self.ws, 'run')
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in self.log.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, lines)


if __name__ == '__main__':
    unittest.main()