#!/usr/bin/env python3
"""Behavioral wire regression against a freshly built gateway (no build performed).

Run: python3 tests/embeddings_encoding.py --binary build/raiju
Uses Python's independent IEEE754/base64 oracle, not Raiju's encoder/decoder.
"""
import argparse
import base64
import contextlib
import http.server
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VECTORS = [
    [0.0, -0.0, -1.0, 0.5, 0.1, -0.25, 1 + 2**-24, 1 + 3 * 2**-24, 1e-40, 3.4028234663852886e38],
    [-2.5, 0.125, -0.1, 12.75, 2**-149, -(2**-150), 2**-126, 0.0, 1.0, -123.5],
]


def wire(vector):
    return struct.pack('<' + 'f' * len(vector), *vector)


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


class Mock(http.server.ThreadingHTTPServer):
    def __init__(self):

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def read_body(self):
                if self.headers.get('Transfer-Encoding', '').lower() != 'chunked':
                    return self.rfile.read(int(self.headers.get('Content-Length', '0')))
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b';', 1)[0], 16)
                    if size == 0:
                        while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                            pass
                        return b''.join(chunks)
                    chunks.append(self.rfile.read(size))
                    assert self.rfile.read(2) == b'\r\n'

            def answer(self, obj):
                raw = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.startswith('/api/models/'):
                    self.answer({'inferenceProviderMapping': {
                        'hf-inference': {'status': 'live', 'providerId': 'test/embedding', 'task': 'feature-extraction'},
                        'nebius': {'status': 'live', 'providerId': 'test/embedding', 'task': 'feature-extraction'},
                    }})
                else:
                    self.send_error(404)

            def do_POST(self):
                raw = self.read_body()
                body = {} if self.path == '/token' else json.loads(raw)
                if self.path == '/token':
                    self.answer({'access_token': 'mock-vertex-token', 'token_type': 'Bearer', 'expires_in': 3600})
                    return
                if self.path.endswith(':batchEmbedContents'):
                    self.answer({'embeddings': [{'values': v} for v in VECTORS]})
                elif '/publishers/google/models/' in self.path:
                    self.answer({'predictions': [{'embeddings': {'values': v, 'statistics': {'token_count': 4}}} for v in VECTORS]})
                elif self.path.endswith('/v2/embed'):
                    self.answer({'embeddings': {'float': VECTORS}, 'meta': {'billed_units': {'input_tokens': 7}}})
                elif '/model/amazon.titan-embed' in self.path:
                    vector = VECTORS[1 if body['inputText'].startswith('second') else 0]
                    self.answer({'embedding': vector, 'inputTextTokenCount': 3})
                elif '/model/cohere.embed-' in self.path:
                    self.answer({'embeddings': VECTORS})
                elif '/hf-inference/' in self.path:
                    self.answer(VECTORS)
                elif self.path.endswith('/embeddings'):
                    encoded = body.get('model') == 'upstream-base64'
                    self.answer({'object': 'list', 'model': 'openai/upstream-base64' if encoded else 'upstream-model', 'id': 'keep-response-id',
                                 'metadata': {'keep': [1, 'two']},
                                 'data': [{'object': 'embedding', 'index': (7, 2)[i], 'tag': 'keep-' + str(i),
                                           'embedding': base64.b64encode(wire(v)).decode() if encoded else v}
                                          for i, v in enumerate(VECTORS)],
                                 'usage': {'prompt_tokens': 7, 'total_tokens': 7, 'cost': 0.125, 'details': {'keep': True}}})
                else:
                    self.send_error(404)

        super().__init__(('127.0.0.1', 0), Handler)
        self.base = 'http://127.0.0.1:' + str(self.server_port)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()


