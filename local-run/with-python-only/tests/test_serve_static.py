#  Copyright 2026 Exactpro (Exactpro Systems Limited)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Tests for `serve_static.py`.

A real server is started on an arbitrary free port in front of a stub standing in for `j-sp`, so
the static serving, the proxying and the header handling are exercised over actual HTTP. Neither
th2-json-stream-provider nor the extracted viewer is needed.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

import serve_static


class BackendStub(BaseHTTPRequestHandler):
    """Echoes back what the proxy forwarded, so the request side can be asserted on."""

    protocol_version = 'HTTP/1.1'
    recorded = []

    def _respond(self, body: bytes):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'engine_user_id=stub-user; Path=/')
        # the provider is served by aiohttp, which sets its own Date/Server headers
        self.send_header('Server', 'stub-provider')
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        BackendStub.recorded.append({
            'method': method,
            'path': self.path,
            'headers': {k.lower(): v for k, v in self.headers.items()},
            'body': body.decode(),
        })
        if self.path.startswith('/boom'):
            self.send_error(500, 'provider exploded')
            return
        self._respond(json.dumps({'method': method, 'path': self.path}).encode())

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def log_message(self, *args):
        pass


@pytest.fixture
def backend():
    BackendStub.recorded = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), BackendStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / 'index.html').write_text('<html>viewer</html>')
    config = tmp_path / 'config' / 'th2'
    config.mkdir(parents=True)
    (config / 'custom.json').write_text('{"jsonlReaderTab": {}}')
    return tmp_path


