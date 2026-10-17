# Local run with Python only

Runs the same solution as [`../with-jupyter-notebook`](../with-jupyter-notebook) —
th2-json-stream-provider (`j-sp`), th2-rpt-viewer and Jupyter behind a single entry point — but
with plain Python processes instead of containers, and packages it as a portable distributive.

A container runtime is needed **once, at build time only**: th2-rpt-viewer is published solely as a
docker image, so its JS static has to be extracted from there. Nothing at run time uses docker.

## Layout

| Path | Description |
| --- | --- |
| `run_solution.py` | configures and launches the whole solution |
| `build_distributive.py` | packs the solution into a portable archive |
| `config.yaml` | configuration of `run_solution.py` |
| `prepare_viewer.py` | extracts the th2-rpt-viewer JS static out of its docker image |
| `serve_static.py` | serves the viewer and proxies its API calls to th2-json-stream-provider |
| `th2-rpt-viewer/custom.json` | viewer configuration, copied into the extracted static |
| `json-stream-provider/log4py.conf` | provider logging configuration |
| `th2-rpt-viewer/static/` | the extracted viewer, produced by `prepare_viewer.py` (git-ignored) |
| `requirements.txt` | dependencies of the solution |
| `dist/` | built archives, produced by `build_distributive.py` (git-ignored) |
| `tests/` | pytest suite for the scripts of this directory |
| `requirements-dev.txt` | dependencies for running the tests |
| `workspace/` | notebooks, results and logs, created on the first start (git-ignored) |
| `kernel-venv/` | virtual environment the notebooks run in (git-ignored) |
| `runtime/`, `jupyter-data/` | generated configuration and kernel registration (git-ignored) |

## `prepare_viewer.py`

Extracts the viewer document root (`/usr/share/nginx/html`) from
`ghcr.io/th2-net/th2-rpt-viewer:5.2.12` into `th2-rpt-viewer/static/`, which is later served as
plain files. The container filesystem is streamed and unpacked on the fly, so no intermediate
archive is written to disk, and the created container is removed afterwards.

```bash
python3 prepare_viewer.py
```

Run it from any working directory — all default paths resolve relative to the script itself.

### Options

| Option | Default | Description |
| --- | --- | --- |
| `--image` | `ghcr.io/th2-net/th2-rpt-viewer:5.2.12` | viewer image to extract |
| `--runtime` | `podman`, then `docker` | container runtime to use |
| `--target` | `th2-rpt-viewer/static` | directory to unpack the viewer into |
| `--config` | `th2-rpt-viewer/custom.json` | viewer config placed into the target |
| `--pull` | off | pull the image even when it is already present locally |
| `--force` | off | re-extract into a non-empty target (wipes it first) |

Without `--pull` the image is pulled only when it is not available locally, so repeated builds and
offline builds do not hit the registry.

### The viewer configuration

Inside the image `config/th2/custom.json` is a symlink to `/var/th2/config/custom.json`, which the
compose setup satisfies with a bind mount of `th2-rpt-viewer/`. There is nothing to mount here, so
the extraction skips that symlink and copies `th2-rpt-viewer/custom.json` into its place as a real
file. Edit `th2-rpt-viewer/custom.json` and re-run with `--force` to change the viewer settings, or
edit `th2-rpt-viewer/static/config/th2/custom.json` directly for a throwaway change — it is
overwritten on the next extraction.

### Upgrading the viewer

```bash
python3 prepare_viewer.py --image ghcr.io/th2-net/th2-rpt-viewer:<version> --pull --force
```

Note that th2-rpt-viewer talks to `j-sp` through the relative `json-stream-provider/...` URL, which
the static server proxies. If a future viewer version changes that URL, the proxy prefix has to be
changed to match.

## `run_solution.py`

Launches Jupyter, `j-sp` and the viewer together, the equivalent of `docker compose up` for this
setup.

```bash
pip install -r requirements.txt
python3 prepare_viewer.py     # once, needs docker/podman
python3 run_solution.py       # uses ./config.yaml
```

It generates the provider `custom.json` out of `config.yaml`, copies the viewer configuration into
the static, creates the notebook virtual environment on the first start, and then runs the three
servers as child processes. Their output is streamed with a `[j-sp]`, `[viewer]` or `[jupyter]`
prefix. Ctrl+C, or any one of them exiting, stops all three.

| Option | Description |
| --- | --- |
| `--config` | yaml configuration to use (default: `config.yaml` next to the script) |
| `--wheelhouse` | install `ipykernel` from this directory instead of from the network |
| `--skip-kernel-venv` | do not create or check the notebook virtual environment |

### Configuration

See the comments in [`config.yaml`](config.yaml). Relative paths are resolved against the directory
holding the configuration file, so the solution can be unpacked and run anywhere.

### One workspace

`workspace` is the single root of everything: `notebooks/`, `results/`, `results/images/` and
`logs/`. `j-sp` is pointed at exactly those directories and Jupyter is opened on their parent,
which is what makes **every directory the provider uses visible in Jupyter** — no mounts or
symlinks, unlike the compose setup.

The kernel needs the same treatment. `j-sp` registers it itself, but a virtual environment created
from inside another one inherits the packages of the base interpreter rather than of the
environment `j-sp` runs in, so `ipykernel` would be missing. `run_solution.py` therefore creates
the notebook environment up front and `j-sp` reuses it. Both processes also share a
`JUPYTER_DATA_DIR` inside the solution, so the kernel `j-sp` registers is the kernel Jupyter lists,
and nothing is written to `~/.local/share/jupyter`.

### Logging

