@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  call ".venv\Scripts\python.exe" -m unittest discover -s tests -v
) else (
  py -m unittest discover -s tests -v
)
pause
