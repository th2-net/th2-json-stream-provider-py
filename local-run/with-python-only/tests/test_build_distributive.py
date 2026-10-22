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

"""Tests for `build_distributive.py`.

The staging and the archives are built for real, only the viewer extraction and the wheel download
are stubbed, so nothing here needs a container runtime or the network.
"""

import tarfile
import zipfile
from pathlib import Path

import pytest

build_distributive = pytest.importorskip(
    'build_distributive', reason='build_distributive.py is not shipped in a distributive')

SCRIPTS_DIR = Path(build_distributive.__file__).resolve().parent


def build_staging(tmp_path):
    staging = tmp_path / 'staged'
    build_distributive.stage(staging)
    return staging


class TestFlattenRequirements:

    def test_inlines_an_include(self, tmp_path):
        (tmp_path / 'base.txt').write_text('aiohttp~=3.13.3\npapermill~=2.6.0\n')
        (tmp_path / 'requirements.txt').write_text('-r base.txt\njupyterlab~=4.6.3\n')

        lines = build_distributive.flatten_requirements(tmp_path / 'requirements.txt')

        assert 'aiohttp~=3.13.3' in lines
        assert 'papermill~=2.6.0' in lines
        assert 'jupyterlab~=4.6.3' in lines
        # the include itself is gone, a distributive cannot resolve it
        assert not any(line.strip().startswith('-r') for line in lines)

    def test_keeps_comments(self, tmp_path):
        (tmp_path / 'requirements.txt').write_text('# why this pin\nrequests~=2.34.2\n')

        lines = build_distributive.flatten_requirements(tmp_path / 'requirements.txt')

        assert '# why this pin' in lines

    def test_follows_nested_includes(self, tmp_path):
        (tmp_path / 'deep.txt').write_text('attrs~=1.0\n')
        (tmp_path / 'base.txt').write_text('-r deep.txt\naiohttp~=3.13.3\n')
        (tmp_path / 'requirements.txt').write_text('-r base.txt\n')

        lines = build_distributive.flatten_requirements(tmp_path / 'requirements.txt')

        assert 'attrs~=1.0' in lines and 'aiohttp~=3.13.3' in lines


class TestStaging:

    def test_carries_the_provider(self, tmp_path):
        staging = build_staging(tmp_path)

        assert (staging / 'server.py').is_file()
        assert (staging / 'json_stream_provider' / '__init__.py').is_file()
        assert (staging / 'example' / 'example.ipynb').is_file()

    def test_carries_the_launcher_and_its_configuration(self, tmp_path):
        staging = build_staging(tmp_path)

        for name in ('run_solution.py', 'serve_static.py', 'config.yaml', 'README.md'):
            assert (staging / name).is_file(), name
        assert (staging / 'json-stream-provider' / 'log4py.conf').is_file()

    def test_carries_the_extracted_viewer(self, tmp_path):
        if not (SCRIPTS_DIR / 'th2-rpt-viewer' / 'static' / 'index.html').is_file():
            pytest.skip('the viewer is not extracted, run prepare_viewer.py first')
        staging = build_staging(tmp_path)

        assert (staging / 'th2-rpt-viewer' / 'static' / 'index.html').is_file()
        # the viewer reads this on start up, in the image it is a symlink into a bind mount
        assert (staging / 'th2-rpt-viewer' / 'static' / 'config' / 'th2' / 'custom.json').is_file()

    def test_carries_the_license(self, tmp_path):
        staging = build_staging(tmp_path)

        assert (staging / 'LICENSE').is_file()
        assert (staging / 'NOTICE').is_file()

    def test_requirements_are_flattened(self, tmp_path):
        staging = build_staging(tmp_path)

        written = (staging / 'requirements.txt').read_text()

        assert 'aiohttp' in written and 'jupyterlab' in written
        assert '-r ' not in written

    def test_excludes_build_artefacts(self, tmp_path):
        cache = SCRIPTS_DIR / 'tests' / '__pycache__'
        if not cache.exists():
            pytest.skip('nothing cached to leak')

        staging = build_staging(tmp_path)

        assert not list(staging.rglob('__pycache__'))
        assert not list(staging.rglob('*.pyc'))


class TestArchives:

    def test_tar_has_a_single_top_level_directory(self, tmp_path):
        staging = build_staging(tmp_path)

        archive = build_distributive.build_tar(staging, staging)

        with tarfile.open(archive) as tar:
            roots = {name.split('/')[0] for name in tar.getnames()}
        assert roots == {staging.name}

    def test_zip_has_a_single_top_level_directory(self, tmp_path):
        staging = build_staging(tmp_path)

        archive = build_distributive.build_zip(staging, staging)

        with zipfile.ZipFile(archive) as zip_file:
            roots = {name.split('/')[0] for name in zip_file.namelist()}
        assert roots == {staging.name}

    @pytest.mark.parametrize('extension', ['.tar.gz', '.zip'])
    def test_a_dotted_version_survives_the_name(self, tmp_path, extension):
        """Regression: with_suffix turned 0.2.1 into 0.2."""
        destination = tmp_path / 'th2-json-stream-provider-local-run-0.2.1'

        archive = build_distributive.archive_path(destination, extension)

        assert archive.name == f'th2-json-stream-provider-local-run-0.2.1{extension}'

    def test_describe_reports_a_checksum(self, tmp_path):
        archive = tmp_path / 'sample.tar.gz'
        archive.write_bytes(b'payload')

        described = build_distributive.describe(archive)

        assert 'sha256' in described
        assert 'MB' in described


def test_version_comes_from_package_info():
    version = build_distributive.read_version()

    assert version
    assert version[0].isdigit()
