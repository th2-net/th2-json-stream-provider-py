# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN ipython kernel install --name "python3" --user
# Run server.py when the container launches \
ENTRYPOINT ["python", "server.py"]
CMD ["/var/th2/config/custom.json"]