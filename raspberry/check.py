#!/usr/bin/env python3
"""
Diagnóstico do cacifo. Verifica, por ordem:
  1. Dependências Python (requests, Pillow, tkinter)
  2. Configuração efetiva (.env + variáveis de ambiente)
  3. Ligação real ao backend (GET /lockers/<id>/door)

Uso:  ./.venv/bin/python check.py      (ou: python3 check.py)
Sai com código 0 se estiver tudo OK, 1 caso contrário.
"""
import sys

ok = True
print("== SAM cacifo — diagnóstico ==")
print(f"Python: {sys.version.split()[0]}  ({sys.executable})")

# 1) Dependências -----------------------------------------------------------
print("\n-- Dependências --")
try:
    import requests
    print(f"[OK]   requests {requests.__version__}")
except Exception as e:  # noqa: BLE001
    ok = False
    print(f"[FALTA] requests  ->  pip install -r requirements.txt   ({e})")

try:
    import PIL
    print(f"[OK]   Pillow {PIL.__version__}")
except Exception as e:  # noqa: BLE001
    print(f"[aviso] Pillow em falta (logo será desenhado como texto)  ({e})")

try:
    import tkinter  # noqa: F401
    print("[OK]   tkinter")
except Exception as e:  # noqa: BLE001
    ok = False
    print(f"[FALTA] tkinter  ->  sudo apt install python3-tk   ({e})")

# 2) Configuração / .env ----------------------------------------------------
import config
print("\n-- Configuração efetiva (.env + ambiente) --")
print(f"  BACKEND_URL   = {config.BACKEND_URL}")
print(f"  LOCKER_ID     = {config.LOCKER_ID}")
print(f"  INTERNAL_KEY  = {'(definida)' if config.INTERNAL_KEY else '(VAZIA!)'}")
print(f"  DEMO_MODE     = {config.DEMO_MODE}")
print(f"  SIMULATE_DOOR = {config.SIMULATE_DOOR}")
print(f"  TELEMETRY_MS  = {config.TELEMETRY_MS}")
if not config.INTERNAL_KEY and not config.DEMO_MODE:
    ok = False
    print("  [erro] INTERNAL_KEY vazia — verifica o .env (SAM_INTERNAL_KEY).")

# Avisa se uma variável de ambiente da sessão estiver a sobrepor o .env.
import os
overrides = [k for k in os.environ if k.startswith("SAM_")]
if overrides:
    print(f"  [nota] variáveis de ambiente SAM_* ativas (têm prioridade sobre o .env): {', '.join(sorted(overrides))}")

# 3) Ligação ao backend -----------------------------------------------------
print("\n-- Ligação ao backend --")
if config.DEMO_MODE:
    print("  DEMO_MODE ativo: a app não liga ao backend.")
else:
    try:
        from sam_client import SamClient
        snap = SamClient().get_door()
        print(f"  [OK] GET /lockers/{config.LOCKER_ID}/door -> {snap}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [FALHA] {e!r}")
        print("  Pistas:")
        print("   - SSLError 'certificate is not yet valid' -> relógio errado:")
        print("       sudo timedatectl set-ntp true   (e confirma com: timedatectl)")
        print("   - ConnectionError / NameResolution    -> rede/DNS: testa  ping apisam.netdw.tech")
        print("   - 127.0.0.1 no URL                    -> há um SAM_BACKEND_URL no ambiente a sobrepor o .env")

print("\n== " + ("TUDO OK ✓" if ok else "HÁ PROBLEMAS — ver acima ✗") + " ==")
sys.exit(0 if ok else 1)
