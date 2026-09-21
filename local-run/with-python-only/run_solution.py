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

"""Configures and launches the whole solution: Jupyter, th2-json-stream-provider, th2-rpt-viewer.

This is the `compose.yml` equivalent of the python only setup. It is driven by `config.yaml`:

    python3 run_solution.py                    # uses ./config.yaml
    python3 run_solution.py --config my.yaml

The three servers run as child processes, their output is streamed with a per-process prefix, and
they are shut down together when one of them exits or on Ctrl+C.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import venv
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent

# the provider reads its logging configuration from this name next to its custom.json
LOG4PY_FILE_NAME = 'log4py.conf'

DEFAULTS = {
    'host': '127.0.0.1',
    'ports': {'viewer': 8080, 'json-stream-provider': 8081, 'jupyter': 8082},
    'workspace': './workspace',
    'viewer': {'static': './th2-rpt-viewer/static', 'config': './th2-rpt-viewer/custom.json'},
    'kernel': {'venv': './kernel-venv', 'name': '.venv', 'display-name': 'Python (.venv)'},
    'jupyter': {'base-url': '/jupyter/', 'token': '', 'open-browser': False,
                'data-dir': './jupyter-data'},
    'json-stream-provider': {'script': None, 'log-config': './json-stream-provider/log4py.conf',
                             'out-of-use-engine-time': 3600, 'cleanup-horizon-days': -1,
                             'restart-kernel-on-error': False},
    'runtime-dir': './runtime',
}

# subdirectories of the workspace, they are what the provider is pointed at and what Jupyter shows
NOTEBOOKS_SUBDIR = 'notebooks'
RESULTS_SUBDIR = 'results'
RESULTS_IMAGES_SUBDIR = 'results/images'
LOGS_SUBDIR = 'logs'


@dataclass
class Settings:
    host: str
    viewer_port: int
    provider_port: int
    jupyter_port: int
    workspace: Path
    viewer_static: Path
    viewer_config: Path
    kernel_venv: Path
    kernel_name: str
    kernel_display_name: str
    jupyter_base_url: str
    jupyter_token: str
    jupyter_open_browser: bool
    jupyter_data_dir: Path
    provider_script: Path
    provider_log_config: Path
    provider_options: dict
    runtime_dir: Path
    python: str = sys.executable
    serve_static_script: Path = field(default_factory=lambda: SCRIPT_DIR / 'serve_static.py')

    @property
    def notebooks_dir(self) -> Path:
        return self.workspace / NOTEBOOKS_SUBDIR

    @property
    def results_dir(self) -> Path:
        return self.workspace / RESULTS_SUBDIR

    @property
    def results_images_dir(self) -> Path:
        return self.workspace / RESULTS_IMAGES_SUBDIR

    @property
    def logs_dir(self) -> Path:
        return self.workspace / LOGS_SUBDIR

    @property
    def provider_config(self) -> Path:
        return self.runtime_dir / 'json-stream-provider' / 'custom.json'


def merge_defaults(config: dict, defaults: dict = None) -> dict:
    """Overlays `config` onto the defaults, one level into the nested sections."""
    merged = {}
    for key, fallback in (defaults if defaults is not None else DEFAULTS).items():
        given = (config or {}).get(key)
        if isinstance(fallback, dict):
            merged[key] = {**fallback, **(given or {})}
        else:
            merged[key] = fallback if given is None else given
    return merged


def find_provider_script(base_dir: Path) -> Path:
    """Locates `server.py`: next to the config in a distributive, up in the repository checkout."""
    candidates = [base_dir / 'server.py', base_dir / '..' / '..' / 'server.py']
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    searched = ', '.join(str(c.resolve()) for c in candidates)
    sys.exit(f'server.py not found, looked in {searched}, set json-stream-provider.script')


def load_settings(config_path: Path) -> Settings:
    config_path = config_path.resolve()
    if not config_path.is_file():
        sys.exit(f'configuration {config_path} not found')
    with open(config_path) as stream:
        config = merge_defaults(yaml.safe_load(stream) or {})

    base_dir = config_path.parent

    def resolve(value) -> Path:
        # relative paths follow the configuration file, so the solution can be unpacked anywhere
        return (base_dir / Path(value).expanduser()).resolve()

    provider = dict(config['json-stream-provider'])
    script = provider.pop('script', None)
    log_config = provider.pop('log-config', None)
    jupyter = config['jupyter']
    kernel = config['kernel']
    return Settings(
        host=config['host'],
        viewer_port=config['ports']['viewer'],
        provider_port=config['ports']['json-stream-provider'],
        jupyter_port=config['ports']['jupyter'],
        workspace=resolve(config['workspace']),
        viewer_static=resolve(config['viewer']['static']),
        viewer_config=resolve(config['viewer']['config']),
        kernel_venv=resolve(kernel['venv']),
        kernel_name=kernel['name'],
        kernel_display_name=kernel['display-name'],
        jupyter_base_url=jupyter['base-url'],
        jupyter_token=jupyter['token'] or '',
        jupyter_open_browser=bool(jupyter['open-browser']),
        jupyter_data_dir=resolve(jupyter['data-dir']),
        provider_script=resolve(script) if script else find_provider_script(base_dir),
        provider_log_config=resolve(log_config) if log_config else None,
        provider_options=provider,
        runtime_dir=resolve(config['runtime-dir']),
    )


def prepare_workspace(settings: Settings) -> None:
    for directory in (settings.notebooks_dir, settings.results_dir, settings.results_images_dir,
                      settings.logs_dir, settings.jupyter_data_dir, settings.runtime_dir):
        directory.mkdir(parents=True, exist_ok=True)


def write_provider_config(settings: Settings) -> Path:
    """Generates the provider `custom.json` out of the yaml configuration."""
    config = {
        'notebooks': str(settings.notebooks_dir),
        'results': str(settings.results_dir),
        'results-images': str(settings.results_images_dir),
        'logs': str(settings.logs_dir),
        'python-kernel-name': settings.kernel_name,
        'virtual-environment-dir': str(settings.kernel_venv),
        'host': settings.host,
        'port': settings.provider_port,
        **settings.provider_options,
    }
    destination = settings.provider_config
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, indent=2) + '\n')
    write_provider_log_config(settings)
    return destination


def write_provider_log_config(settings: Settings) -> Path:
    """Puts the logging configuration next to the generated custom.json.

    The provider resolves `log4py.conf` against the directory of the configuration it is given,
    the same way it picks both of them up from /var/th2/config inside a container.
    """
    source = settings.provider_log_config
    if source is None or not source.is_file():
        return None
    destination = settings.provider_config.parent / LOG4PY_FILE_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text())
    return destination


def write_viewer_config(settings: Settings) -> Path:
    """Puts the viewer configuration where the viewer fetches it from."""
    if not settings.viewer_static.is_dir():
        sys.exit(f'viewer static {settings.viewer_static} not found, run prepare_viewer.py first')
    destination = settings.viewer_static / 'config' / 'th2' / 'custom.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(settings.viewer_config.read_text())
    return destination


def ensure_kernel_venv(settings: Settings, wheelhouse: Path = None) -> None:
    """Creates the notebook virtual environment and makes sure `ipykernel` is available in it.

    The provider registers the kernel itself, but the environment it creates would not have
    `ipykernel`: a virtual environment created from inside another one inherits the packages of the
    base interpreter, not of the environment the provider runs in.
    """
    python = settings.kernel_venv / 'bin' / 'python'
    if not settings.kernel_venv.exists():
        print(f'creating notebook virtual environment {settings.kernel_venv}', flush=True)
        venv.create(settings.kernel_venv, with_pip=True)
    if subprocess.run([str(python), '-c', 'import ipykernel'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    install = [str(python), '-m', 'pip', 'install', 'ipykernel']
    if wheelhouse is not None:
        install += ['--no-index', '--find-links', str(wheelhouse)]
    print(f'installing ipykernel into {settings.kernel_venv}', flush=True)
    subprocess.run(install, check=True)


def child_environment(settings: Settings) -> dict:
    environment = dict(os.environ)
    # keeps the kernel the provider registers and the kernel Jupyter lists in the same place
    environment['JUPYTER_DATA_DIR'] = str(settings.jupyter_data_dir)
    # children write through a pipe, without this their output would appear only when they exit
    environment['PYTHONUNBUFFERED'] = '1'
    return environment


def build_commands(settings: Settings) -> list:
    """Returns the `(name, command)` pairs of the three servers, in start up order."""
    jupyter = [
        settings.python, '-m', 'jupyterlab',
        f'--ServerApp.ip={settings.host}',
        f'--ServerApp.port={settings.jupyter_port}',
        f'--ServerApp.base_url={settings.jupyter_base_url}',
        f'--ServerApp.root_dir={settings.workspace}',
        f'--ServerApp.token={settings.jupyter_token}',
        f'--MultiKernelManager.default_kernel_name={settings.kernel_name}',
        '--ServerApp.open_browser=' + ('True' if settings.jupyter_open_browser else 'False'),
    ]
    return [
        ('j-sp', [settings.python, str(settings.provider_script), str(settings.provider_config)]),
        ('viewer', [settings.python, str(settings.serve_static_script),
                    '--port', str(settings.viewer_port),
                    '--bind', settings.host,
                    '--backend-host', '127.0.0.1',
                    '--backend-port', str(settings.provider_port),
                    '--directory', str(settings.viewer_static)]),
        ('jupyter', jupyter),
    ]


class Supervisor:
    """Runs the child processes, prefixes their output and shuts them all down together."""

    def __init__(self, environment: dict, cwd: Path = None):
        self.environment = environment
        self.cwd = cwd
        self.processes = []
        self.readers = []

    def start(self, name: str, command: list) -> subprocess.Popen:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=self.environment, cwd=str(self.cwd) if self.cwd else None,
            text=True, bufsize=1,
        )
        self.processes.append((name, process))
        reader = threading.Thread(target=self._stream, args=(name, process), daemon=True)
        reader.start()
        self.readers.append(reader)
        return process

    @staticmethod
    def _stream(name: str, process: subprocess.Popen) -> None:
        for line in process.stdout:
            print(f'[{name}] {line.rstrip()}', flush=True)

    def first_exited(self):
        for name, process in self.processes:
            if process.poll() is not None:
                return name, process
        return None

    def wait(self, poll_interval: float = 0.5):
        """Blocks until one of the children exits, returns it."""
        while True:
            exited = self.first_exited()
            if exited is not None:
                return exited
            time.sleep(poll_interval)

    def shutdown(self, timeout: float = 10.0) -> None:
        for name, process in self.processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + timeout
        for name, process in self.processes:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                print(f'[{name}] did not stop in time, killing', flush=True)
                process.kill()
        for reader in self.readers:
            reader.join(timeout=1.0)


def print_urls(settings: Settings) -> None:
    host = '127.0.0.1' if settings.host == '0.0.0.0' else settings.host
    base_url = settings.jupyter_base_url if settings.jupyter_base_url.startswith('/') \
        else '/' + settings.jupyter_base_url
    token = f'?token={settings.jupyter_token}' if settings.jupyter_token else ''
    print('', flush=True)
    print(f'  th2-rpt-viewer  http://{host}:{settings.viewer_port}/', flush=True)
    print(f'  jupyter         http://{host}:{settings.jupyter_port}{base_url}{token}', flush=True)
    print(f'  j-sp            http://{host}:{settings.provider_port}/status', flush=True)
    print(f'  workspace       {settings.workspace}', flush=True)
    print('', flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=SCRIPT_DIR / 'config.yaml',
                        help='yaml configuration to use (default: config.yaml next to this script)')
    parser.add_argument('--wheelhouse', type=Path,
                        help='install ipykernel from this directory instead of from the network')
    parser.add_argument('--skip-kernel-venv', action='store_true',
                        help='do not create or check the notebook virtual environment')
    args = parser.parse_args()

    settings = load_settings(args.config)
    prepare_workspace(settings)
    provider_config = write_provider_config(settings)
    write_viewer_config(settings)
    print(f'provider configuration written to {provider_config}', flush=True)

    wheelhouse = args.wheelhouse
    if wheelhouse is None:
        default_wheelhouse = settings.provider_script.parent / 'wheelhouse'
        wheelhouse = default_wheelhouse if default_wheelhouse.is_dir() else None
    if not args.skip_kernel_venv:
        ensure_kernel_venv(settings, wheelhouse)

    supervisor = Supervisor(child_environment(settings), cwd=settings.workspace)
    interrupted = False
    try:
        for name, command in build_commands(settings):
            print(f'starting {name}', flush=True)
            supervisor.start(name, command)
        print_urls(settings)
        name, process = supervisor.wait()
        print(f'[{name}] exited with code {process.returncode}, stopping the solution', flush=True)
        return process.returncode or 1
    except KeyboardInterrupt:
        interrupted = True
        print('\nstopping the solution', flush=True)
        return 0
    finally:
        supervisor.shutdown()
        if interrupted:
            # restore the default handler so a second Ctrl+C is not swallowed
            signal.signal(signal.SIGINT, signal.SIG_DFL)


if __name__ == '__main__':
    sys.exit(main())
