# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app
# Copy the current directory contents into the container at /app
COPY . /app

# groupadd --system - create a system account
# useradd --system - create a system account
# useradd --gid - name or ID of the primary group of the new account
# usermod --append - append the user to the supplemental GROUPS mentioned by the -G/--groups option without removing the user from other groups
# usermod --groups - new list of supplementary GROUPS
RUN groupadd --system json-stream && useradd --system --gid json-stream --uid 1000 json-stream && usermod --append --groups users json-stream
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

RUN chown -R json-stream "${HOME}" && chmod -R g=u "${HOME}"

USER json-stream

ENV HOME="/home/json-stream"
ENV PATH="${HOME}/.local/bin:${PATH}"
ENV XDG_CACHE_HOME="${HOME}/.cache"
ENV PYTHONPATH="${HOME}/.local/lib/python3.9/site-packages:${PYTHONPATH}"
ENV PIP_CONFIG_FILE="${HOME}/.pip/pip.conf"

ENTRYPOINT ["python", "/app/server.py"]
CMD ["/var/th2/config/custom.json"]