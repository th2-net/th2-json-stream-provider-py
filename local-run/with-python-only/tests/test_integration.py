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

"""End to end test of the whole solution, the automated form of a manual smoke run.

`run_solution.py` is started as it would be by a user, then a notebook is executed through the
viewer's proxy and its results are looked up through Jupyter. Unlike the rest of the suite this
needs the real dependencies and the extracted viewer, so it is marked `integration` and excluded
from the default run:

    pytest tests -m integration
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent.parent
VIEWER_STATIC = SCRIPTS_DIR / 'th2-rpt-viewer' / 'static'
EXAMPLE_NOTEBOOK = REPO_ROOT / 'example' / 'example.ipynb'
SHARED_KERNEL_VENV = SCRIPTS_DIR / 'kernel-venv'

pytestmark = pytest.mark.integration

STARTUP_TIMEOUT = 180
RUN_TIMEOUT = 120


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def missing_requirement() -> str:
    for module in ('aiohttp', 'papermill', 'jupyterlab', 'yaml', 'requests'):
        try:
            __import__(module)
        except ImportError:
            return f'{module} is not installed'
    if not (VIEWER_STATIC / 'index.html').is_file():
        return f'{VIEWER_STATIC} is missing, run prepare_viewer.py first'
    if not EXAMPLE_NOTEBOOK.is_file():
        return f'{EXAMPLE_NOTEBOOK} is missing'
    return ''


def wait_until(predicate, timeout: float, description: str, process=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AssertionError(f'the launcher exited with {process.returncode} while '
                                 f'waiting until {description}')
        try:
            if predicate():
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise AssertionError(f'timed out after {timeout}s waiting until {description}')


class Solution:
    """The running solution and the addresses of its parts."""

    def __init__(self, viewer_port, jupyter_port, provider_port, workspace, log):
        self.viewer = f'http://127.0.0.1:{viewer_port}'
        self.jupyter = f'http://127.0.0.1:{jupyter_port}/jupyter'
        self.provider = f'http://127.0.0.1:{provider_port}'
        self.workspace = workspace
        self.log = log

    def proxied(self, path: str) -> str:
        return f'{self.viewer}/json-stream-provider{path}'


@pytest.fixture(scope='module')
def solution(tmp_path_factory):
    reason = missing_requirement()
    if reason:
        pytest.skip(reason)

    tmp_path = tmp_path_factory.mktemp('solution')
    viewer_port, jupyter_port, provider_port = free_port(), free_port(), free_port()
    # reuse the notebook environment of a previous run when there is one, creating it costs a
    # pip install of ipykernel
    kernel_venv = SHARED_KERNEL_VENV if (SHARED_KERNEL_VENV / 'bin' / 'python').is_file() \
        else tmp_path / 'kernel-venv'
    config = {
        'host': '127.0.0.1',
        'ports': {'viewer': viewer_port, 'json-stream-provider': provider_port,
                  'jupyter': jupyter_port},
        'workspace': str(tmp_path / 'workspace'),
        'viewer': {'static': str(VIEWER_STATIC),
                   'config': str(SCRIPTS_DIR / 'th2-rpt-viewer' / 'custom.json')},
        'kernel': {'venv': str(kernel_venv)},
        'jupyter': {'data-dir': str(tmp_path / 'jupyter-data')},
        'json-stream-provider': {'script': str(REPO_ROOT / 'server.py')},
        'runtime-dir': str(tmp_path / 'runtime'),
    }
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(json.dumps(config))  # json is valid yaml

    log_path = tmp_path / 'solution.log'
    log = open(log_path, 'w')
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_DIR / 'run_solution.py'), '--config', str(config_path)],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(tmp_path),
    )
    running = Solution(viewer_port, jupyter_port, provider_port, tmp_path / 'workspace', log_path)
    try:
        wait_until(lambda: requests.get(running.viewer + '/', timeout=2).status_code == 200,
                   STARTUP_TIMEOUT, 'the viewer answers', process)
        wait_until(lambda: requests.get(running.proxied('/status'), timeout=2).status_code == 200,
                   STARTUP_TIMEOUT, 'the provider answers through the proxy', process)
        wait_until(lambda: requests.get(running.jupyter + '/api/status', timeout=2).status_code
                   == 200, STARTUP_TIMEOUT, 'jupyter answers', process)
        yield running
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        if log_path.is_file() and os.environ.get('SOLUTION_LOG'):
            print(log_path.read_text())


def test_viewer_is_served(solution):
    response = requests.get(solution.viewer + '/', timeout=10)

    assert response.status_code == 200
    assert '<title>TH2 Report</title>' in response.text


def test_viewer_config_is_a_real_file(solution):
    """In the image this path is a symlink into a bind mount that does not exist here."""
    response = requests.get(solution.viewer + '/config/th2/custom.json', timeout=10)

    assert response.status_code == 200
    assert 'jsonlReaderTab' in response.json()


def test_provider_is_reachable_through_the_proxy(solution):
    response = requests.get(solution.proxied('/status'), timeout=10)

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_jupyter_serves_the_workspace(solution):
    """The provider directories have to be visible in Jupyter, that is the point of one root."""
    response = requests.get(solution.jupyter + '/api/contents', timeout=10)

    names = {entry['name'] for entry in response.json()['content']}
    assert {'notebooks', 'results', 'logs'} <= names


def test_jupyter_lists_the_notebook_kernel(solution):
    response = requests.get(solution.jupyter + '/api/kernelspecs', timeout=10)

    kernelspecs = response.json()
    assert '.venv' in kernelspecs['kernelspecs']
    assert kernelspecs['default'] == '.venv'


def test_runs_a_notebook_and_publishes_its_results(solution):
    """The full path a user takes: the viewer starts a run and reads the results back."""
    notebook = solution.workspace / 'notebooks' / 'example.ipynb'
    notebook.write_bytes(EXAMPLE_NOTEBOOK.read_bytes())

    listed = requests.get(solution.proxied('/files/notebooks'), timeout=30,
                          headers={'Accept': 'application/json'}).json()
    assert str(notebook) in listed['files']

    started = requests.post(solution.proxied(f'/execute?path={notebook}'), json={}, timeout=60)
    assert started.status_code == 200
    task_id = started.json()['task_id']

    result = {}

    def finished():
        nonlocal result
        result = requests.get(solution.proxied(f'/result?id={task_id}'), timeout=10).json()
        return result.get('status') != 'in progress'

    wait_until(finished, RUN_TIMEOUT, 'the notebook run finishes')
    assert result['status'] == 'success', result

    # the run is only useful if its output is where both the viewer and jupyter can see it
    produced = requests.get(solution.jupyter + '/api/contents/results', timeout=10).json()
    names = [entry['name'] for entry in produced['content']]
    assert any(name.endswith('.jsonl') for name in names), names


def test_shuts_everything_down_on_interrupt(tmp_path_factory):
    """Ctrl+C has to stop all three servers, leaving nothing behind holding the ports."""
    reason = missing_requirement()
    if reason:
        pytest.skip(reason)

    tmp_path = tmp_path_factory.mktemp('shutdown')
    viewer_port, jupyter_port, provider_port = free_port(), free_port(), free_port()
    kernel_venv = SHARED_KERNEL_VENV if (SHARED_KERNEL_VENV / 'bin' / 'python').is_file() \
        else tmp_path / 'kernel-venv'
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(json.dumps({
        'host': '127.0.0.1',
        'ports': {'viewer': viewer_port, 'json-stream-provider': provider_port,
                  'jupyter': jupyter_port},
        'workspace': str(tmp_path / 'workspace'),
        'viewer': {'static': str(VIEWER_STATIC),
                   'config': str(SCRIPTS_DIR / 'th2-rpt-viewer' / 'custom.json')},
        'kernel': {'venv': str(kernel_venv)},
        'jupyter': {'data-dir': str(tmp_path / 'jupyter-data')},
        'json-stream-provider': {'script': str(REPO_ROOT / 'server.py')},
        'runtime-dir': str(tmp_path / 'runtime'),
    }))

    with open(tmp_path / 'solution.log', 'w') as log:
        process = subprocess.Popen(
            [sys.executable, str(SCRIPTS_DIR / 'run_solution.py'), '--config', str(config_path)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(tmp_path),
        )
        try:
            wait_until(
                lambda: requests.get(f'http://127.0.0.1:{viewer_port}/', timeout=2).status_code
                == 200, STARTUP_TIMEOUT, 'the solution starts', process)
            children = subprocess.run(['pgrep', '-P', str(process.pid)],
                                      capture_output=True, text=True).stdout.split()
            assert len(children) == 3, children

            process.send_signal(signal.SIGINT)
            process.wait(timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)

    assert process.returncode == 0
    remaining = subprocess.run(['pgrep', '-P', str(process.pid)],
                               capture_output=True, text=True).stdout.split()
    assert remaining == []
    # the ports are free again, so nothing kept listening
    for port in (viewer_port, provider_port, jupyter_port):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
