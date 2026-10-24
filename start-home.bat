@echo off
chcp 65001 >nul
rem Запуск домашней части: синхронизация с облаком + API/графики на http://127.0.0.1:8080
cd /d "%~dp0"
if not exist home\env.bat (
  echo Создайте home\env.bat по образцу home\.env.example.bat
  pause
  exit /b 1
)
call home\env.bat
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements-home.txt
)
.venv\Scripts\python -m home