@contextlib.contextmanager
def gateway(binary, mock, large, server):
    with tempfile.TemporaryDirectory(prefix='raiju-embedding-wire-') as directory:
        app = Path(directory)
        providers = {}
        for name in ('openai', 'gemini', 'cohere', 'bedrock', 'vertex', 'huggingface'):
            key = {'name': 'fixture', 'value': 'mock-key', 'models': [], 'weight': 1.0}
            providers[name] = {'keys': [key], 'network_config': {'base_url': mock.base, 'max_retries': 0, 'allow_private_network': True}}
        # Reuse the repository's non-secret RSA test fixture for Vertex's service-account grant.
        pem = re.search(r'const TEST_PKCS8 = `(.*?)`', (ROOT / 'src/jwt.tov').read_text(), re.S).group(1)
        providers['vertex']['keys'][0] = {'name': 'fixture', 'models': [], 'weight': 1.0,
            'vertex_key_config': {'project_id': 'test', 'region': 'us-central1', 'auth_credentials': json.dumps({
                'type': 'service_account', 'client_email': 'fixture@test.invalid', 'private_key': pem, 'token_uri': mock.base + '/token'})}}
        cfg = {'client': {'enable_logging': False, 'enforce_auth_on_inference': False}, 'providers': providers,
               'pricing_sync': {'enabled': False}}
        if large:
            cfg['large_payload_optimization'] = {'enabled': True, 'request_threshold_bytes': 1024,
                'response_threshold_bytes': 32, 'prefetch_size_bytes': 256, 'max_payload_bytes': 1048576, 'truncated_log_bytes': 128}
        config = app / 'config.json'
        config.write_text(json.dumps(cfg))
        base = 'http://127.0.0.1:' + str(port())
        env = {k: v for k, v in os.environ.items() if k not in ('APP_DIR', 'PORT', 'RAIJU_CONFIG', 'RAIJU_HOST')}
        env.update(RAIJU_SETUP_TOKEN='mock-embedding-setup', RAIJU_HF_HUB_URL=mock.base)
        with (app / 'gateway.log').open('w+') as log:
            proc = subprocess.Popen([str(Path(binary).resolve()), '-host', '127.0.0.1', '-port', base.rsplit(':', 1)[1],
                                     '-config', str(config), '-app-dir', directory, '-workers', '1', '-server', server],
                                    cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(200):
                    try:
                        with urllib.request.urlopen(base + '/health', timeout=1):
                            pass
                        break
                    except (urllib.error.URLError, OSError):
                        if proc.poll() is not None:
                            raise RuntimeError('gateway exited during startup')
                        time.sleep(0.05)
                else:
                    raise RuntimeError('gateway never became healthy')
                yield base
            except BaseException:
                log.flush()
                print((app / 'gateway.log').read_text()[-12000:])
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def assert_vectors(response, encoded, indexes=(0, 1)):
    assert response['object'] == 'list', response
    assert len(response['data']) == len(VECTORS), response
    for i, (entry, vector) in enumerate(zip(response['data'], VECTORS)):
        assert entry['index'] == indexes[i] and entry['object'] == 'embedding', entry
        value = entry['embedding']
        if encoded:
            assert isinstance(value, str), ('SDK requires a base64 string', value)
            raw = base64.b64decode(value, validate=True)
            assert raw == wire(vector), (i, raw.hex(), wire(vector).hex())
            # Same float32 decoding the installed SDK performs; catches dimensions, order and actual values.
            decoded = struct.unpack('<' + 'f' * (len(raw) // 4), raw)
            assert len(decoded) == len(vector) and decoded == struct.unpack('<' + 'f' * len(vector), wire(vector))
        else:
            assert isinstance(value, list) and value == vector, (i, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default='build/raiju')
    parser.add_argument('--server', default=os.environ.get('RAIJU_SERVER', 'bun'), choices=('bun', 'http1'))
    args = parser.parse_args()
    mock = Mock()
    try:
        for large in (False, True):
            with gateway(args.binary, mock, large, args.server) as base:
                cases = [('gemini/embedding', 0), ('cohere/embedding', 7),
                         ('vertex/embedding', 8), ('bedrock/amazon.titan-embed-text-v2:0', 6),
                         ('bedrock/cohere.embed-english-v3', 0), ('huggingface/hf-inference/test/embedding', 0)]
                # OpenAI-format upstreams honor base64 on their own; their already-encoded answer is retained.
                cases += [('openai/upstream-base64', 7), ('huggingface/nebius/test/embedding', 7)]
                if not large:
                    cases += [('openai/numeric', 7)]
                for model, tokens in cases:
                    formats = ('base64',) if model.endswith('upstream-base64') else (None, 'float', 'base64')
                    for encoding in formats:
                        orders = (False, True) if large and encoding == 'base64' else (False,)
                        for path, early in [(p, e) for p in ('/v1/embeddings', '/openai/v1/embeddings') for e in orders]:
                            body = {'model': model, 'dimensions': len(VECTORS[0])}
                            if encoding is not None and early:
                                body['encoding_format'] = encoding
                            body['input'] = ['first' + ('x' * 4096 if large else ''), 'second']
                            if encoding is not None and not early:
                                # After a streamed input: beyond the routing prefetch.
                                body['encoding_format'] = encoding
                            response = request(base, path, body)
                            indexes = (7, 2) if model.startswith('openai/') or '/nebius/' in model else (0, 1)
                            assert_vectors(response, encoding == 'base64', indexes)
                            assert response['model'] == model, response
                            assert response['usage']['prompt_tokens'] == tokens and response['usage']['total_tokens'] == tokens, response
                            if model.startswith('openai/'):
                                assert response['id'] == 'keep-response-id' and response['metadata'] == {'keep': [1, 'two']}
                                assert response['usage']['cost'] == 0.125 and response['usage']['details'] == {'keep': True}
                                assert [e['tag'] for e in response['data']] == ['keep-0', 'keep-1']
                            print('ok', 'large' if large else 'ordinary', path, model, encoding or 'default', 'format-first' if early else 'format-last')
                # A small native request whose response exceeds response_threshold_bytes still needs translation.
                if large:
                    response = request(base, '/v1/embeddings', {'model': 'gemini/embedding', 'input': ['first', 'second'], 'encoding_format': 'base64'})
                    assert_vectors(response, True)
                    print('ok ordinary request / large native response')
                # Native AWS InvokeModel is a raw native body, not the OpenAI encoding boundary.
                raw = request(base, '/bedrock/model/amazon.titan-embed-text-v2:0/invoke',
                              {'inputText': 'first', 'dimensions': len(VECTORS[0]), 'normalize': True})
                assert raw['embedding'] == VECTORS[0] and raw['inputTextTokenCount'] == 3, raw
                print('ok native InvokeModel remains float')
    finally:
        mock.shutdown()
        mock.server_close()
        mock.thread.join()


if __name__ == '__main__':
    main()
