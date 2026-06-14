"""
Cliente HTTP para a API SAM, usado pela aplicação do cacifo.

Encapsula os três endpoints do cacifo:
  * verify_pin(pin)        -> resolve o PIN num lead pendente
  * get_door()             -> estado atual da porta (sensor)
  * confirm_deposit(lead)  -> marca o lead como ENTREGUE (doação confirmada)

Todos os métodos são síncronos e devem ser chamados a partir de uma thread de
trabalho (nunca diretamente na thread da interface Tkinter).
"""
import requests

import config


class SamApiError(Exception):
    """Erro de comunicação ou resposta inesperada do backend."""


class SamClient:
    def __init__(self):
        self.base = config.BACKEND_URL
        self.locker_id = config.LOCKER_ID
        self.timeout = config.HTTP_TIMEOUT
        # Sem Session partilhada: a app faz pedidos a partir de várias threads
        # (verificação de PIN, telemetria, porta) e uma requests.Session NÃO é
        # thread-safe. Usar requests.<método> diretamente cria uma ligação por
        # chamada — seguro entre threads.

    # O backend publicado está atrás de Cloudflare, que bloqueia clientes sem
    # User-Agent de browser (erro 1010). Enviamos sempre um UA credível.
    _USER_AGENT = ("Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 SAM-Locker")

    def _headers(self):
        headers = {"Content-Type": "application/json", "User-Agent": self._USER_AGENT}
        if config.INTERNAL_KEY:
            headers["X-Internal-Key"] = config.INTERNAL_KEY
            headers["X-User-Nif"] = config.USER_NIF
            headers["X-User-Role"] = config.USER_ROLE
        return headers

    def _url(self, path):
        return f"{self.base}/lockers/{self.locker_id}{path}"

    # --- PIN ----------------------------------------------------------------
    def verify_pin(self, pin):
        """Devolve dict com {id_lead, item_pedido, nome_cidadao} se válido,
        ou None se o PIN não corresponder a nenhum lead pendente."""
        try:
            resp = requests.post(
                self._url("/verify-pin"),
                json={"pin": pin},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SamApiError(f"Sem ligação ao servidor: {exc}") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                return data
            return None
        raise SamApiError(f"Resposta inesperada ({resp.status_code}) ao validar PIN")

    # --- Porta --------------------------------------------------------------
    def get_door(self):
        """Devolve dict {estado, online, last_change, last_seen}."""
        try:
            resp = requests.get(
                self._url("/door"),
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise SamApiError(f"Sem ligação ao sensor: {exc}") from exc

    # --- Telemetria ---------------------------------------------------------
    def send_telemetry(self, payload):
        """Envia um registo de telemetria do cacifo para o backend (/telemetry).
        Silencioso: erros de rede não devem perturbar a interface."""
        try:
            resp = requests.post(
                f"{self.base}/telemetry",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            return resp.status_code in (200, 201)
        except requests.RequestException:
            return False

    # --- Confirmação --------------------------------------------------------
    def confirm_deposit(self, id_lead):
        """Marca o lead como ENTREGUE. Idempotente do lado do backend."""
        try:
            resp = requests.post(
                self._url("/confirm-deposit"),
                json={"id_lead": id_lead},
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise SamApiError(f"Falha ao confirmar a doação: {exc}") from exc
