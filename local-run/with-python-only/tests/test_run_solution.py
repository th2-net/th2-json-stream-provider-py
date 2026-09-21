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

"""Tests for `run_solution.py`.

The configuration handling and the generated files are checked directly. Process supervision is
exercised with short lived python processes instead of the real servers, so the suite stays fast
and needs neither Jupyter nor the provider.
"""

import json
import sys
import textwrap
import time

import pytest
import yaml

import run_solution


def write_config(tmp_path, overrides=None, with_server=True):
    """Writes a config.yaml into `tmp_path` and returns its path."""
    config = {
        'host': '127.0.0.1',
        'ports': {'viewer': 8080, 'json-stream-provider': 8081, 'jupyter': 8082},
        'workspace': './workspace',
        'viewer': {'static': './static', 'config': './custom.json'},
    }
    config.update(overrides or {})
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(yaml.safe_dump(config))
    (tmp_path / 'custom.json').write_text('{"jsonlReaderTab": {}}')
    (tmp_path / 'static').mkdir(exist_ok=True)
    if with_server:
        (tmp_path / 'server.py').write_text('# stub provider\n')
    return config_path


class TestMergeDefaults:

    def test_fills_in_missing_sections(self):
        merged = run_solution.merge_defaults({})

        assert merged['host'] == '127.0.0.1'
        assert merged['ports']['viewer'] == 8080
        assert merged['kernel']['name'] == '.venv'

    def test_overlays_nested_keys_without_dropping_the_rest(self):
        merged = run_solution.merge_defaults({'ports': {'viewer': 9999}})

        assert merged['ports']['viewer'] == 9999
        # the sibling ports keep their defaults instead of disappearing
        assert merged['ports']['jupyter'] == 8082
        assert merged['ports']['json-stream-provider'] == 8081

    def test_keeps_falsy_overrides(self):
        merged = run_solution.merge_defaults({'jupyter': {'token': '', 'open-browser': False}})

        assert merged['jupyter']['token'] == ''
        assert merged['jupyter']['open-browser'] is False


