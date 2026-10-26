@echo off
chcp 65001 >nul
rem Автозапуск домашней части при входе в Windows, без окна.
rem Кладёт маленький скрипт в папку «Автозагрузка» и сразу запускает его. Права администратора не нужны.
rem Лог: home.log в папке репозитория. Отключить: uninstall-autostart.bat
cd /d "%~dp0"
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\cs-case-tracker.vbs"
> "%TARGET%" (
  echo Set sh = CreateObject("WScript.Shell"^)
  echo sh.CurrentDirectory = "%~dp0"
  echo sh.Run "cmd /c start-home.bat --loop > home.log 2>&1", 0, False
)
echo Автозапуск установлен: %TARGET%
wscript "%TARGET%"
echo Домашняя часть запущена в фоне. Через полминуты открой http://127.0.0.1:8080
pause
