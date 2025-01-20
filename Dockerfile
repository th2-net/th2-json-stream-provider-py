# Use an official Python runtime as a parent image
FROM python:3.11.6-slim

# Set the working directory in the container
WORKDIR /app
# Copy requirements.txt into the container at /app
COPY requirements.txt /app/

# groupadd --system - create a system account
# useradd --system - create a system account
# useradd --gid - name or ID of the primary group of the new account
RUN useradd --system --gid users --uid 1000 json-stream

ENV TH2_CFG_DIR="/app/var/th2/config/"
ENV HOME="/home/json-stream"
ENV PATH="${HOME}/.local/bin:${PATH}"
ENV XDG_CACHE_HOME="${HOME}/.cache"
ENV PIP_CONFIG_FILE="${HOME}/.pip/pip.conf"
ENV PYTHONPATH="${HOME}/.local/lib/python3.9/site-packages"

RUN mkdir -p "${HOME}" "${TH2_CFG_DIR}"

# Install any needed dependencies specified in requirements.txt
RUN pip install -r requirements.txt
RUN ipython kernel install --name "python3" --user
# Run server.py when the container launches \

RUN chown -R json-stream "${HOME}" && chmod -R g=u "${HOME}" \
    && chown -R json-stream "${TH2_CFG_DIR}" && chmod -R g=u "${TH2_CFG_DIR}"

USER json-stream

ENV HOME="/home/json-stream"
ENV PATH="${HOME}/.local/bin:${PATH}"
ENV XDG_CACHE_HOME="${HOME}/.cache"
ENV PYTHON_SHARED_LIB_PATH="${HOME}/python/lib"
ENV PYTHON_LOCAL_LIB_PATH="${HOME}/.local/lib/python3.9/site-packages"
ENV PYTHONPATH="${PYTHONPATH}:${PYTHON_LOCAL_LIB_PATH}:${PYTHON_SHARED_LIB_PATH}"
ENV PIP_CONFIG_FILE="${HOME}/.pip/pip.conf"

RUN mkdir -p "${PYTHON_SHARED_LIB_PATH}"
RUN echo 'umask 0007' >> "${HOME}/.bashrc"

# Copy the json_stream_provider module into the container at /app
COPY json_stream_provider /app/json_stream_provider
# Copy the destributive files into the container at /app
COPY LICENSE NOTICE README.md package_info.json server.py /app/

ENTRYPOINT ["python", "/app/server.py"]
CMD ["/var/th2/config/custom.json"]