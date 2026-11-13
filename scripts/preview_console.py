#!/usr/bin/env python3
"""Disposable localhost console plus two real gateways; no pulls, AWS or paid inference."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os
name = os.environ['PREVIEW_NAME']
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path.endswith('/models'):
            self.reply({'object':'list','data':[{'id':'preview-model','object':'model','owned_by':'local-preview'}]})
        else: self.send_error(404)
    def do_POST(self):
        if not self.path.endswith('/chat/completions'):
            self.send_error(404); return
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        text = name + ': local mock response. No external model was called.'
        if body.get('stream'):
            event = {'id':'local-preview','object':'chat.completion.chunk','created':1,'model':body.get('model','preview-model'),
                     'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]}
            data = ('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.reply({'id':'local-preview','object':'chat.completion','created':1,'model':body.get('model','preview-model'),
                    'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':8,'completion_tokens':12,'total_tokens':20}})
HTTPServer(('0.0.0.0',8081),Handler).serve_forever()
'''

# Fixture-only opaque TCP relay: one immutable upstream, no HTTP routing, secrets
# or external target selection. Internal-only Docker bridges cannot publish host
# ports on all engines; this preserves gateway egress isolation on those engines.
RELAY = r'''
import os, select, socket, socketserver
class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection((os.environ['TARGET'],8080),timeout=5) as upstream:
                upstream.settimeout(None)
                peers = [self.request,upstream]
                while True:
                    readable,_,_ = select.select(peers,[],[])
                    for source in readable:
                        data = source.recv(65536)
                        if not data: return
                        (upstream if source is self.request else self.request).sendall(data)
        except OSError: pass
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
Server(('0.0.0.0',8080),Relay).serve_forever()
'''


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        # Docker errors contain no runtime seed/credential content.
        raise RuntimeError(result.stderr.strip() or f'Docker {args[0]} failed')
    return result.stdout.strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def ready(url, stopped):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 45
    while not stopped.is_set() and time.monotonic() < deadline:
        try:
            with opener.open(url + '/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        stopped.wait(0.1)
    raise RuntimeError(f'Gateway did not become ready: {url}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Already-built native image; never pulled or published')
    parser.add_argument('--client-image', default='python:3.12-slim', help='Already-present image for local mock providers')
    parser.add_argument('--console-port', type=int, default=4173)
    parser.add_argument('--europe-port', type=int, default=18121)
    parser.add_argument('--america-port', type=int, default=18122)
    parser.add_argument('--ui-dir', type=Path, help='Optional built assets override; default uses the image embedded UI')
    parser.add_argument('--server', choices=['bun', 'http1'], default='bun', help='Native transport under preview')
    args = parser.parse_args()
    ports = [args.console_port, args.europe_port, args.america_port]
    if len(set(ports)) != 3 or any(not 1024 <= p <= 65535 for p in ports):
        parser.error('Choose three distinct unprivileged localhost ports')
    for port in ports:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    docker('image', 'inspect', args.image)
    docker('image', 'inspect', args.client_image)
    assets = args.ui_dir.resolve() if args.ui_dir else None
    if assets and not (assets / 'index.html').is_file():
        parser.error('--ui-dir must contain a built index.html')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    access_file = build / 'console-preview-access.json'
    if access_file.exists():
        parser.error('A preview access file already exists; stop its owner before starting another preview')
    runtime = Path(tempfile.mkdtemp(prefix='console-preview-', dir=build))
    runtime.chmod(0o755)  # Only synthetic fixture credentials exist under this disposable directory.
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    prefix = 'raiju-console-preview-' + secrets.token_hex(5)
    containers, networks, volumes = [], [], []
    console_url = f'http://127.0.0.1:{args.console_port}'
    gateways = [dict(id='local-europe', name='Local Europe', url=f'http://127.0.0.1:{args.europe_port}'),
                dict(id='local-america', name='Local America', url=f'http://127.0.0.1:{args.america_port}')]
    access = {'console': console_url, 'gateways': [], 'owner': prefix, 'server': args.server,
              'consoleSetupToken': secrets.token_hex(32)}
    manifest = runtime / 'console.json'
    save(manifest, {'gateways': gateways, 'defaultGateway': gateways[0]['id']})
    manifest.chmod(0o644)  # Manifest has origins/labels only, never credentials.

    def network(label, internal=True):
        name = prefix + '-' + label
        docker('network', 'create', *(['--internal'] if internal else []), name)
        networks.append(name)
        return name

    def gateway(label, port, net, config, console=False):
        seed = runtime / (label + '-seed.json')
        save(seed, config)
        seed.chmod(0o644)  # Only synthetic localhost fixture credentials, readable by native uid.
        volume = prefix + '-' + label + '-data'
        docker('volume', 'create', volume)
        volumes.append(volume)
        name = prefix + '-' + label
        extra = []
        if assets:
            extra += ['--env', 'RAIJU_UI_DIR=/app/ui', '--mount',
                      f'type=bind,source={assets},target=/app/ui,readonly']
        if console:
            extra += ['--env', 'RAIJU_CONSOLE_CONFIG=/app/console.json', '--mount',
                      f'type=bind,source={manifest},target=/app/console.json,readonly']
        containers.append(name)
        # Gateways themselves remain only on their own egress-disabled internal network.
        docker('run', '--detach', '--pull=never', '--name', name, '--network', net,
               '--read-only',
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=268435456', '--cap-drop=ALL',
               '--security-opt', 'no-new-privileges', '--env', 'AWS_EC2_METADATA_DISABLED=true',
               '--mount', f'type=bind,source={seed},target=/app/seed.json,readonly',
               '--mount', f'type=volume,source={volume},target=/app/data', *extra,
               '--entrypoint', '/bin/sh', args.image, '-eu', '-c',
               'if [ ! -f /app/data/config.json ]; then cp /app/seed.json /app/data/config.json; chmod 600 /app/data/config.json; fi; '
               f'exec /usr/local/bin/raiju -app-dir /app/data -host 0.0.0.0 -port 8080 -server {args.server} -workers {2 if args.server == "bun" else 1}')
        front = network(label + '-front', internal=False)
        relay = name + '-loopback'
        containers.append(relay)
        docker('run', '--detach', '--pull=never', '--name', relay, '--network', front,
               '--publish', f'127.0.0.1:{port}:8080', '--read-only', '--user', '65532:65532',
               '--cap-drop=ALL', '--security-opt', 'no-new-privileges', '--env', 'TARGET=' + name,
               '--entrypoint', 'python3', args.client_image, '-u', '-c', RELAY)
        docker('network', 'connect', net, relay)

    try:
        for entry, port in zip(gateways, ports[1:]):
            label = entry['id']
            net = network(label)
            mock_name = prefix + '-' + label + '-mock'
            containers.append(mock_name)
            docker('run', '--detach', '--pull=never', '--name', mock_name, '--network', net,
                   '--network-alias', 'local-provider', '--read-only', '--cap-drop=ALL',
                   '--security-opt', 'no-new-privileges', '--env', 'PREVIEW_NAME=' + entry['name'],
                   '--entrypoint', 'python3', args.client_image, '-u', '-c', MOCK)
            token, vk = 'local-admin-' + secrets.token_hex(24), 'sk-raiju-' + secrets.token_hex(32)
            password = 'preview-' + secrets.token_hex(8)
            config = {'client': {'allowed_origins': [console_url], 'enable_logging': False,
                                 'enforce_auth_on_inference': True, 'allow_direct_keys': False},
                      'governance': {'auth_config': {'username': 'preview', 'password': password, 'token': token},
                                     'virtual_keys': [{'id': label, 'value': vk, 'is_active': True,
                                                      'provider_configs': [{'provider': 'openai', 'allowed_models': ['preview-model']}]}]},
                      'providers': {'openai': {'keys': [{'name': label, 'value': 'local-provider-not-a-real-key',
                                                       'models': ['preview-model'], 'weight': 1}],
                                              'network_config': {'base_url': 'http://local-provider:8081', 'allow_private_network': True}}},
                      'metadata': {'preview_gateway': entry['name']}, 'logs_store': {'enabled': False},
                      'audit': {'enabled': False}, 'pricing_sync': {'enabled': False}}
            gateway(label, port, net, config)
            access['gateways'].append({**entry, 'username': 'preview', 'password': password, 'token': token,
                                       'virtualKey': vk, 'container': prefix + '-' + label})
        gateway('console', ports[0], network('console'),
                {'setup_token': access['consoleSetupToken'], 'client': {'enable_logging': False, 'allowed_origins': [console_url]},
                 'providers': {}, 'pricing_sync': {'enabled': False}}, console=True)
        for url in [*[g['url'] for g in gateways], console_url]:
            ready(url, stopped)
        save(access_file, access)
        print(f'Local console: {console_url}', flush=True)
        print('Real gateways, independent state/networks; provider responses are local mocks. No paid calls.', flush=True)
        for entry in access['gateways']:
            print(f"{entry['name']}: username {entry['username']}; password {entry['password']}", flush=True)
        print(f'Synthetic tokens and Playground keys: {access_file}', flush=True)
        print('RAIJU_PREVIEW_READY', flush=True)
        stopped.wait()
    finally:
        if containers:
            docker('rm', '--force', '--volumes', *containers, check=False)
        for volume in volumes:
            docker('volume', 'rm', volume, check=False)
        for net in networks:
            docker('network', 'rm', net, check=False)
        if access_file.exists():
            try:
                if json.loads(access_file.read_text()).get('owner') == prefix:
                    access_file.unlink()
            except (OSError, ValueError):
                pass
        shutil.rmtree(runtime)


if __name__ == '__main__':
    main()
