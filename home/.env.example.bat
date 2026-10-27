@echo off
chcp 65001 >nul
@rem --- home: copy to env.bat and fill in ---
set DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/cs_prices
set CLOUD_URL=https://34-123-45-67.sslip.io
set CLOUD_TOKEN=same-token-as-API_TOKEN-in-the-cloud
set SYNC_INTERVAL=60
set API_PORT=8080
