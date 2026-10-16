#pragma once

#ifdef ARDUINO

#include <HTTPClient.h>
#include <M5StickCPlus.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "ApprovalApp.h"
#include "Hal.h"

class DeviceDisplay final : public hal::IDisplay {
 public:
  void clear() override;
  void drawLines(const std::vector<std::string>& lines) override;
  void setBrightness(uint8_t brightness) override;
};

class M5Buttons final : public hal::IButtons {
 public:
  bool wasPressedA() override;
  bool wasPressedB() override;
};

class M5Mqtt final : public hal::IMqtt {
 public:
  M5Mqtt();
  bool connect() override;
  bool connected() const override;
  void subscribe(const char* topic) override;
  void loop() override;
  void onMessage(MessageHandler handler) override;

 private:
  static void receive(char* topic, uint8_t* payload, unsigned int length);
  bool connectWifi();

  WiFiClient wifiClient_;
  mutable PubSubClient client_;
  MessageHandler handler_;
  Backoff wifiBackoff_;
  uint32_t nextWifiAttemptMs_ = 0;
  bool wifiRetryScheduled_ = false;
  static M5Mqtt* active_;
};

class M5Http final : public hal::IHttp {
 public:
  int postJson(const std::string& url, const std::string& bearer,
               const std::string& body) override;
  int getJson(const std::string& url, const std::string& bearer,
              const BodyHandler& onBody) override;

 private:
  class StreamBodyReader final : public hal::IByteReader {
   public:
    StreamBodyReader(Stream& stream, int contentLength);
    int read() override;
    size_t readBytes(char* buffer, size_t length) override;

   private:
    Stream& stream_;
    int remaining_;
    bool bounded_;
  };

  static void addHeaders(HTTPClient& client, const std::string& bearer);
};

class M5Power final : public hal::IPower {
 public:
  void setCpuMhz(uint32_t mhz) override;
  void setWifiSleep(bool enabled) override;
};

class M5Clock final : public hal::IClock {
 public:
  uint32_t millis() const override;
  int64_t epochSeconds() const override;
};

#endif
