/*
 * SAM — Sensor de porta do cacifo (Arduino Uno R4 WiFi)
 * ----------------------------------------------------------------------------
 * Lê um interruptor magnético (reed switch) ligado à porta do cacifo e reporta
 * o estado (ABERTA / FECHADA) ao backend SAM através de pings HTTP rápidos:
 *
 *   - Envia imediatamente sempre que o estado muda (com debounce).
 *   - Envia um "heartbeat" periódico para o backend saber que o sensor está
 *     vivo (o backend marca o cacifo como offline se não receber pings).
 *
 * Endpoint:  POST {SERVER}/lockers/{LOCKER_ID}/door
 * Corpo:     {"estado":"ABERTA"} ou {"estado":"FECHADA"}
 * Auth:      cabeçalho X-Internal-Key (= INTERNAL_API_KEY do backend)
 *
 * Ligação do reed switch:
 *   - Um terminal ao pino REED_PIN, o outro ao GND.
 *   - Pino configurado como INPUT_PULLUP.
 *   - Porta FECHADA  -> íman junto ao reed -> contacto fechado -> pino LOW.
 *   - Porta ABERTA   -> íman afastado       -> contacto aberto  -> pino HIGH.
 * (Se o teu reed for normalmente-fechado, inverte DOOR_CLOSED_LEVEL.)
 */

#include <WiFiS3.h>
#include "Arduino_LED_Matrix.h"  // matriz de LEDs 12x8 embutida no Uno R4 WiFi
#include "WDT.h"                  // watchdog por hardware (RA4M1) — auto-reset

// ===================== CONFIGURAÇÃO (editar) ================================
const char WIFI_SSID[] = "CMF";
const char WIFI_PASS[] = "12345678";

// Backend SAM publicado (acessível de qualquer rede), via HTTPS.
// Para usar um backend local: USE_HTTPS 0, SERVER_HOST="192.168.x.x", PORT=3011.
#define USE_HTTPS 1
const char SERVER_HOST[] = "apisam.netdw.tech";  // backend publicado
const uint16_t SERVER_PORT = 443;                // 443 (HTTPS) / 3011 (local)

const int LOCKER_ID = 1;
const char INTERNAL_KEY[] = "mais_uma_chave_interna_para_o_trabalho_sam";

// Pino do reed switch e nível lógico correspondente a porta FECHADA.
const int REED_PIN = 2;
const int DOOR_CLOSED_LEVEL = LOW;

const unsigned long DEBOUNCE_MS = 40;      // anti-ressalto do contacto
const unsigned long HEARTBEAT_MS = 2000;   // ping periódico (backend offline aos 6s)
// Watchdog: se um ciclo do loop demorar mais que isto, a placa reinicia sozinha.
// Bem acima do tempo normal de um ciclo (inclui um pedido HTTPS ~1-2s); o máximo
// suportado pelo RA4M1 ronda os 5,6 s.
const uint32_t WDT_TIMEOUT_MS = 5000;
// ===========================================================================

#if USE_HTTPS
WiFiSSLClient client;
#else
WiFiClient client;
#endif

// --- Matriz de LEDs: ícones de cadeado (8 linhas x 12 colunas) -------------
ArduinoLEDMatrix matrix;

// Nota: renderBitmap() recebe a matriz por REFERÊNCIA não-const, por isso os
// frames não podem ser `const` (e não se pode passar um ternário, que faria
// "decay" para ponteiro). Cada frame é desenhado a partir do seu próprio array.

// Cadeado FECHADO: arco simétrico com as duas pernas a entrar no corpo.
uint8_t LOCK_CLOSED[8][12] = {
  {0,0,0,0,1,1,1,1,0,0,0,0},
  {0,0,0,1,0,0,0,0,1,0,0,0},
  {0,0,0,1,0,0,0,0,1,0,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,0,0,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
};

// Cadeado ABERTO: arco rodado para a esquerda, perna direita levantada (fora
// do corpo) — a forma típica de "destrancado".
uint8_t LOCK_OPEN[8][12] = {
  {0,0,1,1,1,1,0,0,0,0,0,0},
  {0,0,1,0,0,1,0,0,0,0,0,0},
  {0,0,1,0,0,0,0,0,0,0,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,0,0,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
  {0,0,1,1,1,1,1,1,1,1,0,0},
};

void showLock(bool open) {
  if (open) {
    matrix.renderBitmap(LOCK_OPEN, 8, 12);
  } else {
    matrix.renderBitmap(LOCK_CLOSED, 8, 12);
  }
}

// Leitura debounced
int lastRawReading = -1;
int stableState = -1;             // HIGH/LOW estável do pino
unsigned long lastChangeMs = 0;
bool lastDoorOpen = false;        // último estado reportado (true = ABERTA)
unsigned long lastHeartbeatMs = 0;

// Rede não-bloqueante
bool pendingSend = true;          // há uma mudança por enviar ao backend
unsigned long lastWifiAttempt = 0;

bool doorIsOpen() {
  return stableState != DOOR_CLOSED_LEVEL;
}

// (Re)liga ao WiFi SEM prender o ciclo: no máximo uma tentativa a cada 8 s.
// Assim o sensor/LEDs continuam a atualizar mesmo sem rede.
void maintainWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (lastWifiAttempt != 0 && millis() - lastWifiAttempt < 8000) return;
  lastWifiAttempt = millis();
  Serial.print("A ligar ao WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi ligado. IP: ");
    Serial.println(WiFi.localIP());
  }
}

