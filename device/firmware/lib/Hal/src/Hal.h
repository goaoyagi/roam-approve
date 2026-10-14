#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace hal {

class IDisplay {
 public:
  virtual ~IDisplay() = default;
  virtual void clear() = 0;
  virtual void drawLines(const std::vector<std::string>& lines) = 0;
  virtual void setBrightness(uint8_t brightness) = 0;
};

class IButtons {
 public:
  virtual ~IButtons() = default;
  virtual bool wasPressedA() = 0;
  virtual bool wasPressedB() = 0;
};

class IMqtt {
 public:
  using MessageHandler =
      std::function<void(const std::string& topic, const std::string& payload)>;

  virtual ~IMqtt() = default;
  virtual bool connect() = 0;
  virtual bool connected() const = 0;
  virtual void subscribe(const char* topic) = 0;
  virtual void loop() = 0;
  virtual void onMessage(MessageHandler handler) = 0;
};

class IHttp {
 public:
  virtual ~IHttp() = default;
  virtual int postJson(const std::string& url, const std::string& bearer,
                       const std::string& body) = 0;
  virtual int getJson(const std::string& url, const std::string& bearer,
                      std::string& outBody) = 0;
};

class IPower {
 public:
  virtual ~IPower() = default;
  virtual void setCpuMhz(uint32_t mhz) = 0;
  virtual void setWifiSleep(bool enabled) = 0;
};

class IClock {
 public:
  virtual ~IClock() = default;
  virtual uint32_t millis() const = 0;
  virtual int64_t epochSeconds() const = 0;
};

}  // namespace hal
