# th2-json-stream-provider (j-sp) (0.0.2)

This python server is made to launch Jupyter notebooks (*.ipynb) and get results from them.

## Configuration:

### custom:

* `notebooks` **_??? default version ???_** - path to the directory with notebooks. `j-sp` search files with `ipynb` extension recursively in the specified folder. 
* `results` **_??? default version ???_** - path to the directory for run results. `j-sp` resolves result file with `jsonl` extension against specified folder.
* `logs` **_??? default version ???_** - path to the directory for run logs. `j-sp` puts run logs to specified folder.

### mounting:

* `/home/json-stream/` - is home folder for j-sp. It can contain: installed python library, pip.conf and other useful files for run notebooks.    
* `/home/jupyter-notebook/` - is shared folder between this tool and any source of notebooks. 
In general j-sp should be run with jupyter notebook/lab/hub. User can develop / debug a notebook in the jupyter and run via j-sp

### service:

th2-rpt-viewer since the `???` version can interact with j-sp by the `http://<cluster>:<port>/th2-<schema>/json-stream-provider/` URL 

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

## How to start th2-json-stream-provider using th2-infra

1. Have Jupyter Notebooks running.
2. Make CR similar to [example](example-cr.yaml).
3. Install needed libraries in provider's pod.
4. Use json-stream-provider from rpt-data-viewer or using services like Postman or similar service.

## How to setup json-stream-provider's CR file

- In customConfig there are 3 fields that provider accepts:
  - notebooks - path to directory that contains notebooks that you would like to execute.
  - results - path to directory that will contain resulting files from your runs.
  - logs - path to directory that will contain log files from your runs.
- In mounting you need to specify 2 pvc:
  - First should have path in which contains directories from customConfig. It could be same as notebook's path.
  - Second path must be /home/json-stream/ this is directory that provider will use.
