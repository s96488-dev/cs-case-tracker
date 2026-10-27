# Cloud collector image.
FROM python:3.12-slim
WORKDIR /app
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY common ./common
COPY cloud ./cloud
ENV BUFFER_PATH=/data/buffer.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "cloud.server:app", "--host", "0.0.0.0", "--port", "8000"]
