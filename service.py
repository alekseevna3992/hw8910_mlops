"""Лёгкий HTTP-прототип. Только localhost, STUB ONLY."""
import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MAX_NEW_TOKENS = 32
MAX_PROMPT_CHARS = 4096


class StubBackend:
    def __init__(self, manifest):
        self.loaded_id = manifest['model_id']
        self.calls = 0
        self.runtime_sha256 = manifest['runtime_sha256']

    def generate(self, prompt, limit):
        self.calls += 1
        time.sleep(.01)
        return {'answer': f'STUB ONLY: {self.loaded_id}', 'output_tokens': 1}


class ServiceState:
    def __init__(self, root, warmup_seconds):
        self.root = Path(root)
        self.ready = False                       # НЕ готовы до прогрева
        manifest = json.loads((self.root / 'accepted.json').read_text())
        self.backend = StubBackend(manifest)
        self.warmup_finished = threading.Event()
        self.warmup_seconds = warmup_seconds
        threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self):
        time.sleep(self.warmup_seconds)
        self.warmup_finished.set()
        self.ready = True

    @staticmethod
    def _validate(payload):
        if not isinstance(payload, dict):
            raise ValueError('body должен быть JSON-объектом')
        prompt = payload.get('prompt', '')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('prompt: непустая строка обязательна')
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f'prompt: длина > {MAX_PROMPT_CHARS}')
        mnt = payload.get('max_new_tokens', 32)
        if isinstance(mnt, bool) or not isinstance(mnt, int):
            raise ValueError('max_new_tokens: ожидается int')
        if not (1 <= mnt <= MAX_NEW_TOKENS):
            raise ValueError(f'max_new_tokens: диапазон 1..{MAX_NEW_TOKENS}, got {mnt}')
        return prompt, mnt

    def generate(self, payload):
        if not self.ready:
            raise RuntimeError('not ready')            # ловим отдельно в handler
        prompt, mnt = self._validate(payload)
        started = time.perf_counter()
        result = self.backend.generate(prompt, mnt)
        # ВАЖНО: model_id/runtime_sha256 берём у ЗАГРУЖЕННОГО backend, не у диска.
        result.update(
            model_id=self.backend.loaded_id,
            runtime_sha256=self.backend.runtime_sha256,
            request_id=str(uuid.uuid4()),
            generation_seconds=time.perf_counter() - started,
        )
        result.setdefault('output_tokens', 0)
        return result


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

        def send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                self.send_json(200, {'alive': True, 'backend': 'STUB ONLY'})
            elif self.path == '/ready':
                self.send_json(200 if state.ready else 503, {'ready': state.ready})
            elif self.path == '/debug':
                self.send_json(200, {
                    'loaded_id': state.backend.loaded_id,
                    'calls': state.backend.calls,
                    'warmup_finished': state.warmup_finished.is_set(),
                    'ready': state.ready,
                })
            else:
                self.send_json(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/generate':
                self.send_json(404, {'error': 'not found'})
                return
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 65536:
                self.send_json(413, {'error': 'body size'})
                return
            if not state.ready:
                self.send_json(503, {'error': 'not ready'})
                return
            try:
                payload = json.loads(self.rfile.read(size))
                self.send_json(200, state.generate(payload))
            except RuntimeError as e:
                self.send_json(503, {'error': str(e)})
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                self.send_json(400, {'error': str(e)})
    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, default=Path('.lab'))
    p.add_argument('--port', type=int, default=8091)
    p.add_argument('--warmup-seconds', type=float, default=5)
    args = p.parse_args()
    state = ServiceState(args.workspace, args.warmup_seconds)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(state))
    print(f'STUB ONLY: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()