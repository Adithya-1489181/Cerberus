// Copy this file to config.h and fill in your own values.
// config.h is gitignored so your WiFi password never gets committed.
#pragma once

// ---- WiFi: the access point created by the Raspberry Pi (see README "Network setup") ----
#define WIFI_SSID     "CerberusNet"
#define WIFI_PASSWORD "12345678"   // WPA2 needs at least 8 characters

// ---- Raspberry Pi running raspberry-pi/recognize_server.py ----
#define PI_HOST "192.168.4.1"    // fixed Pi address on its own access point
#define PI_PORT 5001
#define PI_SCAN_PATH "/scan"

// ---- Pins ----
#define TRIG_PIN      5    // HC-SR04 trigger
#define ECHO_PIN      18   // HC-SR04 echo (through a voltage divider, see README)
#define SERVO_PIN     13   // door-lock/latch servo signal
#define LED_GREEN_PIN 25   // lit while the door is open / access granted
#define LED_RED_PIN   26   // lit on access denied
#define BUZZER_PIN    27   // optional piezo buzzer, short beep on denial

// ---- Behaviour ----
#define DETECT_DISTANCE_CM   60     // trigger a scan when something is closer than this
#define DETECT_CONFIRM_COUNT 3      // consecutive close readings required (debounce)
#define SCAN_COOLDOWN_MS     6000   // minimum time between two scans
#define DOOR_OPEN_ANGLE      90     // servo angle when the door is unlocked/open
#define DOOR_CLOSED_ANGLE    0      // servo angle when the door is locked/closed
#define DOOR_OPEN_MS         5000   // how long the door stays open after recognition
#define HTTP_TIMEOUT_MS      4000   // max time to wait for the Pi's response