@pytest.fixture
def base_url(backend, static_dir):
    server = serve_static.create_server(
        directory=str(static_dir), port=0, bind='127.0.0.1',
        backend_host='127.0.0.1', backend_port=backend.server_address[1],
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def test_serves_the_viewer_index(base_url):
    response = requests.get(f'{base_url}/', timeout=5)

    assert response.status_code == 200
    assert response.text == '<html>viewer</html>'


def test_serves_the_viewer_config(base_url):
    """The viewer fetches this relative path on start up."""
    response = requests.get(f'{base_url}/config/th2/custom.json', timeout=5)

    assert response.status_code == 200
    assert response.json() == {'jsonlReaderTab': {}}


def test_unknown_static_path_is_404(base_url):
    assert requests.get(f'{base_url}/nope.js', timeout=5).status_code == 404


def test_proxies_get_with_the_prefix_stripped(base_url):
    response = requests.get(f'{base_url}/json-stream-provider/files/notebooks', timeout=5)

    assert response.status_code == 200
    assert response.json() == {'method': 'GET', 'path': '/files/notebooks'}


def test_proxies_the_query_string(base_url):
    requests.get(f'{base_url}/json-stream-provider/files?path=/a/b.ipynb', timeout=5)

    assert BackendStub.recorded[-1]['path'] == '/files?path=/a/b.ipynb'


def test_proxies_post_with_its_body(base_url):
    """The viewer starts notebook runs with POST /execute, which the template did not support."""
    response = requests.post(
        f'{base_url}/json-stream-provider/execute?path=/a/b.ipynb',
        json={'int_1_test': 5}, timeout=5,
    )

    assert response.status_code == 200
    recorded = BackendStub.recorded[-1]
    assert recorded['method'] == 'POST'
    assert recorded['path'] == '/execute?path=/a/b.ipynb'
    assert json.loads(recorded['body']) == {'int_1_test': 5}


def test_forwards_an_empty_post_body(base_url):
    requests.post(f'{base_url}/json-stream-provider/stop?id=42', timeout=5)

    recorded = BackendStub.recorded[-1]
    assert recorded['method'] == 'POST' and recorded['body'] == ''


def test_post_to_the_static_is_rejected(base_url):
    assert requests.post(f'{base_url}/index.html', timeout=5).status_code == 405


def test_forwards_the_provider_cookie(base_url):
    """`engine_user_id` is set by the provider and must reach the browser."""
    response = requests.get(f'{base_url}/json-stream-provider/status', timeout=5)

    assert response.cookies.get('engine_user_id') == 'stub-user'


def test_forwards_request_headers(base_url):
    requests.get(f'{base_url}/json-stream-provider/files/notebooks',
                 headers={'Accept': 'application/json', 'Cookie': 'engine_user_id=abc'}, timeout=5)

    recorded = BackendStub.recorded[-1]['headers']
    assert recorded['accept'] == 'application/json'
    assert recorded['cookie'] == 'engine_user_id=abc'


def test_drops_hop_by_hop_request_headers(base_url):
    requests.get(f'{base_url}/json-stream-provider/status',
                 headers={'Accept-Encoding': 'gzip'}, timeout=5)

    # forwarding Accept-Encoding would make the provider compress a body the proxy relays verbatim.
    # The proxy's own http client replaces it with `identity`, which is exactly what is wanted.
    assert BackendStub.recorded[-1]['headers'].get('accept-encoding') != 'gzip'


def test_does_not_duplicate_date_and_server_headers(base_url):
    """Regression: `send_response` emits both, forwarding the provider's copies duplicated them."""
    response = requests.get(f'{base_url}/json-stream-provider/status', timeout=5)

    assert response.raw.headers.get_all('Date') is not None
    assert len(response.raw.headers.get_all('Date')) == 1
    assert len(response.raw.headers.get_all('Server')) == 1
    # the emitted one is the proxy's, not the stub provider's
    assert 'stub-provider' not in response.headers['Server']


def test_relays_a_provider_error_status(base_url):
    response = requests.get(f'{base_url}/json-stream-provider/boom', timeout=5)

    assert response.status_code == 500


def test_reports_an_unreachable_provider(static_dir):
    """With no provider listening the proxy answers 500 rather than hanging or crashing."""
    server = serve_static.create_server(
        directory=str(static_dir), port=0, bind='127.0.0.1',
        backend_host='127.0.0.1', backend_port=9,  # discard port, nothing listens there
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f'http://127.0.0.1:{server.server_address[1]}/json-stream-provider/status'
        response = requests.get(url, timeout=10)
        assert response.status_code == 500
        # the static side keeps working while the provider is down
        index = requests.get(f'http://127.0.0.1:{server.server_address[1]}/', timeout=5)
        assert index.status_code == 200
    finally:
        server.shutdown()
        server.server_close()


def test_custom_prefix(backend, static_dir):
    server = serve_static.create_server(
        directory=str(static_dir), port=0, bind='127.0.0.1', prefix='/api',
        backend_host='127.0.0.1', backend_port=backend.server_address[1],
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f'http://127.0.0.1:{server.server_address[1]}'
        assert requests.get(f'{url}/api/status', timeout=5).json()['path'] == '/status'
        # the default prefix is no longer proxied, it is just a missing file
        assert requests.get(f'{url}/json-stream-provider/status', timeout=5).status_code == 404
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('argv, port, backend_port, directory', [
    (['8080', '8081', '/static'], 8080, 8081, '/static'),
    (['--port', '9000', '--backend-port', '9001', '--directory', '/s'], 9000, 9001, '/s'),
    (['--directory', '/s'], 8080, 8081, '/s'),
])
def test_argument_forms(argv, port, backend_port, directory):
    """The positional form of the original template keeps working alongside the options."""
    args = serve_static.parse_args(argv)

    assert (args.port, args.backend_port, args.directory) == (port, backend_port, directory)


def test_directory_is_required():
    with pytest.raises(SystemExit):
        serve_static.parse_args([])


@pytest.mark.parametrize('given, expected', [
    ('/json-stream-provider', '/json-stream-provider'),
    ('json-stream-provider', '/json-stream-provider'),
    ('/json-stream-provider/', '/json-stream-provider'),
])
def test_prefix_is_normalised(given, expected):
    assert serve_static.parse_args(['--directory', '/s', '--prefix', given]).prefix == expected
