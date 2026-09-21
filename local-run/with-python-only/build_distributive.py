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

"""Packs the python only local run into a portable archive.

The result carries everything the solution needs except the python interpreter itself: the
provider, the extracted viewer, the launcher and its configuration. Unpack it anywhere, install
the requirements and run `run_solution.py`.

    python3 build_distributive.py                 # needs docker/podman if the viewer is missing
    python3 build_distributive.py --with-wheels   # adds an offline install of the requirements
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

DISTRIBUTIVE_NAME = 'th2-json-stream-provider-local-run'

# copied from the repository root, the provider and what its license requires
REPO_FILES = ('server.py', 'LICENSE', 'NOTICE', 'package_info.json')
REPO_DIRS = ('json_stream_provider', 'example')

# copied from this directory, the local run itself
LOCAL_FILES = ('run_solution.py', 'serve_static.py', 'prepare_viewer.py', 'config.yaml',
               'README.md', 'requirements-dev.txt', 'pytest.ini')
LOCAL_DIRS = ('th2-rpt-viewer', 'json-stream-provider', 'tests')

# never belongs in a distributive, whatever it is next to
EXCLUDED = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache')


def read_version() -> str:
    package_info = json.loads((REPO_ROOT / 'package_info.json').read_text())
    return package_info['package_version']


def flatten_requirements(path: Path) -> list:
    """Inlines the `-r` includes, a distributive has no directory above it to resolve them."""
    lines = []
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if stripped.startswith('-r'):
            included = (path.parent / stripped[2:].strip()).resolve()
            lines.append(f'# {included.name} of th2-json-stream-provider, inlined by '
                         f'build_distributive.py')
            lines.extend(flatten_requirements(included))
            continue
        lines.append(raw)
    return lines


def stage(staging: Path) -> None:
    """Assembles the contents of the distributive in `staging`."""
    staging.mkdir(parents=True)
    for name in REPO_FILES:
        shutil.copyfile(REPO_ROOT / name, staging / name)
    for name in REPO_DIRS:
        shutil.copytree(REPO_ROOT / name, staging / name, ignore=EXCLUDED)
    for name in LOCAL_FILES:
        shutil.copyfile(SCRIPT_DIR / name, staging / name)
    for name in LOCAL_DIRS:
        shutil.copytree(SCRIPT_DIR / name, staging / name, ignore=EXCLUDED)

    requirements = flatten_requirements(SCRIPT_DIR / 'requirements.txt')
    (staging / 'requirements.txt').write_text('\n'.join(requirements) + '\n')


def download_wheels(staging: Path, python: str = sys.executable) -> int:
    """Fills `wheelhouse/` so the requirements can be installed without a network.

    The wheels are built for the interpreter and the platform doing the downloading, so the
    result only installs on a matching target. That is recorded next to them.
    """
    wheelhouse = staging / 'wheelhouse'
    wheelhouse.mkdir()
    subprocess.run(
        [python, '-m', 'pip', 'download', '-r', str(staging / 'requirements.txt'),
         '-d', str(wheelhouse)],
        check=True,
    )
    version = subprocess.run([python, '-c', 'import platform, sys; print(platform.python_version(),'
                                            ' platform.system(), platform.machine())'],
                             check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    (wheelhouse / 'BUILT-FOR.txt').write_text(
        f'{version}\n\n'
        'These wheels were downloaded for the python version and platform above. Installing them\n'
        'on a different python minor version fails with "No matching distribution found", the\n'
        'compiled wheels carry a cpXY tag. Rebuild the distributive on a matching interpreter,\n'
        'or install from the network instead.\n')
    return len(list(wheelhouse.iterdir()))


def extract_viewer(runtime: str = None, python: str = sys.executable) -> None:
    """Runs `prepare_viewer.py`, it is a command line tool rather than a library."""
    command = [python, str(SCRIPT_DIR / 'prepare_viewer.py')]
    if runtime:
        command += ['--runtime', runtime]
    subprocess.run(command, check=True)


def archive_path(destination: Path, extension: str) -> Path:
    # not with_suffix: a version like 0.2.0 ends in what looks like a suffix and would be eaten
    return destination.parent / (destination.name + extension)


def build_tar(staging: Path, destination: Path) -> Path:
    archive = archive_path(destination, '.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(staging, arcname=staging.name)
    return archive


def build_zip(staging: Path, destination: Path) -> Path:
    archive = archive_path(destination, '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(staging.rglob('*')):
            zip_file.write(path, Path(staging.name) / path.relative_to(staging))
    return archive


def describe(archive: Path) -> str:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return f'{archive}\n  {archive.stat().st_size / 1_000_000:.1f} MB\n  sha256 {digest}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=SCRIPT_DIR / 'dist',
                        help='directory to write the archive into (default: ./dist)')
    parser.add_argument('--version', help='version of the distributive (default: package_info)')
    parser.add_argument('--with-wheels', action='store_true',
                        help='include a wheelhouse for installing without a network')
    parser.add_argument('--zip', action='store_true', help='also build a .zip archive')
    parser.add_argument('--skip-viewer', action='store_true',
                        help='fail instead of extracting the viewer when it is missing')
    parser.add_argument('--runtime', help='container runtime for extracting the viewer')
    args = parser.parse_args()

    viewer_static = SCRIPT_DIR / 'th2-rpt-viewer' / 'static'
    if not (viewer_static / 'index.html').is_file():
        if args.skip_viewer:
            sys.exit(f'{viewer_static} is missing, run prepare_viewer.py first')
        print(f'{viewer_static} is missing, extracting the viewer', flush=True)
        extract_viewer(args.runtime)

    version = args.version or read_version()
    output: Path = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    staging = output / f'{DISTRIBUTIVE_NAME}-{version}'
    if staging.exists():
        shutil.rmtree(staging)

    stage(staging)
    if args.with_wheels:
        print('downloading wheels', flush=True)
        wheels = download_wheels(staging)
        print(f'wheelhouse holds {wheels} files, built for python '
              f'{sys.version_info.major}.{sys.version_info.minor} on this platform only',
              flush=True)

    archives = [build_tar(staging, staging)]
    if args.zip:
        archives.append(build_zip(staging, staging))
    shutil.rmtree(staging)

    for archive in archives:
        print(describe(archive), flush=True)


if __name__ == '__main__':
    main()
