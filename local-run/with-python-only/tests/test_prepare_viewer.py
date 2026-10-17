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

"""Tests for `prepare_viewer.py`.

No container runtime is involved: the unpacking is exercised against synthetic archives shaped
like the th2-rpt-viewer image, and `main` is exercised with the runtime calls stubbed out.
"""

import io
import tarfile

import pytest

import prepare_viewer

STATIC = prepare_viewer.IMAGE_STATIC_DIR

# captured before any test stubs it out, so the real lookup can be restored where it is the subject
REAL_DETECT_RUNTIME = prepare_viewer.detect_runtime


def build_archive(files=(), dirs=(), symlinks=()) -> tarfile.TarFile:
    """Builds an in-memory tar and reopens it in streaming mode, as `extract_static` reads it."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name in dirs:
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for name, content in files:
            payload = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        for name, target in symlinks:
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode='r|')


def test_unpacks_only_the_document_root(tmp_path):
    archive = build_archive(files=[
        (f'{STATIC}/index.html', '<html>'),
        (f'{STATIC}/main.js', 'console.log(1)'),
        ('etc/nginx/nginx.conf', 'events {}'),
        ('docker-entrypoint.sh', '#!/bin/sh'),
    ])

    written = prepare_viewer.unpack_static(archive, tmp_path)

    assert written == 2
    assert (tmp_path / 'index.html').read_text() == '<html>'
    assert (tmp_path / 'main.js').read_text() == 'console.log(1)'
    # everything outside the viewer document root stays out of the target
    assert not (tmp_path / 'etc').exists()
    assert not (tmp_path / 'docker-entrypoint.sh').exists()


def test_keeps_nested_structure(tmp_path):
    archive = build_archive(
        dirs=[f'{STATIC}/resources'],
        files=[(f'{STATIC}/resources/icon.svg', '<svg/>')],
    )

    written = prepare_viewer.unpack_static(archive, tmp_path)

    assert written == 1
    assert (tmp_path / 'resources' / 'icon.svg').read_text() == '<svg/>'


def test_skips_the_config_symlink(tmp_path):
    """In the image `config/th2/custom.json` points at the /var/th2 bind mount, which is absent."""
    archive = build_archive(
        files=[(f'{STATIC}/index.html', '<html>')],
        symlinks=[(f'{STATIC}/{prepare_viewer.VIEWER_CONFIG_PATH}', '/var/th2/config/custom.json')],
    )

    written = prepare_viewer.unpack_static(archive, tmp_path)

    assert written == 1
    config = tmp_path / prepare_viewer.VIEWER_CONFIG_PATH
    assert not config.exists() and not config.is_symlink()


def test_refuses_to_escape_the_target(tmp_path):
    archive = build_archive(files=[(f'{STATIC}/../../../evil.txt', 'pwned')])

    with pytest.raises(RuntimeError, match='refusing to extract'):
        prepare_viewer.unpack_static(archive, tmp_path)

    assert not (tmp_path.parent / 'evil.txt').exists()


class StubRuntime:
    """Stands in for the podman/docker calls `main` makes."""

    def __init__(self, files=1):
        self.files = files
        self.pulled = False
        self.extracted_into = None

    def install(self, monkeypatch, image_present=True):
        monkeypatch.setattr(prepare_viewer, 'detect_runtime', lambda explicit=None: 'stub-runtime')
        monkeypatch.setattr(prepare_viewer, 'image_present', lambda runtime, image: image_present)
        monkeypatch.setattr(prepare_viewer, 'run', lambda cmd, **kw: self._pull())
        monkeypatch.setattr(prepare_viewer, 'extract_static', self._extract)
        return self

    def _pull(self):
        self.pulled = True

    def _extract(self, runtime, image, target):
        self.extracted_into = target
        for index in range(self.files):
            (target / f'file{index}.js').write_text('payload')
        (target / 'index.html').write_text('<html>')
        return self.files


def run_main(monkeypatch, tmp_path, extra_args=(), config_text='{"a": 1}'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = tmp_path / 'custom.json'
    if config_text is not None:
        config.write_text(config_text)
    target = tmp_path / 'static'
    args = ['prepare_viewer.py', '--target', str(target), '--config', str(config), *extra_args]
    monkeypatch.setattr('sys.argv', args)
    prepare_viewer.main()
    return target, config


def test_materializes_the_viewer_config(monkeypatch, tmp_path):
    StubRuntime().install(monkeypatch)

    target, config = run_main(monkeypatch, tmp_path, config_text='{"jsonlReaderTab": {}}')

    written = target / prepare_viewer.VIEWER_CONFIG_PATH
    assert written.is_file() and not written.is_symlink()
    assert written.read_text() == '{"jsonlReaderTab": {}}'


def test_pulls_only_when_the_image_is_missing(monkeypatch, tmp_path):
    present = StubRuntime().install(monkeypatch, image_present=True)
    run_main(monkeypatch, tmp_path)
    assert not present.pulled

    missing = StubRuntime().install(monkeypatch, image_present=False)
    run_main(monkeypatch, tmp_path / 'second')
    assert missing.pulled


def test_pull_flag_forces_a_pull(monkeypatch, tmp_path):
    stub = StubRuntime().install(monkeypatch, image_present=True)

    run_main(monkeypatch, tmp_path, extra_args=['--pull'])

    assert stub.pulled


def test_refuses_to_overwrite_without_force(monkeypatch, tmp_path):
    StubRuntime().install(monkeypatch)
    target, _ = run_main(monkeypatch, tmp_path)
    assert (target / 'index.html').exists()

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path)

    assert 'pass --force' in str(exit_info.value)
    # the previously extracted tree survives the refusal
    assert (target / 'index.html').exists()


def test_force_re_extracts(monkeypatch, tmp_path):
    StubRuntime(files=2).install(monkeypatch)
    target, _ = run_main(monkeypatch, tmp_path)
    (target / 'stale.js').write_text('stale')

    StubRuntime(files=1).install(monkeypatch)
    run_main(monkeypatch, tmp_path, extra_args=['--force'])

    # --force wipes the target, so leftovers of the previous extraction are gone
    assert not (target / 'stale.js').exists()
    assert not (target / 'file1.js').exists()
    assert (target / 'file0.js').exists()


def test_bad_config_does_not_wipe_an_existing_target(monkeypatch, tmp_path):
    """Regression: arguments must be validated before --force removes the target."""
    StubRuntime().install(monkeypatch)
    target, config = run_main(monkeypatch, tmp_path)
    assert (target / 'index.html').exists()
    config.unlink()

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path, extra_args=['--force'], config_text=None)

    assert 'not found' in str(exit_info.value)
    assert (target / 'index.html').exists()


def test_unavailable_runtime_does_not_wipe_an_existing_target(monkeypatch, tmp_path):
    """Regression: the runtime is resolved before --force removes the target."""
    StubRuntime().install(monkeypatch)
    target, _ = run_main(monkeypatch, tmp_path)

    # the real lookup, with nothing on PATH, fails exactly as a missing runtime would
    monkeypatch.setattr(prepare_viewer, 'detect_runtime', REAL_DETECT_RUNTIME)
    monkeypatch.setattr(prepare_viewer.shutil, 'which', lambda name: None)

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path, extra_args=['--force', '--runtime', 'nosuchtool'])

    assert 'not available on PATH' in str(exit_info.value)
    assert (target / 'index.html').exists()


def test_fails_when_the_image_has_no_viewer(monkeypatch, tmp_path):
    stub = StubRuntime().install(monkeypatch)
    monkeypatch.setattr(prepare_viewer, 'extract_static', lambda runtime, image, target: 0)

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path)

    assert 'no files found' in str(exit_info.value)
    assert stub.extracted_into is None
