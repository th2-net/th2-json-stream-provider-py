FROM jupyter/datascience-notebook:python-3.9

RUN echo "c.ServerApp.base_url = '/jupyter/'" >> /etc/jupyter/jupyter_server_config.py

ENV PYTHON_SHARED_LIB_PATH="${HOME}/python/lib"

RUN mkdir -p "${PYTHON_SHARED_LIB_PATH}"
ENV PYTHONPATH="${PYTHONPATH}:${PYTHON_SHARED_LIB_PATH}"
ENV PIP_TARGET="${PYTHON_SHARED_LIB_PATH}"