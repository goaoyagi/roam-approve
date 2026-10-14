// Wiring only: HAL (M5 implementation) + ApprovalApp.
// Excluded from the native test env (native builds test/ only).
#ifdef ARDUINO
#include <Arduino.h>

#if __has_include("../include/config.h")
#include "../include/config.h"
#endif
#if !defined(BRIDGE_URL) || !defined(DEVICE_TOKEN)
#warning "config.h not found; using example firmware configuration"
#include "../include/config.example.h"
#endif

#include <time.h>

#include "ApprovalApp.h"
#include "hal_m5/M5Hal.h"

namespace {
DeviceDisplay display;
M5Buttons buttons;
M5Mqtt mqtt;
M5Http http;
M5Power power;
M5Clock clockSource;
ApprovalConfig config{BRIDGE_URL, DEVICE_TOKEN};
ApprovalApp app(display, buttons, mqtt, http, power, clockSource, config);
}  // namespace

void setup() {
  M5.begin();
  M5.Lcd.setRotation(1);
  WiFi.mode(WIFI_STA);
  configTime(0, 0, "pool.ntp.org");
  app.begin();
}

void loop() {
  M5.update();
  app.tick();
  delay(10);
}
#endif
