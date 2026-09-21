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

"""Extracts the th2-rpt-viewer JS static out of its docker image.

The rest of the `with-python-only` solution needs no container runtime, but the viewer is
distributed only as a docker image, so docker/podman is required for this one build step.
The extracted tree is served as plain files by `serve_static.py`.
"""

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

DEFAULT_IMAGE = 'ghcr.io/th2-net/th2-rpt-viewer:5.2.12'

# The image is nginx based, the viewer bundle is its document root.
IMAGE_STATIC_DIR = 'usr/share/nginx/html'

# Inside the image this path is a symlink to /var/th2/config/custom.json, which docker satisfies
# with a bind mount. There is nothing to mount here, so the file is materialized from a local copy.
VIEWER_CONFIG_PATH = 'config/th2/custom.json'

SCRIPT_DIR = Path(__file__).resolve().parent


def detect_runtime(explicit: str = None) -> str:
    if explicit:
        if shutil.which(explicit) is None:
            sys.exit(f"container runtime '{explicit}' is not available on PATH")
        return explicit
    for candidate in ('podman', 'docker'):
        if shutil.which(candidate) is not None:
            return candidate
    sys.exit('neither podman nor docker is available on PATH, use --runtime to point at one')


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print('+', ' '.join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=True, **kwargs)


def image_present(runtime: str, image: str) -> bool:
    return subprocess.run(
        [runtime, 'image', 'inspect', image],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def unpack_static(tar: tarfile.TarFile, target: Path) -> int:
    """Unpacks the members under `IMAGE_STATIC_DIR` of an open container archive into `target`.

    Works on a streamed archive, so members are visited once and in order. Returns the number of
    regular files written.
    """
    prefix = IMAGE_STATIC_DIR + '/'
    extracted = 0
    for member in tar:
        if not member.name.startswith(prefix):
            continue
        relative = member.name[len(prefix):]
        if not relative:
            continue
        destination = (target / relative).resolve()
        if not destination.is_relative_to(target):
            # the image is trusted, but an archive should never write outside its root
            raise RuntimeError(f'refusing to extract {member.name} outside {target}')
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if member.issym() or member.islnk():
            # the only link in the tree is the config symlink materialized separately
            print(f'  skipping link {relative} -> {member.linkname}', file=sys.stderr)
            continue
        if not member.isfile():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        if source is None:
            continue
        with source, open(destination, 'wb') as out:
            shutil.copyfileobj(source, out)
        extracted += 1
    return extracted


def extract_static(runtime: str, image: str, target: Path) -> int:
    """Streams the container filesystem and unpacks the viewer document root into `target`."""
    container_id = subprocess.run(
        [runtime, 'create', image],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    try:
        print('+', ' '.join([runtime, 'export', container_id]), file=sys.stderr)
        export = subprocess.Popen([runtime, 'export', container_id], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=export.stdout, mode='r|') as tar:
                return unpack_static(tar, target)
        finally:
            export.stdout.close()
            if export.wait() != 0:
                raise RuntimeError(f'{runtime} export failed with exit code {export.returncode}')
    finally:
        subprocess.run([runtime, 'rm', container_id], stdout=subprocess.DEVNULL, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--image', default=DEFAULT_IMAGE,
                        help=f'viewer image to extract (default: {DEFAULT_IMAGE})')
    parser.add_argument('--runtime', help='container runtime to use (default: podman, then docker)')
    parser.add_argument('--target', type=Path, default=SCRIPT_DIR / 'th2-rpt-viewer' / 'static',
                        help='directory to unpack the viewer into')
    parser.add_argument('--config', type=Path, default=SCRIPT_DIR / 'th2-rpt-viewer' / 'custom.json',
                        help=f'viewer config placed at {VIEWER_CONFIG_PATH} in the target')
    parser.add_argument('--pull', action='store_true', help='pull the image even if present locally')
    parser.add_argument('--force', action='store_true', help='re-extract into a non-empty target')
    args = parser.parse_args()

    # everything that can fail without touching the filesystem is validated before the target is
    # wiped, so a bad argument never destroys an already extracted tree
    if not args.config.is_file():
        sys.exit(f'viewer config {args.config} not found')
    runtime = detect_runtime(args.runtime)

    target: Path = args.target.resolve()
    if target.exists() and any(target.iterdir()):
        if not args.force:
            sys.exit(f'{target} already exists and is not empty, pass --force to re-extract')
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    if args.pull or not image_present(runtime, args.image):
        run([runtime, 'pull', args.image])

    extracted = extract_static(runtime, args.image, target)
    if extracted == 0:
        sys.exit(f'no files found under {IMAGE_STATIC_DIR} in {args.image}')

    index = target / 'index.html'
    if not index.is_file():
        sys.exit(f'{index} is missing, {args.image} does not look like th2-rpt-viewer')

    config_destination = target / VIEWER_CONFIG_PATH
    config_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.config, config_destination)

    print(f'extracted {extracted} files from {args.image} into {target}')
    print(f'viewer config taken from {args.config}')


if __name__ == '__main__':
    main()
