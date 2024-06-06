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
  imageName: nexus.exactpro.com:18000/th2-json-stream-provider-py
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

## Release notes:

### 0.0.3

* Added `json-stream` user to users group