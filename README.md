# th2-json-stream-provider (j-sp) (0.0.5)

This python server is made to launch Jupyter notebooks (*.ipynb) and get results from them.

## Configuration:

### custom:

* `notebooks` (Default value: /home/jupyter-notebook/) - path to the directory with notebooks. `j-sp` search files with `ipynb` extension recursively in the specified folder.
* `results` (Default value: /home/jupyter-notebook/results) - path to the directory for run results. `j-sp` resolves result file with `jsonl` extension against specified folder.
* `logs` (Default value: /home/jupyter-notebook/logs) - path to the directory for run logs. `j-sp` puts run logs to specified folder.
* `out-of-use-engine-time` (Default value: 3600) - out-of-use time interval in seconds. `j-sp` unregisters engine related to a notebook when user doesn't run the notebook more than this time

### mounting:

* `/home/json-stream/` - is home folder for j-sp. It can contain: installed python library, pip.conf and other useful files for run notebooks.
* `/home/jupyter-notebook/` - is shared folder between this tool and any source of notebooks.
In general j-sp should be run with jupyter notebook/lab/hub. User can develop / debug a notebook in the jupyter and run via j-sp

### service:

th2-rpt-viewer since the `5.2.7-TH2-5142-9348403860` version can interact with j-sp by the `http://<cluster>:<port>/th2-<schema>/json-stream-provider/` URL

### resources:

j-sp use pod resources to run notebooks. Please calculate required resource according to solving issues.

```yaml
apiVersion: th2.exactpro.com/v2
kind: Th2Box
metadata:
  name: json-stream-provider
spec:
  imageName: ghcr.io/th2-net/th2-json-stream-provider-py
  imageVersion: 0.0.2
  type: th2-rpt-data-provider
  customConfig:
    notebooks: /home/jupyter-notebook/
    results: /home/jupyter-notebook/j-sp/results/
    logs: /home/jupyter-notebook/j-sp/logs/
    out-of-use-engine-time: 3600
  mounting:
    - path: /home/jupyter-notebook/
      pvcName: jupyter-notebook
    - path: /home/json-stream/
      pvcName: json-stream-provider
  resources:
    limits:
      memory: 1000Mi
      cpu: 1000m
    requests:
      memory: 100Mi
      cpu: 100m
  service:
    enabled: true
    ingress:
      urlPaths:
        - '/json-stream-provider/'
    clusterIP:
      - name: backend
        containerPort: 8080
        port: 8080
```

## Requirements for Jupyter's notebooks

* Cell tagged `parameters` (required)
  * this cell should be listed parameters only.
  * parameters could have typing and value, but value must be constant and have primitive type like boolean, number, string.
  * required parameters:
    * `output_path` - path to [JSONL](https://jsonlines.org/) file. Server considers a content of this file as run results. 
* Cell with dependencies (optional) - server doesn't include third-party packages by default. 
You can install / uninstall packages required for your code in one of cells. All installed packages are shared between runs any notebook.
Installation example: 
  ``` python
  import sys
  !{sys.executable} -m pip install <package_name>==<package_version>
  ```

## local run

### run th2-rpt-viewer, th2-json-provider, jupyter-notebook are proxied by nginx

You can put required files for you jupyter notebooks into `local-run/with-jupyter-notebook/user_data` folder. Please note that this folder is read-only for containers.<br>
Or you can mount own folder by changing value of `USER_DATA_DIR` environment variable in the `local-run/with-jupyter-notebook/.evn` file.<br>
Or change the `local-run/with-jupyter-notebook/compose.yml` file. Please note you should mount the same dictionary by the same path to `jupyter_notebook` and `json_stream_provider` services.

#### provide permission for `local-run/with-jupyter-notebook/user_data` folder
`jupyter-notebook` and `json-stream-provider` use user from default linux `users` group. 
It means that:
* `user_data` folder internal folder should have `rwx` permission for `users` group.
* files in `user_data` folder should have `rw` permission for `users` group.

Perhaps you will need sudo permission for the next commands

```shell
cd local-run/with-jupyter-notebook
chgrp -R users user_data/
chmod -R g=u user_data/
```

#### start command
```shell
cd local-run/with-jupyter-notebook
docker compose up --build
```
#### clean command
```shell
cd local-run/with-jupyter-notebook
docker compose rm --force --volumes --stop
docker compose down --volumes
docker compose build
```
#### application URLs:
* http://localhost - th2-rpt-viewer
* http://localhost/jupyter - jupyter-notebook. You can authorise via token printed into `jupyter_notebook` logs:
  ```shell
  cd local-run/with-jupyter-notebook
  docker compose logs jupyter_notebook | grep 'jupyter/lab?token=' | tail -1 | cut -d '=' -f 2
  ```

## Release notes:

### 0.0.7

* j-sp generates cookies with `engine_user_id` field to identify user for creating unique python engine.
* Custom engine holds separate papermill notebook client for each `engine_user_id` and file combination.
* update local run with jupyter-notebook:
  * updated th2-rpt-viewer:
    * added pycode parameter type
    * added ability to save/load presets for notebooks
    * compare mode was changed to have ability to launch notebooks
    * added ability to move to nearest chunk in compare mode
    * added ability to off parameter in notebook

### 0.0.6

* Added papermill custom engine to reuse it for notebook execution.
  A separate engine is registered for each notebook and unregistered after 1 hour out-of-use time by default.
* update local run with jupyter-notebook:
  * updated th2-rpt-viewer:
    * `JSON Reader` page pulls execution status each 50 ms instead of 1 sec
    * `JSON Reader` page now uses virtuoso for rendering lists
    * `JSON Reader` page now has search, it's values could be loaded from `json` file containing array of objects containing `pattern` and `color` fields for searching content. Execution of notebook could create such file and it will be loaded into UI if it would be created in path of `customization_path` parameter.
    * Added ability to create multiple `JSON Reader` pages.
    * `JSON Reader` page now has compare mode.

### 0.0.5

* added `umask 0007` to `~/.bashrc` file to provide rw file access for `users` group
* added `/file` request for loading content of single jsonl file
* removed ability to get any file from machine via `/file` REST APIs
* added sorting on requests `/files/notebooks` and `/files/results`
* added `/files/all` request to list all files in `/notebooks` and `/results/` directories
* added `convert_parameter` function for parsing parameter depending on it's type
* update local run with jupyter-notebook:
  * updated th2-rpt-viewer:
    * added option to change default view type of result group
    * added display of #display-table field in Table view type
    * added option to view last N results of Notebook
    * added validation of Notebook's parameters
    * added timestamp and file path parameter types
    * fixed clearing of Notebook's parameters on run
    * increased width of parameters' inputs
  * updated compose:
    * changed use data access from `ro` to `rw`

### 0.0.4

* added `${HOME}/python/lib` into `PYTHONPATH` environment variable
* update local run with jupyter-notebook:
  * updated jupyter-notebook Dockerfile: 
    * used `jupyter/datascience-notebook:python-3.9`
    * defined `PYTHONPATH`, `PIP_TARGET` environment variables
  * updated compose:
    * added `python_lib` volume
* added saving of current tasks
  * task contains status(success, failed, in progress) and id using which task can be stopped
* added end-point `/stop` for stopping requested task
* updated end-point `/result` it now requests task by id and returns file, reason for failed run or informs that task is 'in progress' depending on task status

### 0.0.3

* Added `json-stream` user to users group
* Added docker compose for local run