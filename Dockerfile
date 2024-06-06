# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app
# Copy the current directory contents into the container at /app
COPY . /app

RUN groupadd -r json-stream && useradd -r -g json-stream json-stream
ENV HOME="/home/json-stream"
RUN mkdir -p "${HOME}"

ENV HOME="/home/json-stream"
ENV PATH="${HOME}/.local/bin:${PATH}"
ENV XDG_CACHE_HOME="${HOME}/.cache"
ENV PYTHONPATH="${HOME}/.local/lib/python3.9/site-packages:${PYTHONPATH}"
ENV PIP_CONFIG_FILE="${HOME}/.pip/pip.conf"

# Install any needed dependencies specified in requirements.txt
RUN pip install -r requirements.txt
RUN ipython kernel install --name "python3" --user
# Run server.py when the container launches \

RUN chown -R json-stream "${HOME}"

USER json-stream

ENV HOME="/home/json-stream"
ENV PATH="${HOME}/.local/bin:${PATH}"
ENV XDG_CACHE_HOME="${HOME}/.cache"
ENV PYTHONPATH="${HOME}/.local/lib/python3.9/site-packages:${PYTHONPATH}"
ENV PIP_CONFIG_FILE="${HOME}/.pip/pip.conf"

ENTRYPOINT ["python", "/app/server.py"]
CMD ["/var/th2/config/custom.json"]