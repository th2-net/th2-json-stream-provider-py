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

"""Keeps the requirements files in step with what the code actually imports.

Nothing is installed here, the files and the sources are read. An import that no requirement
covers would only fail once someone sets the solution up from scratch, which is exactly the case
these tests stand in for.
"""

import ast
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent.parent
REQUIREMENTS = SCRIPTS_DIR / 'requirements.txt'
DEV_REQUIREMENTS = SCRIPTS_DIR / 'requirements-dev.txt'

# distributions whose import name differs from the name they are installed under
IMPORT_NAMES = {'pyyaml': 'yaml'}

# a built distributive is flat: server.py and json_stream_provider sit next to these scripts and
# the requirements are inlined, so the checks about the repository layout do not apply there
IS_DISTRIBUTIVE = (SCRIPTS_DIR / 'server.py').is_file()
repository_only = pytest.mark.skipif(IS_DISTRIBUTIVE,
                                     reason='the repository layout is flattened in a distributive')

# imported by neither the scripts nor the tests, they are run as programs or by the provider
NOT_IMPORTED_HERE = {'jupyterlab', 'aiohttp', 'aiohttp-swagger', 'aiojobs', 'ipykernel',
                     'papermill', 'nbclient', 'nbformat'}


def read_requirements(path: Path) -> set:
    """Returns the distribution names of a requirements file, following `-r` includes."""
    names = set()
    for raw in path.read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r'):
            included = line[2:].strip()
            names |= read_requirements((path.parent / included).resolve())
            continue
        for separator in ('~=', '==', '>=', '<=', '>', '<', '!='):
            if separator in line:
                line = line.split(separator, 1)[0]
                break
        names.add(line.strip().lower())
    return names


def importable_names(distributions: set) -> set:
    return {IMPORT_NAMES.get(name, name).replace('-', '_') for name in distributions}


def local_module_names() -> set:
    """Modules and packages that sit next to the scripts, they are never a requirement."""
    names = {path.stem for path in SCRIPTS_DIR.glob('*.py')}
    names |= {path.name for path in SCRIPTS_DIR.iterdir() if (path / '__init__.py').is_file()}
    return names | {'conftest'}


def third_party_imports(path: Path) -> set:
    local = local_module_names()
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split('.')[0])
    return {name for name in found
            if name not in sys.stdlib_module_names and name not in local}


SCRIPTS = sorted(SCRIPTS_DIR.glob('*.py'))
TESTS = sorted((SCRIPTS_DIR / 'tests').glob('*.py'))


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_every_script_import_is_a_requirement(script):
    covered = importable_names(read_requirements(REQUIREMENTS))

    assert third_party_imports(script) <= covered


@pytest.mark.parametrize('test_module', TESTS, ids=lambda p: p.name)
def test_every_test_import_is_a_dev_requirement(test_module):
    covered = importable_names(read_requirements(DEV_REQUIREMENTS))

    assert third_party_imports(test_module) <= covered


@repository_only
def test_the_provider_requirements_are_included():
    """The solution runs server.py, so its dependencies have to be installed as well."""
    root = read_requirements(REPO_ROOT / 'requirements.txt')

    assert root
    assert root <= read_requirements(REQUIREMENTS)


@repository_only
def test_the_provider_requirements_are_included_by_reference():
    """Copying them would drift, dependabot only watches the repository root."""
    lines = [line.strip() for line in REQUIREMENTS.read_text().splitlines()]

    assert '-r ../../requirements.txt' in lines


def test_jupyter_is_a_requirement():
    """It is started as a program rather than imported, so no import check would catch it."""
    assert 'jupyterlab' in read_requirements(REQUIREMENTS)


def test_dev_requirements_stay_light():
    """The default suite has to run without the provider and jupyter being installed."""
    dev = read_requirements(DEV_REQUIREMENTS)

    assert 'pytest' in dev
    assert dev.isdisjoint(NOT_IMPORTED_HERE)
