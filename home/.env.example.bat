@echo off
chcp 65001 >nul
@rem --- дом: скопируйте в env.bat и заполните ---
set DATABASE_URL=postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/cs_prices
set CLOUD_URL=https://34-123-45-67.sslip.io
set CLOUD_TOKEN=тот-же-токен-что-API_TOKEN-в-облаке
set SYNC_INTERVAL=60
set API_PORT=8080
