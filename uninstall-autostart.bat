@echo off
chcp 65001 >nul
rem Отключает автозапуск и останавливает фоновую домашнюю часть.
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\cs-case-tracker.vbs"
if exist "%TARGET%" del "%TARGET%"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*start-home.bat --loop*' -or $_.CommandLine -like '*python* -m home*') } | Sort-Object { $_.Name -ne 'cmd.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Автозапуск отключён.
pause
