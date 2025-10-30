FROM jupyter/datascience-notebook:python-3.9

RUN echo "c.ServerApp.base_url = '/jupyter/'" >> /etc/jupyter/jupyter_server_config.py
RUN echo "c.MultiKernelManager.default_kernel_name = '.venv'" >> /etc/jupyter/jupyter_server_config.py
RUN echo 'source /home/jovyan/.venv/bin/activate' >> /home/jovyan/.bashrc

RUN python -m venv /home/jovyan/.venv
RUN source /home/jovyan/.venv/bin/activate && pip install --upgrade pip && pip install ipykernel && python -m ipykernel install --user --name=.venv --display-name 'Python (.venv)'
RUN cat /home/jovyan/.local/share/jupyter/kernels/.venv/kernel.json