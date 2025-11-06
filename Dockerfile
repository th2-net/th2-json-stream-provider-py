# Use an official Python runtime as a parent image
FROM python:3.12.9-slim

# Set the working directory in the container
WORKDIR /app
# Copy requirements.txt into the container at /app
COPY requirements.txt /app/

ENV HOME="/home/json-stream"
RUN mkdir -p "${HOME}"

# Install any needed dependencies specified in requirements.txt
RUN pip install -r requirements.txt

# create sim links for compatible to jupyter python
RUN mkdir -p /opt/conda/bin && \
    ln -s /usr/local/bin/python /opt/conda/bin/python && \
    ln -s /usr/local/bin/pip /opt/conda/bin/pip

ENV HOME="/home/json-stream"
RUN echo 'umask 0007' >> "${HOME}/.bashrc"

# Copy the json_stream_provider module into the container at /app
COPY json_stream_provider /app/json_stream_provider
# Copy the destributive files into the container at /app
COPY LICENSE NOTICE README.md package_info.json server.py /app/

ENTRYPOINT ["python", "/app/server.py"]
CMD ["/var/th2/config/custom.json"]