# Home backend image (used by the demo; on Windows the home side runs natively via start-home.bat).
FROM python:3.12-slim
WORKDIR /app
COPY requirements-home.txt .
RUN pip install --no-cache-dir -r requirements-home.txt
COPY common ./common
COPY home ./home
ENV API_HOST=0.0.0.0
EXPOSE 8080
CMD ["python", "-m", "home"]
