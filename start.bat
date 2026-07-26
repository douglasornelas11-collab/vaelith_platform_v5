@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)
if not exist .venv (
  %PY% -m venv .venv
  if errorlevel 1 goto :error
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :error
start "" http://localhost:8080/login
python server.py
exit /b 0
:error
echo.
echo Nao foi possivel iniciar a plataforma.
pause
exit /b 1
