<div align="center">
  <img src="https://sam.netdw.tech/logo_big.svg" alt="SAM – Sistema de Apoio Municipal" width="160" />

  <h1>SAM — Cacifo Inteligente</h1>
  <p><em>Módulo físico do cacifo: interface do Raspberry Pi + sensor de porta Arduino</em></p>

  <p>
    <img src="https://img.shields.io/badge/Raspberry_Pi-400-C51A4A?style=for-the-badge&logo=raspberrypi&logoColor=white" alt="Raspberry Pi 400" />
    <img src="https://img.shields.io/badge/Python-3-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3" />
    <img src="https://img.shields.io/badge/Tkinter-GUI-FFD43B?style=for-the-badge&logo=python&logoColor=black" alt="Tkinter" />
    <img src="https://img.shields.io/badge/Arduino-Uno_R4_WiFi-00979D?style=for-the-badge&logo=arduino&logoColor=white" alt="Arduino Uno R4 WiFi" />
  </p>
</div>

---

## Contexto

Peça final do projeto **SAM (Sistema de Apoio Municipal)**. Materializa o cacifo
inteligente onde um cidadão deposita um bem associado a um *lead*, validado por
um **PIN de entrega**. É composto por dois programas independentes:

| Programa | Onde corre | O que faz |
| --- | --- | --- |
| **Aplicação do cacifo** (`raspberry/`) | Raspberry Pi 400 | Interface gráfica táctil com pinpad. Valida o PIN, indica o bem a depositar e fica à escuta da porta. |
| **Sensor de porta** (`arduino/`) | Arduino Uno R4 WiFi | Lê um interruptor magnético na porta e envia pings rápidos do estado (ABERTA/FECHADA) ao backend. |