class TestLoadSettings:

    def test_resolves_paths_against_the_config_file(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        assert settings.workspace == (tmp_path / 'workspace').resolve()
        assert settings.viewer_static == (tmp_path / 'static').resolve()
        # a distributive unpacked anywhere keeps working, nothing is relative to the cwd
        assert settings.workspace.is_absolute()

    def test_applies_defaults_for_absent_sections(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        assert settings.kernel_name == '.venv'
        assert settings.jupyter_base_url == '/jupyter/'
        assert settings.runtime_dir == (tmp_path / 'runtime').resolve()

    def test_workspace_subdirectories(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        assert settings.notebooks_dir == settings.workspace / 'notebooks'
        assert settings.results_dir == settings.workspace / 'results'
        assert settings.results_images_dir == settings.workspace / 'results' / 'images'
        assert settings.logs_dir == settings.workspace / 'logs'

    def test_missing_config_is_reported(self, tmp_path):
        with pytest.raises(SystemExit) as exit_info:
            run_solution.load_settings(tmp_path / 'absent.yaml')

        assert 'not found' in str(exit_info.value)

    def test_empty_config_falls_back_to_defaults(self, tmp_path):
        config_path = tmp_path / 'config.yaml'
        config_path.write_text('')
        (tmp_path / 'server.py').write_text('# stub\n')

        settings = run_solution.load_settings(config_path)

        assert settings.viewer_port == 8080
        assert settings.host == '127.0.0.1'

    def test_explicit_provider_script_wins(self, tmp_path):
        script = tmp_path / 'elsewhere' / 'server.py'
        script.parent.mkdir()
        script.write_text('# stub\n')
        config = write_config(tmp_path, {'json-stream-provider': {'script': './elsewhere/server.py'}})

        settings = run_solution.load_settings(config)

        assert settings.provider_script == script.resolve()

    def test_provider_script_is_autodetected_next_to_the_config(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        assert settings.provider_script == (tmp_path / 'server.py').resolve()

    def test_provider_script_is_autodetected_in_the_repository_root(self, tmp_path):
        # mirrors the checkout: config lives in local-run/with-python-only, server.py two up
        nested = tmp_path / 'local-run' / 'with-python-only'
        nested.mkdir(parents=True)
        (tmp_path / 'server.py').write_text('# stub\n')

        settings = run_solution.load_settings(write_config(nested, with_server=False))

        assert settings.provider_script == (tmp_path / 'server.py').resolve()

    def test_absent_provider_script_is_reported(self, tmp_path):
        with pytest.raises(SystemExit) as exit_info:
            run_solution.load_settings(write_config(tmp_path, with_server=False))

        assert 'server.py not found' in str(exit_info.value)

    def test_script_key_does_not_leak_into_the_provider_options(self, tmp_path):
        config = write_config(tmp_path, {'json-stream-provider': {'script': './server.py'}})

        settings = run_solution.load_settings(config)

        assert 'script' not in settings.provider_options


class TestGeneratedFiles:

    def test_creates_the_workspace_tree(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        run_solution.prepare_workspace(settings)

        for directory in (settings.notebooks_dir, settings.results_dir,
                          settings.results_images_dir, settings.logs_dir,
                          settings.jupyter_data_dir, settings.runtime_dir):
            assert directory.is_dir()

    def test_provider_config_points_at_the_workspace(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        assert written['notebooks'] == str(settings.notebooks_dir)
        assert written['results'] == str(settings.results_dir)
        assert written['results-images'] == str(settings.results_images_dir)
        assert written['logs'] == str(settings.logs_dir)

    def test_provider_config_carries_the_port(self, tmp_path):
        """Without this the provider would fall back to 8080 and collide with the viewer."""
        settings = run_solution.load_settings(
            write_config(tmp_path, {'ports': {'json-stream-provider': 9091}}))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        assert written['port'] == 9091

    def test_provider_config_passes_options_through(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path, {
            'json-stream-provider': {'cleanup-horizon-days': 7, 'out-of-use-engine-time': 60},
        }))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        assert written['cleanup-horizon-days'] == 7
        assert written['out-of-use-engine-time'] == 60
        assert 'script' not in written

    def test_provider_config_points_at_the_kernel_venv(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        assert written['virtual-environment-dir'] == str(settings.kernel_venv)
        assert written['python-kernel-name'] == '.venv'

    def test_provider_config_carries_the_host(self, tmp_path):
        """Without this the provider would bind every interface whatever `host` says."""
        settings = run_solution.load_settings(write_config(tmp_path, {'host': '127.0.0.1'}))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        assert written['host'] == '127.0.0.1'

    def test_log_config_key_does_not_leak_into_the_provider_options(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))
        run_solution.prepare_workspace(settings)

        written = json.loads(run_solution.write_provider_config(settings).read_text())

        # it travels through the environment, the provider would not understand it here
        assert 'log-config' not in written

    def test_log_config_is_written_next_to_the_provider_config(self, tmp_path):
        """That is where the provider looks for it, the same as /var/th2/config in a container."""
        (tmp_path / 'log4py.conf').write_text('[loggers]\nkeys=root\n')
        settings = run_solution.load_settings(
            write_config(tmp_path, {'json-stream-provider': {'log-config': './log4py.conf'}}))
        run_solution.prepare_workspace(settings)

        provider_config = run_solution.write_provider_config(settings)

        written = provider_config.parent / 'log4py.conf'
        assert written.is_file()
        assert written.read_text() == '[loggers]\nkeys=root\n'

    def test_absent_log_config_is_skipped(self, tmp_path):
        settings = run_solution.load_settings(
            write_config(tmp_path, {'json-stream-provider': {'log-config': './absent.conf'}}))
        run_solution.prepare_workspace(settings)

        provider_config = run_solution.write_provider_config(settings)

        # the provider falls back to its built-in configuration, which is better than crashing
        assert not (provider_config.parent / 'log4py.conf').exists()

    def test_viewer_config_is_written_where_the_viewer_fetches_it(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        written = run_solution.write_viewer_config(settings)

        assert written == settings.viewer_static / 'config' / 'th2' / 'custom.json'
        assert json.loads(written.read_text()) == {'jsonlReaderTab': {}}

    def test_missing_viewer_static_is_reported(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))
        (tmp_path / 'static').rmdir()

        with pytest.raises(SystemExit) as exit_info:
            run_solution.write_viewer_config(settings)

        assert 'prepare_viewer.py' in str(exit_info.value)


class TestCommands:

    def test_starts_the_three_servers(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        names = [name for name, _ in run_solution.build_commands(settings)]

        assert names == ['j-sp', 'viewer', 'jupyter']

    def test_provider_is_given_the_generated_config(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        command = dict(run_solution.build_commands(settings))['j-sp']

        assert command[1] == str(settings.provider_script)
        assert command[2] == str(settings.provider_config)

    def test_viewer_is_pointed_at_the_provider_port(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        command = dict(run_solution.build_commands(settings))['viewer']

        assert '--backend-port' in command
        assert command[command.index('--backend-port') + 1] == str(settings.provider_port)
        assert command[command.index('--directory') + 1] == str(settings.viewer_static)

    def test_jupyter_opens_the_workspace(self, tmp_path):
        """This is what makes the provider directories visible in Jupyter."""
        settings = run_solution.load_settings(write_config(tmp_path))

        command = dict(run_solution.build_commands(settings))['jupyter']

        assert f'--ServerApp.root_dir={settings.workspace}' in command

    def test_jupyter_defaults_to_the_registered_kernel(self, tmp_path):
        settings = run_solution.load_settings(write_config(tmp_path))

        command = dict(run_solution.build_commands(settings))['jupyter']

        assert '--MultiKernelManager.default_kernel_name=.venv' in command
        assert '--ServerApp.open_browser=False' in command

    def test_child_environment_shares_the_jupyter_data_dir(self, tmp_path):
        """The provider registers the kernel there and Jupyter has to list it from there."""
        settings = run_solution.load_settings(write_config(tmp_path))

        environment = run_solution.child_environment(settings)

        assert environment['JUPYTER_DATA_DIR'] == str(settings.jupyter_data_dir)
        assert environment['PYTHONUNBUFFERED'] == '1'



class TestKernelVenv:

    def test_reuses_an_environment_that_already_has_ipykernel(self, tmp_path, monkeypatch):
        settings = run_solution.load_settings(write_config(tmp_path))
        settings.kernel_venv.mkdir(parents=True)
        calls = []
        monkeypatch.setattr(run_solution.venv, 'create',
                            lambda *a, **kw: calls.append('create'))
        monkeypatch.setattr(run_solution.subprocess, 'run',
                            lambda cmd, **kw: calls.append(cmd) or _completed(0))

        run_solution.ensure_kernel_venv(settings)

        assert 'create' not in calls
        # only the import check runs, nothing is installed
        assert len(calls) == 1 and calls[0][-1] == 'import ipykernel'

    def test_installs_ipykernel_when_absent(self, tmp_path, monkeypatch):
        settings = run_solution.load_settings(write_config(tmp_path))
        calls = []
        monkeypatch.setattr(run_solution.venv, 'create',
                            lambda *a, **kw: calls.append('create'))
        monkeypatch.setattr(run_solution.subprocess, 'run',
                            lambda cmd, **kw: calls.append(cmd) or _completed(1))

        run_solution.ensure_kernel_venv(settings)

        assert 'create' in calls
        assert calls[-1][-1] == 'ipykernel'

    def test_installs_from_the_wheelhouse_when_given(self, tmp_path, monkeypatch):
        settings = run_solution.load_settings(write_config(tmp_path))
        wheelhouse = tmp_path / 'wheelhouse'
        calls = []
        monkeypatch.setattr(run_solution.venv, 'create', lambda *a, **kw: None)
        monkeypatch.setattr(run_solution.subprocess, 'run',
                            lambda cmd, **kw: calls.append(cmd) or _completed(1))

        run_solution.ensure_kernel_venv(settings, wheelhouse)

        install = calls[-1]
        assert '--no-index' in install
        assert install[install.index('--find-links') + 1] == str(wheelhouse)


def _completed(returncode):
    class Completed:
        pass

    result = Completed()
    result.returncode = returncode
    return result


class TestSupervisor:

    def make(self, tmp_path):
        return run_solution.Supervisor({**run_solution.os.environ}, cwd=tmp_path)

    def test_prefixes_the_output_of_each_child(self, tmp_path, capsys):
        supervisor = self.make(tmp_path)

        supervisor.start('alpha', [sys.executable, '-c', 'print("hello")'])
        supervisor.wait(poll_interval=0.05)
        supervisor.shutdown()

        assert '[alpha] hello' in capsys.readouterr().out

    def test_wait_returns_the_child_that_exited(self, tmp_path):
        supervisor = self.make(tmp_path)
        script = 'import time; time.sleep(30)'

        supervisor.start('long', [sys.executable, '-c', script])
        supervisor.start('short', [sys.executable, '-c', 'pass'])
        try:
            name, process = supervisor.wait(poll_interval=0.05)
            assert name == 'short'
            assert process.returncode == 0
        finally:
            supervisor.shutdown()

    def test_shutdown_stops_every_remaining_child(self, tmp_path):
        """One server exiting has to bring the other two down, not leave them orphaned."""
        supervisor = self.make(tmp_path)
        script = 'import time; time.sleep(30)'
        first = supervisor.start('first', [sys.executable, '-c', script])
        second = supervisor.start('second', [sys.executable, '-c', script])

        supervisor.shutdown()

        assert first.poll() is not None
        assert second.poll() is not None

    def test_kills_a_child_that_ignores_the_termination(self, tmp_path, capsys):
        supervisor = self.make(tmp_path)
        stubborn = textwrap.dedent('''
            import signal, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print("ready", flush=True)
            time.sleep(30)
        ''')

        process = supervisor.start('stubborn', [sys.executable, '-c', stubborn])
        deadline = time.monotonic() + 10
        while 'ready' not in capsys.readouterr().out and time.monotonic() < deadline:
            time.sleep(0.05)
        supervisor.shutdown(timeout=1.0)

        assert process.poll() is not None


class TestUrls:

    def test_reports_a_reachable_host_when_bound_to_all_interfaces(self, tmp_path, capsys):
        settings = run_solution.load_settings(write_config(tmp_path, {'host': '0.0.0.0'}))

        run_solution.print_urls(settings)

        printed = capsys.readouterr().out
        # 0.0.0.0 is not an address a browser can open
        assert 'http://127.0.0.1:8080/' in printed
        assert 'http://0.0.0.0' not in printed

    def test_includes_the_jupyter_token_when_set(self, tmp_path, capsys):
        settings = run_solution.load_settings(
            write_config(tmp_path, {'jupyter': {'token': 'secret'}}))

        run_solution.print_urls(settings)

        assert '?token=secret' in capsys.readouterr().out
