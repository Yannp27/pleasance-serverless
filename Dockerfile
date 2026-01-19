# RunPod Serverless Dockerfile

FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy handler
COPY proxy_client.py serverless_handler.py ./

# RunPod handler entrypoint
CMD ["python", "-u", "serverless_handler.py"]
