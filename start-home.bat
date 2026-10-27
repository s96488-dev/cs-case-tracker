@echo off
chcp 65001 >nul
rem Starts the home part: cloud sync + API/charts on http://127.0.0.1:8080
rem With --loop (used by autostart) the server restarts if it crashes.
cd /d "%~dp0"
if not exist home\env.bat (
  echo Create home\env.bat from home\.env.example.bat
  if /i not "%~1"=="--loop" pause
  exit /b 1
)
call home\env.bat
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements-home.txt
)
rem Pull the latest version from GitHub if the folder is a git clone.
if exist .git (
  git pull --ff-only
  .venv\Scripts\pip install -q -r requirements-home.txt
)
:run
.venv\Scripts\python -m home
if /i "%~1"=="--loop" (
  echo %date% %time% server stopped, restarting in 30 seconds
  ping -n 31 127.0.0.1 >nul
  goto run
)
