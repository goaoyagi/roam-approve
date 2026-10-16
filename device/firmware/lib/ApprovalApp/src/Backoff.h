#pragma once

#include <cstdint>

class Backoff {
 public:
  explicit Backoff(uint32_t initialMs = 1000, uint32_t maxMs = 30000)
      : initialMs_(initialMs > maxMs ? maxMs : initialMs),
        maxMs_(maxMs),
        currentMs_(0) {}

  uint32_t nextDelayMs() {
    if (currentMs_ == 0) {
      currentMs_ = initialMs_;
    } else if (currentMs_ < maxMs_) {
      currentMs_ = currentMs_ > maxMs_ / 2 ? maxMs_ : currentMs_ * 2;
    }
    return currentMs_;
  }

  void reset() { currentMs_ = 0; }

 private:
  uint32_t initialMs_;
  uint32_t maxMs_;
  uint32_t currentMs_;
};
