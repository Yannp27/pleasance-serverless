# RunPod Serverless Dockerfile

FROM runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install runpod

# Copy agent code
COPY proxy_client.py .
COPY serverless_handler.py .

# RunPod expects handler at /app
CMD ["python", "-u", "serverless_handler.py"]
