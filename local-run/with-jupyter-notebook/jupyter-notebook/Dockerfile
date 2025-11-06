FROM jupyterhub/singleuser:5.2.1

RUN python -m venv /home/jovyan/.venv
RUN source /home/jovyan/.venv/bin/activate && \
    pip install --upgrade pip && \
    pip install ipykernel && \
    python -m ipykernel install --user --name=.venv --display-name 'Python (.venv)'

RUN echo "c.ServerApp.base_url = '/jupyter/'" >> /etc/jupyter/jupyter_server_config.py && \
    echo "c.MultiKernelManager.default_kernel_name = '.venv'" >> /etc/jupyter/jupyter_server_config.py && \
    echo 'source /home/jovyan/.venv/bin/activate' >> /home/jovyan/.bashrc