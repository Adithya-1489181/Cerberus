/*
 * Cerberus - ESP32 sensing & actuation module.
 *
 * - Continuously measures distance with an HC-SR04 ultrasonic sensor.
 * - When someone steps within DETECT_DISTANCE_CM, it signals the Raspberry
 *   Pi (over WiFi/HTTP) to run facial recognition.
 * - Based on the Pi's reply ("recognized" / "not_recognized") it decides
 *   whether to open the door (servo) or keep it shut.
 *
 * Libraries required (install via Arduino Library Manager):
 *   - ESP32Servo   (madhephaestus/ESP32Servo)
 *   - ArduinoJson  (bblanchon/ArduinoJson, v6 or v7)
 *
 * Board: any ESP32 dev board (Arduino-ESP32 core 2.x or 3.x).
 *
 * Before building: copy config.example.h to config.h and fill in your
 * WiFi credentials and the Raspberry Pi's IP address.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

#include "config.h"

Servo doorServo;

unsigned long lastScanAt = 0;
bool doorIsOpen = false;
unsigned long doorOpenedAt = 0;

const char *wifiStatusName(wl_status_t st) {
  switch (st) {
    case WL_NO_SSID_AVAIL:   return "NO_SSID_AVAIL (network not seen)";
    case WL_CONNECT_FAILED:  return "CONNECT_FAILED (wrong password / rejected)";
    case WL_CONNECTION_LOST: return "CONNECTION_LOST";
    case WL_DISCONNECTED:    return "DISCONNECTED";
    case WL_IDLE_STATUS:     return "IDLE";
    default:                 return "OTHER";
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  // List what this ESP32 can actually see (it is 2.4 GHz only).
  Serial.println("Scanning WiFi networks...");
  int n = WiFi.scanNetworks();
  bool found = false;
  for (int i = 0; i < n; i++) {
    Serial.printf("  %-24s ch%-2d %4d dBm\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));
    if (WiFi.SSID(i) == WIFI_SSID) found = true;
  }
  Serial.println(found ? "Target network is visible."
                       : "Target network NOT visible - check the Pi access point is on 2.4 GHz and in range.");

  // Retry until connected; reset the WiFi stack between attempts.
  while (WiFi.status() != WL_CONNECTED) {
    Serial.printf("Connecting to '%s'", WIFI_SSID);
    WiFi.disconnect(true);
    delay(200);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
      delay(500);
      Serial.print(".");
    }
    if (WiFi.status() != WL_CONNECTED)
      Serial.printf("\nFailed, status %d: %s - retrying\n", WiFi.status(), wifiStatusName(WiFi.status()));
  }
  Serial.printf("\nWiFi connected, IP: %s\n", WiFi.localIP().toString().c_str());
}

// Returns distance in cm, or -1 on timeout/no echo.
long readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 30ms timeout ~= 5m range, plenty for a doorway sensor.
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000UL);
  if (duration == 0) return -1;
  return duration / 58; // speed of sound conversion -> cm
}

void setDoor(bool open) {
  doorServo.write(open ? DOOR_OPEN_ANGLE : DOOR_CLOSED_ANGLE);
  doorIsOpen = open;
  if (open) doorOpenedAt = millis();
  digitalWrite(LED_GREEN_PIN, open ? HIGH : LOW);
}

void denyAccessFeedback() {
  digitalWrite(LED_RED_PIN, HIGH);
  tone(BUZZER_PIN, 1000, 300);
  delay(300);
  digitalWrite(LED_RED_PIN, LOW);
}

// POSTs to the Pi's /scan endpoint and returns true if it replied "recognized".
bool askPiToRecognizeFace(String &nameOut) {
  HTTPClient http;
  String url = String("http://") + PI_HOST + ":" + String(PI_PORT) + PI_SCAN_PATH;

  Serial.printf("[esp32] person detected -> asking Pi: %s\n", url.c_str());
  http.begin(url);
  http.setTimeout(HTTP_TIMEOUT_MS);
  int httpCode = http.POST("");

  if (httpCode <= 0) {
    Serial.printf("[esp32] HTTP request failed: %s\n", http.errorToString(httpCode).c_str());
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();
  Serial.printf("[esp32] Pi responded (%d): %s\n", httpCode, body.c_str());

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[esp32] bad JSON from Pi: %s\n", err.c_str());
    return false;
  }

  const char *status = doc["status"] | "not_recognized";
  nameOut = String((const char *)(doc["name"] | "unknown"));
  return strcmp(status, "recognized") == 0;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  doorServo.setPeriodHertz(50);
  doorServo.attach(SERVO_PIN, 500, 2400);
  setDoor(false); // start locked/closed

  connectWiFi();
  Serial.println("[esp32] ready, scanning for visitors...");
}

void loop() {
  // Auto-close the door once it has been open long enough.
  if (doorIsOpen && millis() - doorOpenedAt >= DOOR_OPEN_MS) {
    Serial.println("[esp32] closing door after timeout");
    setDoor(false);
  }

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  static int closeReadings = 0;
  long distance = readDistanceCm();

  if (distance > 0 && distance <= DETECT_DISTANCE_CM) {
    closeReadings++;
  } else {
    closeReadings = 0;
  }

  bool cooldownElapsed = millis() - lastScanAt >= SCAN_COOLDOWN_MS;

  if (closeReadings >= DETECT_CONFIRM_COUNT && cooldownElapsed && !doorIsOpen) {
    lastScanAt = millis();
    closeReadings = 0;

    String name;
    bool recognized = askPiToRecognizeFace(name);

    if (recognized) {
      Serial.printf("[esp32] access granted to %s -> opening door\n", name.c_str());
      setDoor(true);
    } else {
      Serial.println("[esp32] access denied -> door stays shut");
      denyAccessFeedback();
    }
  }

  delay(150); // ~6-7 distance samples per second is plenty for a doorway
}
