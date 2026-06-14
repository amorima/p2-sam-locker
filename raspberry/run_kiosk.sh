#!/usr/bin/env bash
#
# Arranque da aplicação do cacifo no Raspberry Pi 400.
# Carrega o .env (se existir), garante o ambiente virtual e lança em ecrã inteiro.
set -euo pipefail

cd "$(dirname "$0")"

# Carregar variáveis de ambiente do .env, se presente.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Ambiente virtual (criado na primeira execução).
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

# Evitar que o ecrã apague / poupança de energia (X11).
if command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
fi

exec ./.venv/bin/python app.py
