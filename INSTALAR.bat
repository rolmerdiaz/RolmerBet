@echo off
setlocal
cd /d "%~dp0"
title Instalador de RolmerBet

set "PYTHON_EXE="

rem Buscar primero los comandos registrados en PATH.
for %%C in (py.exe python.exe python3.exe python3.13.exe python3.12.exe python3.11.exe) do (
  if not defined PYTHON_EXE (
    for /f "delims=" %%P in ('where %%C 2^>nul') do (
      if not defined PYTHON_EXE (
        "%%P" -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,11) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=%%P"
      )
    )
  )
)

rem Buscar instalaciones normales de python.org aunque no esten en PATH.
if not defined PYTHON_EXE for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
) do if exist "%%~P" set "PYTHON_EXE=%%~P"

rem Buscar instalaciones administradas por el nuevo Python Install Manager.
if not defined PYTHON_EXE for /d %%D in ("%LocalAppData%\Python\pythoncore-*") do (
  if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
)

rem Busqueda ampliada: Registro de Windows y paquetes de Microsoft Store.
if not defined PYTHON_EXE (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\buscar_python.ps1" > "%TEMP%\rolmerbet_python.txt"
  if not errorlevel 1 set /p PYTHON_EXE=<"%TEMP%\rolmerbet_python.txt"
  del "%TEMP%\rolmerbet_python.txt" >nul 2>nul
)

if not defined PYTHON_EXE (
  echo No se pudo localizar el ejecutable de Python.
  echo.
  echo La copia instalada desde Microsoft Store no expone un Python ejecutable.
  echo Abre Python 3.13 desde Inicio una vez y vuelve a intentar.
  echo Si continua, instala Python desde python.org activando "Add Python to PATH".
  pause
  exit /b 1
)

echo Python encontrado:
"%PYTHON_EXE%" --version
echo Ruta: %PYTHON_EXE%
echo.

echo [1/4] Creando entorno privado...
"%PYTHON_EXE%" -m venv .venv
if errorlevel 1 goto :error

echo [2/4] Actualizando instalador de paquetes...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/4] Instalando dependencias...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [4/4] Instalando Chromium para la lectura oculta de Triunfobet...
call .venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo Instalacion terminada. Abre EJECUTAR.bat.
pause
exit /b 0

:error
echo.
echo La instalacion no termino. Revisa tu conexion y vuelve a ejecutar este archivo.
pause
exit /b 1