// Indicador de WiFi no LED interno (pino 13):
//   ligado e estável  -> LED sólido
//   a tentar / sem rede -> LED a piscar (~2 Hz)
// Sem delay() — usa millis(), para não bloquear o loop nem o watchdog.
void updateWifiLed() {
  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_BUILTIN, HIGH);
  } else {
    digitalWrite(LED_BUILTIN, (millis() / 250) % 2 == 0 ? HIGH : LOW);
  }
}

// Envia o estado atual da porta ao backend. Devolve true em caso de sucesso.
// Não tenta religar o WiFi (isso é tratado, sem bloquear, por maintainWifi).
bool sendDoorState(bool isOpen) {
  if (WiFi.status() != WL_CONNECTED) return false;

  if (!client.connect(SERVER_HOST, SERVER_PORT)) {
    Serial.println("Falha a ligar ao servidor.");
    return false;
  }

  String estado = isOpen ? "ABERTA" : "FECHADA";
  String body = String("{\"estado\":\"") + estado + "\"}";
  String path = String("/lockers/") + LOCKER_ID + "/door";

  client.print(String("POST ") + path + " HTTP/1.1\r\n");
  client.print(String("Host: ") + SERVER_HOST + "\r\n");
  // O backend está atrás de Cloudflare: sem User-Agent de browser devolve 1010.
  client.print("User-Agent: Mozilla/5.0 (Arduino UnoR4 WiFi) SAM-Locker\r\n");
  client.print(String("X-Internal-Key: ") + INTERNAL_KEY + "\r\n");
  client.print("X-User-Role: admin\r\n");
  client.print("Content-Type: application/json\r\n");
  client.print(String("Content-Length: ") + body.length() + "\r\n");
  client.print("Connection: close\r\n\r\n");
  client.print(body);

  // Aguardar (curto) e descartar a resposta para libertar o socket.
  unsigned long t0 = millis();
  while (client.connected() && millis() - t0 < 1500) {
    while (client.available()) client.read();
  }
  client.stop();

  Serial.print("-> porta ");
  Serial.println(estado);
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(REED_PIN, INPUT_PULLUP);
  pinMode(LED_BUILTIN, OUTPUT);
  matrix.begin();

  stableState = digitalRead(REED_PIN);
  lastRawReading = stableState;
  lastDoorOpen = doorIsOpen();

  // Estado da porta -> matriz (cadeado). Estado do WiFi -> LED interno (loop).
  showLock(lastDoorOpen);
  digitalWrite(LED_BUILTIN, LOW);

  // A ligação WiFi e o envio do estado inicial são feitos no loop, sem bloquear
  // a leitura do sensor (pendingSend já está a true).
  lastHeartbeatMs = millis();

  // Watchdog: arranca por último, depois de tudo inicializado. Se o loop deixar
  // de fazer refresh (bloqueio do stack WiFi/TLS após horas), a placa reinicia.
  if (WDT.begin(WDT_TIMEOUT_MS)) {
    Serial.println("Watchdog ativo.");
  } else {
    Serial.println("AVISO: watchdog nao iniciou (timeout fora do limite do chip).");
  }
}

void loop() {
  // Alimenta o watchdog: enquanto o loop correr normalmente nunca reinicia.
  WDT.refresh();

  // --- 1) Sensor + LEDs: SEMPRE primeiro, nunca depende da rede ---
  int raw = digitalRead(REED_PIN);
  if (raw != lastRawReading) {
    lastRawReading = raw;
    lastChangeMs = millis();
  }
  if (millis() - lastChangeMs > DEBOUNCE_MS && raw != stableState) {
    stableState = raw;
    bool open = doorIsOpen();
    showLock(open);          // atualiza imediatamente o cadeado na matriz (porta)
    pendingSend = true;      // marca para enviar ao backend quando houver rede
  }

  // --- 2) Rede: não bloqueia o sensor ---
  maintainWifi();
  updateWifiLed();  // LED interno reflete o estado do WiFi (sólido/piscar)
  WDT.refresh();  // orçamento próprio para o envio (evita reset falso após reconexão)
  if (WiFi.status() == WL_CONNECTED) {
    if (pendingSend) {
      // Envia a mudança assim que possível.
      if (sendDoorState(doorIsOpen())) {
        lastDoorOpen = doorIsOpen();
        pendingSend = false;
        lastHeartbeatMs = millis();
      }
    } else if (millis() - lastHeartbeatMs >= HEARTBEAT_MS) {
      // Heartbeat periódico para o backend saber que o sensor está vivo.
      sendDoorState(lastDoorOpen);
      lastHeartbeatMs = millis();
    }
  }
}
