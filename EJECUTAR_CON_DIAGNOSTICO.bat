@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat.
  pause
  exit /b 1
)
call ".venv\Scripts\python.exe" "RolmerBet.pyw"
pause
