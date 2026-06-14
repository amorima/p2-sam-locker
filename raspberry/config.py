"""
Configuração da aplicação do cacifo (Raspberry Pi 400).

Todos os valores podem ser sobrepostos por variáveis de ambiente, o que permite
correr a mesma aplicação em desenvolvimento (portátil) e em produção (Pi) sem
alterar código. Ver o ficheiro `.env.example` para a lista completa.
"""
import os


def _load_dotenv():
    """Carrega o ficheiro .env ao lado deste módulo (se existir) para que
    `python app.py` funcione em qualquer plataforma sem precisar de o exportar
    manualmente. Variáveis já definidas no ambiente têm prioridade."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_dotenv()


def _env(name, default):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "sim")


def _env_int(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


# --- Ligação ao backend -----------------------------------------------------
# URL base da API SAM (sem barra final). Produção: https://apisam.netdw.tech
# (atrás de Cloudflare); backend local: http://127.0.0.1:3011
BACKEND_URL = _env("SAM_BACKEND_URL", "https://apisam.netdw.tech").rstrip("/")

# Cacifo físico que este Pi controla. Só temos um, por isso = 1.
LOCKER_ID = _env_int("SAM_LOCKER_ID", 1)

# Autenticação dos dispositivos: cabeçalho X-Internal-Key (= INTERNAL_API_KEY do
# backend). Os endpoints do cacifo usam verifyInternalOrJWT.
INTERNAL_KEY = _env("SAM_INTERNAL_KEY", "")
USER_NIF = _env("SAM_USER_NIF", "000000000")
USER_ROLE = _env("SAM_USER_ROLE", "admin")

# Timeout (segundos) para os pedidos HTTP ao backend.
HTTP_TIMEOUT = float(_env("SAM_HTTP_TIMEOUT", "4"))

# --- PIN --------------------------------------------------------------------
PIN_LENGTH = _env_int("SAM_PIN_LENGTH", 6)

# --- Porta / sensor ---------------------------------------------------------
# Intervalo (ms) com que o Pi consulta o estado da porta no backend.
DOOR_POLL_MS = _env_int("SAM_DOOR_POLL_MS", 250)

# Tempo máximo (s) à espera que a porta abra antes de cancelar e voltar ao PIN.
DEPOSIT_TIMEOUT_S = _env_int("SAM_DEPOSIT_TIMEOUT_S", 120)

# Segundos que o ecrã de sucesso fica visível antes de voltar ao início.
SUCCESS_DWELL_S = _env_int("SAM_SUCCESS_DWELL_S", 5)

# --- Telemetria do cacifo ---------------------------------------------------
# O Pi reporta periodicamente o estado de saúde do cacifo (como o painel faz),
# para aparecer em "Equipamentos" no frontend. 0 desativa.
TELEMETRY_MS = _env_int("SAM_TELEMETRY_MS", 8000)
APP_VERSION = _env("SAM_APP_VERSION", "1.0.0")
# Localização física do cacifo (Vila do Conde por omissão).
GEO_LAT = float(_env("SAM_GEO_LAT", "41.3530"))
GEO_LON = float(_env("SAM_GEO_LON", "-8.7430"))

# --- Modos de teste ---------------------------------------------------------
# DEMO_MODE: não fala com o backend. PIN de demonstração validado localmente e
# porta controlada pelo teclado (teclas 'o' = abrir, 'c' = fechar). Ideal para
# testar a interface sem backend nem Arduino.
DEMO_MODE = _env_bool("SAM_DEMO_MODE", False)
DEMO_PIN = _env("SAM_DEMO_PIN", "123456")
DEMO_ITEM = _env("SAM_DEMO_ITEM", "Cobertor")

# SIMULATE_DOOR: usa o backend para validar o PIN, mas simula a porta pelo
# teclado ('o'/'c') em vez de consultar o backend. Útil para testar o fluxo
# completo sem o Arduino ligado.
SIMULATE_DOOR = _env_bool("SAM_SIMULATE_DOOR", False)

# --- Interface --------------------------------------------------------------
FULLSCREEN = _env_bool("SAM_FULLSCREEN", True)
# Esconder o cursor do rato (ecrã táctil).
HIDE_CURSOR = _env_bool("SAM_HIDE_CURSOR", True)

WINDOW_W = _env_int("SAM_WINDOW_W", 1024)
WINDOW_H = _env_int("SAM_WINDOW_H", 600)

# Paleta "azul clássico" SAM (logótipo branco + acento laranja da marca).
COLORS = {
    "bg_top": "#0A2A5E",       # azul-marinho profundo (topo do gradiente)
    "bg_bottom": "#1657A8",    # azul royal (base do gradiente)
    "card": "#0E3F86",         # painel central
    "card_edge": "#2C66B5",
    "key": "#1C5BB0",          # tecla normal
    "key_active": "#2E72C8",
    "key_text": "#FFFFFF",
    "clear": "#15498C",        # tecla apagar
    "accent": "#F28D38",       # laranja da marca (tecla OK / acentos)
    "accent_active": "#FF9E4D",
    "text": "#FFFFFF",
    "muted": "#B9CDEA",
    "error": "#FF6B6B",
    "success": "#3BD17A",
    "door_open": "#F2A33C",
    "door_closed": "#3BD17A",
    "door_unknown": "#7E9BC7",
}

FONT_FAMILY = _env("SAM_FONT", "DejaVu Sans")
