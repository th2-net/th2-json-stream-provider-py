# th2-json-stream-provider

This python server is made to launch Jupyter Notebooks and get results from them.

## How to start json-stream-provider using th2-infra

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
