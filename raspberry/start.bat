@echo off
REM ============================================================
REM  SAM Cacifo - arranque com duplo-clique no Windows (testes)
REM  Cria o ambiente virtual, instala as dependencias e corre a app.
REM ============================================================
setlocal
cd /d "%~dp0"

echo === SAM Cacifo ===

if not exist ".venv\Scripts\python.exe" (
  echo A criar ambiente virtual...
  python -m venv .venv || py -3 -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERRO: nao foi possivel criar o ambiente virtual.
  echo Confirma que o Python 3 esta instalado e no PATH ^(python --version^).
  echo.
  pause
  exit /b 1
)

echo A instalar/atualizar dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo A iniciar a aplicacao...
".venv\Scripts\python.exe" app.py

echo.
echo (A aplicacao terminou.)
pause
