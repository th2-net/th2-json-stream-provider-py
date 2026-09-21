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

"""Extraction of the real th2-rpt-viewer image.

The rest of the `prepare_viewer.py` tests stub the container runtime out. This one does not: it
pulls and unpacks the actual image, which is the only way to notice that a new viewer version
moved the document root, stopped shipping the configuration symlink, or changed the URL the
proxy is built around. It needs podman or docker and is opt-in:

    pytest -m docker
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import prepare_viewer
import serve_static

pytestmark = pytest.mark.docker

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
VIEWER_CONFIG = SCRIPTS_DIR / 'th2-rpt-viewer' / 'custom.json'

EXTRACT_TIMEOUT = 900


@pytest.fixture(scope='module')
def extracted(tmp_path_factory):
    """Runs `prepare_viewer.py` against the real image, as a user would."""
    if shutil.which('podman') is None and shutil.which('docker') is None:
        pytest.skip('neither podman nor docker is available')

    target = tmp_path_factory.mktemp('viewer') / 'static'
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / 'prepare_viewer.py'),
         '--target', str(target), '--config', str(VIEWER_CONFIG)],
        capture_output=True, text=True, timeout=EXTRACT_TIMEOUT,
    )
    if result.returncode != 0:
        pytest.fail(f'extraction failed:\n{result.stdout}\n{result.stderr}')
    return target


def javascript_of(target: Path) -> str:
    return '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                     for path in target.glob('*.js'))


def test_extracts_the_viewer_entry_point(extracted):
    index = extracted / 'index.html'

    assert index.is_file()
    assert 'TH2 Report' in index.read_text()


def test_extracts_the_bundle_and_the_resources(extracted):
    assert list(extracted.glob('main.*.js')), 'the main bundle is missing'
    assert (extracted / 'resources').is_dir()
    # a viewer that suddenly ships a handful of files means the document root moved
    assert len(list(extracted.rglob('*'))) > 100


def test_materializes_the_configuration_symlink(extracted):
    """In the image this is a symlink into the /var/th2 bind mount, which does not exist here."""
    config = extracted / prepare_viewer.VIEWER_CONFIG_PATH

    assert config.is_file()
    assert not config.is_symlink()
    assert json.loads(config.read_text()) == json.loads(VIEWER_CONFIG.read_text())


def test_leaves_the_rest_of_the_container_out(extracted):
    for unwanted in ('etc', 'usr', 'docker-entrypoint.sh', 'bin'):
        assert not (extracted / unwanted).exists(), unwanted


def test_the_viewer_still_calls_the_provider_through_the_proxied_prefix(extracted):
    """`serve_static.py` proxies this prefix, a viewer that renamed it would break silently."""
    prefix = serve_static.DEFAULT_PREFIX.strip('/')

    assert f'"{prefix}"' in javascript_of(extracted)


def test_the_viewer_still_reads_the_configuration_from_the_materialized_path(extracted):
    """The path the extraction writes has to be the path the bundle fetches."""
    assert prepare_viewer.VIEWER_CONFIG_PATH in javascript_of(extracted)


def test_the_extraction_is_reproducible(extracted, tmp_path):
    """A second extraction of the same image produces the same tree."""
    second = tmp_path / 'static'
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / 'prepare_viewer.py'),
         '--target', str(second), '--config', str(VIEWER_CONFIG)],
        check=True, capture_output=True, timeout=EXTRACT_TIMEOUT,
    )

    first_names = {path.relative_to(extracted) for path in extracted.rglob('*')}
    second_names = {path.relative_to(second) for path in second.rglob('*')}
    assert first_names == second_names