`j-sp` reads `log4py.conf` from the directory of the configuration file it is given, the same way
it picks both up from `/var/th2/config` inside a container. `run_solution.py` therefore copies
`json-stream-provider/log4py.conf` next to the generated `custom.json`. Edit the source file and
restart to change the provider log level; without it `j-sp` falls back to its built-in `DEBUG`
configuration.

### Known limitations

* An empty `jupyter.token` disables Jupyter authentication. That is acceptable while bound to
  `127.0.0.1`, but set a token before changing `host`.

## `build_distributive.py`

Packs everything into a portable archive: the provider, the extracted viewer, the launcher, the
configuration and the tests. Unpack it anywhere, install the requirements and run it — the paths
in `config.yaml` are relative to the configuration file, and `run_solution.py` finds `server.py`
next to itself.

```bash
python3 build_distributive.py                 # ./dist/th2-json-stream-provider-local-run-<version>.tar.gz
python3 build_distributive.py --with-wheels   # adds an offline install
python3 build_distributive.py --zip           # also builds a .zip
```

It extracts the viewer first when it is missing, so a clean checkout needs only this one command.
The `-r` include of `requirements.txt` is inlined on the way in, because a distributive has no
directory above it. The version comes from `package_info.json`.

| Option | Default | Description |
| --- | --- | --- |
| `--output` | `./dist` | directory to write the archive into |
| `--version` | `package_info.json` | version of the distributive |
| `--with-wheels` | off | include a wheelhouse for installing without a network |
| `--zip` | off | also build a `.zip` archive |
| `--skip-viewer` | off | fail instead of extracting the viewer when it is missing |
| `--runtime` | autodetected | container runtime for extracting the viewer |

### Using a distributive

```bash
tar -xzf th2-json-stream-provider-local-run-<version>.tar.gz
cd th2-json-stream-provider-local-run-<version>
pip install -r requirements.txt
python3 run_solution.py
```

`pytest -m integration` inside the unpacked directory starts the solution, runs the bundled
`example.ipynb` through the viewer and checks the results, which is a quick way to confirm the
deployment works.

### Offline installs

`--with-wheels` adds a `wheelhouse/` of every dependency, roughly 50 MB, installed with:

```bash
pip install --no-index --find-links wheelhouse -r requirements.txt
python3 run_solution.py --wheelhouse wheelhouse
```

The wheels are built for the python version and the platform that produced them — installing them
on a different python minor version fails with `No matching distribution found`, because the
compiled wheels carry a `cpXY` tag. `wheelhouse/BUILT-FOR.txt` records the target; build the
distributive on an interpreter matching the machines it is meant for.

## `serve_static.py`

Serves the extracted viewer and proxies its API calls to `j-sp`, replacing the nginx reverse proxy
of the compose based setup. th2-rpt-viewer requests the provider through the relative
`json-stream-provider/...` URL, so everything under that prefix is forwarded to `j-sp` with the
prefix stripped, and everything else is served from the static directory.

```bash
python3 serve_static.py --port 8080 --backend-port 8081 --directory th2-rpt-viewer/static
python3 serve_static.py 8080 8081 th2-rpt-viewer/static   # positional form
```

### Options

| Option | Default | Description |
| --- | --- | --- |
| `--port` | `8080` | port to listen on |
| `--backend-host` | `127.0.0.1` | host th2-json-stream-provider listens on |
| `--backend-port` | `8081` | port th2-json-stream-provider listens on |
| `--bind` | `0.0.0.0` | address to bind to |
| `--directory` | required | directory with the th2-rpt-viewer static |
| `--prefix` | `/json-stream-provider` | URL prefix proxied to the provider |

The provider port must match the `port` of the `j-sp` `custom.json`.

`GET`, `HEAD` and `POST` are proxied — `POST` is what the viewer uses to start (`/execute`) and
stop (`/stop`) notebook runs. Hop-by-hop headers are re-created for each hop, everything else,
including the `engine_user_id` cookie the provider sets, is passed through unchanged.

## Tests

The scripts of this directory are covered by a pytest suite. It needs neither a container runtime
nor a running `j-sp`: the container archive and the provider are stubbed.

```bash
pip install -r requirements-dev.txt
pytest
```

The default suite needs neither `j-sp` nor Jupyter installed, so `requirements-dev.txt` stays
light on purpose.

Two further suites are opt-in, because they need more than the sources.

`-m integration` starts the real solution, runs `example.ipynb` through the viewer's proxy and
reads its results back through Jupyter. It needs the full requirements and the extracted viewer,
and skips itself when either is missing. It also runs inside an unpacked distributive, which makes
it a quick way to confirm a deployment.

`-m docker` extracts the real th2-rpt-viewer image rather than a stubbed one. It is the only check
that would notice a new viewer version moving its document root, dropping the configuration
symlink, or renaming the `json-stream-provider/...` URL the proxy is built around. It needs podman
or docker and skips itself when neither is available.

```bash
pytest -m integration
pytest -m docker
```

## Requirements

* Python 3.12
* `pip install -r requirements.txt`
* `podman` or `docker`, for `prepare_viewer.py` only
* network access to `ghcr.io` on the first extraction

`requirements.txt` includes the repository root `requirements.txt` by reference rather than
copying it, so the dependabot updates of `j-sp` itself apply here too. On top of those it adds
`jupyterlab`, `PyYAML` and `requests`. `build_distributive.py` flattens the include, because a
distributive has no directory above it.

The notebook environment is separate and is created by `run_solution.py`, see
[One workspace](#one-workspace). Packages a notebook needs are installed into it from the notebook
itself, as in the compose setup.
