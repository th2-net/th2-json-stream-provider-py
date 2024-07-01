# th2-json-stream-provider (j-sp) (0.0.3)

This python server is made to launch Jupyter notebooks (*.ipynb) and get results from them.

## Configuration:

### custom:

* `notebooks` (Default value: /home/jupyter-notebook/) - path to the directory with notebooks. `j-sp` search files with `ipynb` extension recursively in the specified folder.
* `results` (Default value: /home/jupyter-notebook/results) - path to the directory for run results. `j-sp` resolves result file with `jsonl` extension against specified folder.
* `logs` (Default value: /home/jupyter-notebook/logs) - path to the directory for run logs. `j-sp` puts run logs to specified folder.

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

#### start command
```shell
cd local-run/with-jupyter-notebook
docker compose up
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

### 0.0.5

* added `/file` request for loading content of single jsonl file
* changed `replacePathServerToLocal` to return empty string in case of not starting with `./notebooks` or `./results`

#### Frontend changes

* added option to change default view type of result group
* added display of #display-table field in Table view type
* added option to view last N results of Notebook
* added validation of Notebook's parameters
* fixed clearing of Notebook's parameters on run
* increased width of parameters' inputs

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