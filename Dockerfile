# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app
# Copy the current directory contents into the container at /app
COPY . /app

RUN useradd -m json-stream \
    && usermod -aG root json-stream

USER json-stream

ENV HOME="/home/json-stream"
ENV XDG_CACHE_HOME="/home/json-stream/.cache"
ENV PYTHONPATH="/home/json-stream/.local/lib/python3.9/site-packages:${PYTHONPATH}"
ENV PATH="/home/json-stream/.local/bin:${PATH}"

# Install any needed dependencies specified in requirements.txt
RUN pip install -r requirements.txt
RUN ipython kernel install --name "python3" --user
# Run server.py when the container launches \
ENTRYPOINT ["python", "/app/server.py"]
CMD ["/var/th2/config/custom.json"]