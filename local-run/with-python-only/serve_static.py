#!/usr/bin/env python3
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

"""Serves the th2-rpt-viewer static and proxies its API calls to th2-json-stream-provider.

This replaces the nginx reverse proxy of the compose based setup. th2-rpt-viewer requests `j-sp`
through the relative `json-stream-provider/...` URL, so everything under that prefix is forwarded
to `j-sp` with the prefix stripped, and everything else is served from the static directory.

    python3 serve_static.py --port 8080 --backend-port 8081 --directory th2-rpt-viewer/static
    python3 serve_static.py 8080 8081 th2-rpt-viewer/static   # positional form
"""

import argparse
import email.message
import sys
from http.server import (
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)

import requests as requests

DIRECTORY = None
BACKEND_HOST = None
BACKEND_PORT = None
PORT = None
PREFIX = None

DEFAULT_PREFIX = '/json-stream-provider'

# headers that describe the hop rather than the payload, they are re-created for the next hop
HOP_BY_HOP_REQUEST_HEADERS = frozenset({'accept-encoding', 'host', 'connection', 'content-length'})
# `send_response` emits `Date` and `Server` itself, forwarding the provider's copies duplicates them
HOP_BY_HOP_RESPONSE_HEADERS = frozenset({'content-encoding', 'transfer-encoding', 'connection',
                                         'date', 'server'})


class ProxyHTTPRequestHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def __init__(self, request, client_address, server):
        global DIRECTORY

        self.proxy_client = requests.Session()
        super(ProxyHTTPRequestHandler, self).__init__(
            client_address=client_address, request=request, server=server, directory=DIRECTORY
        )

    def _is_backend_path(self) -> bool:
        return self.path == PREFIX or self.path.startswith(PREFIX + '/') \
            or self.path.startswith(PREFIX + '?')

    def _backend_url(self) -> str:
        path = self.path[len(PREFIX):].lstrip('/')
        return f"http://{BACKEND_HOST}:{BACKEND_PORT}/{path}"

    def _request_headers(self) -> email.message.Message:
        headers = email.message.Message()
        for k, v in self.headers.items():
            if k.lower() not in HOP_BY_HOP_REQUEST_HEADERS:
                headers.set_raw(k, v)
        return headers

    def _read_body(self) -> bytes:
        length = self.headers.get('Content-Length')
        if length is None:
            return b''
        return self.rfile.read(int(length))

    def _proxy(self, method: str, body: bytes = None, send_body: bool = True) -> None:
        try:
            with self.proxy_client.request(
                    method, self._backend_url(), headers=self._request_headers(), data=body,
                    stream=True, allow_redirects=False, verify=False,
            ) as resp:
                self.send_response(resp.status_code)

                for k, v in resp.headers.items():
                    if k.lower() not in HOP_BY_HOP_RESPONSE_HEADERS:
                        self.send_header(k, v)
                self.end_headers()

                if send_body:
                    for i in resp.iter_content(chunk_size=None):
                        self.wfile.write(i)
                    self.wfile.flush()
        except requests.RequestException as ex:
            print("ERR", ex, flush=True)
            self.send_error(500, "No response from provider")

    def do_GET(self, body=True):
        if self._is_backend_path():
            self._proxy('GET', send_body=body)
        else:
            super().do_GET()

    def do_HEAD(self):
        if self._is_backend_path():
            self._proxy('HEAD', send_body=False)
        else:
            super().do_HEAD()

    def do_POST(self):
        if self._is_backend_path():
            self._proxy('POST', body=self._read_body())
        else:
            self.send_error(405, "Only the provider accepts POST requests")


def create_server(directory: str, port: int = 8080, backend_host: str = '127.0.0.1',
                  backend_port: int = 8081, prefix: str = DEFAULT_PREFIX,
                  bind: str = '0.0.0.0') -> ThreadingHTTPServer:
    """Configures the handler and returns a server bound to `bind`:`port`.

    `port` 0 binds an arbitrary free port, the effective one is in `server.server_address[1]`.
    """
    global DIRECTORY, BACKEND_HOST, BACKEND_PORT, PORT, PREFIX

    DIRECTORY = directory
    BACKEND_HOST = backend_host
    BACKEND_PORT = backend_port
    PREFIX = '/' + prefix.strip('/')
    server = ThreadingHTTPServer((bind, port), ProxyHTTPRequestHandler)
    PORT = server.server_address[1]
    return server


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('port_positional', nargs='?', type=int, metavar='PORT',
                        help='port to listen on')
    parser.add_argument('backend_port_positional', nargs='?', type=int, metavar='BACKEND_PORT',
                        help='port th2-json-stream-provider listens on')
    parser.add_argument('directory_positional', nargs='?', metavar='DIRECTORY',
                        help='directory with the th2-rpt-viewer static')
    parser.add_argument('--port', type=int, help='port to listen on (default: 8080)')
    parser.add_argument('--backend-port', type=int,
                        help='port th2-json-stream-provider listens on (default: 8081)')
    parser.add_argument('--backend-host', default='127.0.0.1',
                        help='host th2-json-stream-provider listens on (default: 127.0.0.1)')
    parser.add_argument('--bind', default='0.0.0.0',
                        help='address to bind to (default: 0.0.0.0)')
    parser.add_argument('--directory', help='directory with the th2-rpt-viewer static')
    parser.add_argument('--prefix', default=DEFAULT_PREFIX,
                        help=f'URL prefix proxied to the provider (default: {DEFAULT_PREFIX})')
    args = parser.parse_args(argv)

    args.port = args.port if args.port is not None else (args.port_positional or 8080)
    args.backend_port = args.backend_port if args.backend_port is not None \
        else (args.backend_port_positional or 8081)
    args.directory = args.directory or args.directory_positional
    if args.directory is None:
        parser.error('a static directory is required, pass it positionally or with --directory')
    args.prefix = '/' + args.prefix.strip('/')
    return args


if __name__ == "__main__":
    arguments = parse_args(sys.argv[1:])
    httpd = create_server(
        directory=arguments.directory, port=arguments.port, backend_host=arguments.backend_host,
        backend_port=arguments.backend_port, prefix=arguments.prefix, bind=arguments.bind,
    )
    # flushed explicitly, stdout is block buffered when the launcher captures it through a pipe
    print(f"http server is running on http://{arguments.bind}:{PORT}/ "
          f"serving {DIRECTORY}, {PREFIX}/* -> http://{BACKEND_HOST}:{BACKEND_PORT}/", flush=True)
    httpd.serve_forever()
