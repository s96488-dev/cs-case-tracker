@echo off
chcp 65001 >nul
rem Запуск домашней части: синхронизация с облаком + API/графики на http://127.0.0.1:8080
rem С ключом --loop (так запускает автозапуск) сервер перезапускается, если упал.
cd /d "%~dp0"
if not exist home\env.bat (
  echo Создайте home\env.bat по образцу home\.env.example.bat
  if /i not "%~1"=="--loop" pause
  exit /b 1
)
call home\env.bat
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements-home.txt
)
rem Подтягиваем свежую версию из GitHub, если папка — клон репозитория.
if exist .git (
  git pull --ff-only
  .venv\Scripts\pip install -q -r requirements-home.txt
)
:run
.venv\Scripts\python -m home
if /i "%~1"=="--loop" (
  echo %date% %time% сервер остановился, перезапуск через 30 секунд
  ping -n 31 127.0.0.1 >nul
  goto run
)
