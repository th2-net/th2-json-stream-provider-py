# Local run with Python only

Runs the same solution as [`../with-jupyter-notebook`](../with-jupyter-notebook) —
th2-json-stream-provider (`j-sp`), th2-rpt-viewer and Jupyter behind a single entry point — but
with plain Python processes instead of containers, and packages it as a portable distributive.

A container runtime is needed **once, at build time only**: th2-rpt-viewer is published solely as a
docker image, so its JS static has to be extracted from there. Nothing at run time uses docker.

## Layout

| Path | Description |
| --- | --- |
| `prepare_viewer.py` | extracts the th2-rpt-viewer JS static out of its docker image |
| `th2-rpt-viewer/custom.json` | viewer configuration, copied into the extracted static |
| `th2-rpt-viewer/static/` | the extracted viewer, produced by `prepare_viewer.py` (git-ignored) |
| `tests/` | pytest suite for the scripts of this directory |
| `requirements-dev.txt` | dependencies for running the tests |

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

## Requirements

* Python 3.12
* `podman` or `docker`, for `prepare_viewer.py` only
* network access to `ghcr.io` on the first extraction
