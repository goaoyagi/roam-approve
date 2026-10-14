#ifdef ARDUINO

#include "M5Hal.h"

#include <ctime>
#include <string>

#if __has_include("../../include/config.h")
#include "../../include/config.h"
#endif
#if !defined(WIFI_SSID) || !defined(WIFI_PASSWORD) || !defined(MQTT_HOST) || \
    !defined(MQTT_PORT)
#include "../../include/config.example.h"
#endif

M5Mqtt* M5Mqtt::active_ = nullptr;

void DeviceDisplay::clear() { M5.Lcd.fillScreen(BLACK); }

void DeviceDisplay::drawLines(const std::vector<std::string>& lines) {
  M5.Lcd.setTextColor(WHITE, BLACK);
  M5.Lcd.setTextSize(1);
  for (size_t i = 0; i < lines.size(); ++i) {
    M5.Lcd.setCursor(0, static_cast<int32_t>(i * 20));
    M5.Lcd.println(lines[i].c_str());
  }
}

void DeviceDisplay::setBrightness(uint8_t brightness) {
  M5.Axp.ScreenBreath(brightness);
}

bool M5Buttons::wasPressedA() { return M5.BtnA.wasPressed(); }

bool M5Buttons::wasPressedB() { return M5.BtnB.wasPressed(); }

M5Mqtt::M5Mqtt() : client_(wifiClient_) {
  active_ = this;
  client_.setServer(MQTT_HOST, MQTT_PORT);
  client_.setBufferSize(2048);
  client_.setCallback(&M5Mqtt::receive);
}

bool M5Mqtt::connectWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiBackoff_.reset();
    wifiRetryScheduled_ = false;
    return true;
  }

  const uint32_t nowMs = millis();
  if (!wifiRetryScheduled_ ||
      static_cast<int32_t>(nowMs - nextWifiAttemptMs_) >= 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    nextWifiAttemptMs_ = nowMs + wifiBackoff_.nextDelayMs();
    wifiRetryScheduled_ = true;
  }
  return false;
}

bool M5Mqtt::connect() {
  if (!connectWifi()) return false;
  if (client_.connected()) return true;
  return client_.connect("roam-approve");
}

bool M5Mqtt::connected() const { return client_.connected(); }

void M5Mqtt::subscribe(const char* topic) { client_.subscribe(topic); }

void M5Mqtt::loop() {
  if (WiFi.status() == WL_CONNECTED) client_.loop();
}

void M5Mqtt::onMessage(MessageHandler handler) {
  handler_ = std::move(handler);
}

void M5Mqtt::receive(char* topic, uint8_t* payload, unsigned int length) {
  if (active_ == nullptr || !active_->handler_) return;
  std::string message;
  if (payload != nullptr && length > 0) {
    message.assign(reinterpret_cast<char*>(payload), length);
  }
  active_->handler_(topic == nullptr ? std::string() : std::string(topic),
                    message);
}

void M5Http::addHeaders(HTTPClient& client, const std::string& bearer) {
  client.setConnectTimeout(3000);
  client.setTimeout(3000);
  client.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  client.addHeader("Authorization", String("Bearer ") + bearer.c_str());
  client.addHeader("Content-Type", "application/json");
}

int M5Http::postJson(const std::string& url, const std::string& bearer,
                     const std::string& body) {
  HTTPClient client;
  if (!client.begin(url.c_str())) return -1;
  addHeaders(client, bearer);
  const int status = client.POST(String(body.c_str()));
  client.end();
  return status;
}

int M5Http::getJson(const std::string& url, const std::string& bearer,
                    std::string& outBody) {
  HTTPClient client;
  if (!client.begin(url.c_str())) return -1;
  addHeaders(client, bearer);
  const int status = client.GET();
  if (status >= 200 && status < 300) {
    outBody = client.getString().c_str();
  }
  client.end();
  return status;
}

void M5Power::setCpuMhz(uint32_t mhz) { setCpuFrequencyMhz(mhz); }

void M5Power::setWifiSleep(bool enabled) { WiFi.setSleep(enabled); }

uint32_t M5Clock::millis() const { return ::millis(); }

int64_t M5Clock::epochSeconds() const {
  const time_t now = time(nullptr);
  return now > 1600000000 ? static_cast<int64_t>(now) : 0;
}

#endif
