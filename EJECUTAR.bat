@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Primero ejecuta INSTALAR.bat.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "RolmerBet.pyw"
