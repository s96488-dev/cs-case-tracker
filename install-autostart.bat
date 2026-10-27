@echo off
chcp 65001 >nul
rem Starts the home part at Windows sign-in, without a window.
rem Puts a small script into the Startup folder and runs it right away. No admin rights needed.
rem Log: home.log in the repository folder. To disable: uninstall-autostart.bat
cd /d "%~dp0"
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\cs-case-tracker.vbs"
> "%TARGET%" (
  echo Set sh = CreateObject("WScript.Shell"^)
  echo sh.CurrentDirectory = "%~dp0"
  echo sh.Run "cmd /c start-home.bat --loop > home.log 2>&1", 0, False
)
echo Autostart installed: %TARGET%
wscript "%TARGET%"
echo The home part is running in the background. Open http://127.0.0.1:8080 in about 30 seconds
pause