O backend ([p2-sam-backend](https://github.com/amorima/p2-sam-backend)) foi
adaptado com um recurso `/lockers` que serve de ponte entre os dois.

---

## Arquitetura

```
 ┌─────────────────────────────┐         ┌──────────────────────────────┐
 │  Arduino Uno R4 WiFi         │         │  Raspberry Pi 400 (GUI)      │
 │  + reed switch na porta      │         │  pinpad táctil + numpad      │
 └──────────────┬──────────────┘         └───────────────┬──────────────┘
                │ POST /lockers/1/door                    │ POST /lockers/1/verify-pin
                │  {estado:ABERTA|FECHADA}                │ GET  /lockers/1/door (polling)
                │  (ping em mudança + heartbeat)          │ POST /lockers/1/confirm-deposit
                ▼                                         ▼
        ┌──────────────────────────────────────────────────────────┐
        │                  Backend SAM  (/lockers)                  │
        │   • guarda o último estado da porta em memória            │
        │   • escreve telemetria só nas transições (PORTA_ABERTA…)  │
        │   • resolve o PIN → lead pendente                         │
        │   • confirma o depósito → lead ENTREGUE                   │
        └──────────────────────────────────────────────────────────┘
```

O Arduino **não** fala diretamente com o Raspberry: ambos comunicam através do
backend. Assim, o estado da porta fica também visível no painel de administração
(telemetria) e o sistema mantém-se coerente com o resto da plataforma.

---

## Fluxo de depósito

1. O cidadão insere o **PIN de entrega** no pinpad (táctil ou numpad físico).
2. A app chama `POST /lockers/1/verify-pin`. O backend procura um *lead*
   **PENDENTE** com aquele PIN e devolve o nome do bem (`item_pedido`).
3. O ecrã mostra **"Por favor deposite o _\<bem\>_ no cacifo 1"** e começa a
   consultar o estado da porta (`GET /lockers/1/door`) ~4×/segundo.
4. Entretanto o Arduino reporta a porta. Quando o cidadão **abre** a porta, o
   ecrã passa a "Feche a porta para concluir".
5. Quando a porta **volta a fechar**, a app chama
   `POST /lockers/1/confirm-deposit`. O *lead* fica **ENTREGUE** — a doação é
   dada como certa — e aparece o ecrã de sucesso.

---

## Backend — adaptação

Ficheiros adicionados/alterados em `p2-sam-backend`:

- `controllers/lockers.controllers.js` — lógica do recurso.
- `routes/lockers.routes.js` — rotas.
- `server.js` — regista `/lockers` e isenta-o do rate limit (pings frequentes).

### Endpoints

Todos aceitam o cabeçalho `X-Internal-Key` (= `INTERNAL_API_KEY`) ou um JWT.

| Método | Rota | Corpo | Resposta |
| --- | --- | --- | --- |
| `POST` | `/lockers/:id/verify-pin` | `{ "pin": "123456" }` | `{ valid, id_lead, item_pedido, nome_cidadao }` ou `404` |
| `POST` | `/lockers/:id/door` | `{ "estado": "ABERTA"\|"FECHADA" }` | snapshot da porta |
| `GET` | `/lockers/:id/door` | — | `{ estado, online, last_change, last_seen }` |
| `POST` | `/lockers/:id/confirm-deposit` | `{ "id_lead": 3 }` | `{ confirmed, lead }` |
| `GET` | `/lockers` · `/lockers/:id` | — | cacifo(s) + snapshot da porta |

> O último estado da porta é mantido **em memória**. Cada transição
> ABERTA↔FECHADA gera um documento de telemetria (`PORTA_ABERTA`/`PORTA_FECHADA`)
> para o histórico do painel; os *heartbeats* não escrevem na base de dados.

---

## Aplicação do cacifo (Raspberry Pi 400)

### Requisitos

- Raspberry Pi OS com ambiente gráfico (X11).
- Python 3 + Tkinter (`sudo apt install python3-tk`).

### Arranque com um clique (sem linha de comandos)

- **Windows (PC de testes):** duplo-clique em **`start.bat`** — cria o `.venv`,
  instala as dependências e arranca a app.
- **Raspberry Pi:** correr **uma vez** `bash install_desktop.sh` (cria um ícone
  **"SAM Cacifo"** no ambiente de trabalho). A partir daí, **duplo-clique no
  ícone** instala as dependências (1ª vez) e arranca a app em ecrã inteiro.

Pré-requisito no Pi (uma vez): `sudo apt install -y python3-venv python3-tk`.

### Diagnóstico

`python check.py` (ou `./.venv/bin/python check.py`) verifica **dependências +
leitura do `.env` + ligação ao backend** e indica o que está mal.

### Instalação e arranque (linha de comandos)

```bash
cd raspberry
cp .env.example .env          # já vem para apisam.netdw.tech; confirmar SAM_INTERNAL_KEY
chmod +x run_kiosk.sh
./run_kiosk.sh                # cria .venv, instala deps e arranca em ecrã inteiro
```

> O `config.py` carrega automaticamente o `.env` ao lado de `app.py` (em
> qualquer plataforma), por isso `python app.py` também funciona sem o script.
> No arranque, a app imprime o backend em uso — útil para confirmar o `.env`.

Para arrancar automaticamente no boot, instalar a unidade systemd:

```bash
sudo cp sam-locker.service /etc/systemd/system/
sudo systemctl enable --now sam-locker
```

### Interação

- **Ecrã táctil** ou **numpad físico**: dígitos `0-9`, `←` apaga, `OK`/`Enter`
  valida. O PIN é submetido automaticamente ao ficar completo.
- `Esc` fecha a aplicação.

### Configuração (variáveis de ambiente)

As principais (lista completa em `.env.example`):

| Variável | Omissão | Descrição |
| --- | --- | --- |
| `SAM_BACKEND_URL` | `https://apisam.netdw.tech` | URL base da API (produção; local: `http://127.0.0.1:3011`) |
| `SAM_LOCKER_ID` | `1` | Cacifo físico controlado |
| `SAM_INTERNAL_KEY` | — | Chave dos dispositivos (X-Internal-Key) |
| `SAM_PIN_LENGTH` | `6` | Dígitos do PIN |
| `SAM_DOOR_POLL_MS` | `250` | Período de consulta da porta |
| `SAM_FULLSCREEN` | `1` | Ecrã inteiro |

### Modos de teste (sem hardware)

```bash
# Fluxo completo só com teclado, sem backend nem Arduino:
SAM_DEMO_MODE=1 SAM_FULLSCREEN=0 python app.py
#   PIN de demonstração: 123456   |   porta: tecla 'o' abre, 'c' fecha

# Usar o backend real para o PIN, mas simular a porta pelo teclado:
SAM_SIMULATE_DOOR=1 python app.py
```

### Logótipo

Por omissão o logótipo é desenhado como texto (sem dependências). Para um
logótipo pixel-perfect a partir do SVG da marca:

```bash
pip install cairosvg
python assets/render_logo.py     # gera assets/logo.png (carregado se existir)
```

---

## Sensor de porta (Arduino Uno R4 WiFi)

### Material

- Arduino Uno R4 WiFi.
- Interruptor magnético / reed switch (par íman + sensor).
- Fios.

### Ligação

| Reed switch | Arduino |
| --- | --- |
| Terminal A | Pino digital **D2** |
| Terminal B | **GND** |

O pino usa `INPUT_PULLUP`. Com o íman alinhado (**porta fechada**) o contacto
fecha e o pino lê `LOW`; ao afastar (**porta aberta**) lê `HIGH`. Se o teu reed
for normalmente-fechado, inverte `DOOR_CLOSED_LEVEL` no sketch.

### Configuração e upload

No topo de `arduino/sam_locker_door/sam_locker_door.ino` editar:

- `WIFI_SSID` / `WIFI_PASS`
- `SERVER_HOST` / `SERVER_PORT` / `USE_HTTPS` (já configurado para produção:
  `apisam.netdw.tech`, `443`, `1`; para backend local: o IP do PC, `3011`, `0`)
- `LOCKER_ID` (= 1)
- `INTERNAL_KEY` (igual ao `SAM_INTERNAL_KEY` do Raspberry / `INTERNAL_API_KEY` do backend)

> **Cloudflare:** o backend publicado está atrás de Cloudflare, que bloqueia
> pedidos sem `User-Agent` de browser (erro 1010). O sketch e o cliente do
> Raspberry já enviam um `User-Agent` adequado. Em HTTPS, se a validação TLS
> falhar no R4, atualizar os certificados raiz pelo Arduino IDE
> (*Tools → … → Upload SSL Root Certificates*, adicionar `apisam.netdw.tech`).

Carregar com o Arduino IDE (placa **Arduino Uno R4 WiFi**, bibliotecas `WiFiS3`
e `Arduino_LED_Matrix` incluídas no *board package*). O Monitor Série (115200)
mostra os envios.

**Feedback visual na placa:**
- **Matriz de LEDs 12×8:** mostra um **cadeado fechado** quando a porta está
  fechada (ímanes juntos) e um **cadeado aberto** quando se separam.
- **LED interno** (`LED_BUILTIN`): indica o **WiFi** — **sólido = ligado**,
  **a piscar = a tentar ligar / sem rede**.

**Fiabilidade:**
- **Watchdog** por hardware (RA4M1): se um ciclo bloquear mais de ~5 s (ex.: o
  stack WiFi/TLS encravar após muitas horas), a placa **reinicia-se sozinha** e
  volta a ligar e a reportar — sem intervenção manual.
- A leitura do sensor e os LEDs nunca dependem da rede (atualizam mesmo offline);
  o WiFi religa em segundo plano sem bloquear.

---

## Agradecimentos

Um agradecimento especial ao **Prof. Diogo Filipe de Bastos Sousa Ribeiro** pelo
apoio nesta componente do projeto — por acreditar na ideia e por confiar e
emprestar os equipamentos (Raspberry Pi, Arduino e sensores) que tornaram
possível a sua realização.

---

<div align="center">
  <sub>Desenvolvido para fins académicos · ESMAD - Politécnico do Porto · 2025/2026</sub>
</div>
