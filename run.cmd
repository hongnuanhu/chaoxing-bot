@echo off
rem Windows 入口：等价于 run.sh
rem 用法：run.cmd cx_play.py --login
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [x] 还没装环境，先执行：
  echo     py -3 -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install playwright requests
  echo     .venv\Scripts\python.exe -m playwright install chromium
  exit /b 1
)
set PYTHONWARNINGS=ignore
".venv\Scripts\python.exe" %*
