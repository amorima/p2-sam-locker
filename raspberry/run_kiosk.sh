#!/usr/bin/env bash
#
# Arranque da aplicação do cacifo no Raspberry Pi 400.
# Cria o ambiente virtual, garante as dependências e lança em ecrã inteiro.
# O .env é lido pela própria app (config.py), por isso não é preciso exportá-lo.
set -euo pipefail

cd "$(dirname "$0")"

# Ambiente virtual + dependências (idempotente: instala/atualiza sempre).
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
fi
./.venv/bin/pip install -q -r requirements.txt

# Evitar que o ecrã apague / poupança de energia (X11).
if command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
fi

exec ./.venv/bin/python app.py
