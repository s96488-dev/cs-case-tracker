@echo off
rem Backtest of case-buying signals on the home database; writes backtest_report.md.
rem Extra options are passed through, e.g. backtest.bat --split 2021-01-01 --gens 60
cd /d "%~dp0"
call home\env.bat
.venv\Scripts\python -m home.backtest %*
