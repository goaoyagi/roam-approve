#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "Backoff.h"
#include "Hal.h"

struct ApprovalConfig {
  ApprovalConfig(const std::string& bridge, const std::string& token,
                 const std::string& requestSource = "m5stickc")
      : bridgeUrl(bridge), deviceToken(token), source(requestSource) {}

  std::string bridgeUrl;
  std::string deviceToken;
  std::string source = "m5stickc";
  uint32_t syncMinIntervalMs = 1000;
  uint32_t periodicSyncMs = 30000;
  uint32_t doneDisplayMs = 1500;
  uint32_t fallbackTimeoutMs = 300000;
  uint32_t idleDimMs = 30000;
  uint8_t normalBrightness = 100;
  uint8_t dimBrightness = 8;
};

class PowerPolicy {
 public:
  PowerPolicy(hal::IDisplay& display, hal::IPower& power,
              uint32_t idleDimMs = 30000, uint8_t normalBrightness = 100,
              uint8_t dimBrightness = 8);

  void begin(uint32_t nowMs);
  void activity(uint32_t nowMs);
  void tick(uint32_t nowMs);
  bool isDimmed() const { return dimmed_; }

 private:
  hal::IDisplay& display_;
  hal::IPower& power_;
  uint32_t idleDimMs_;
  uint32_t lastActivityMs_ = 0;
  uint8_t normalBrightness_;
  uint8_t dimBrightness_;
  bool dimmed_ = false;
};

class ApprovalApp {
 public:
  enum class State { Idle, Showing, Sending, Done };

  ApprovalApp(hal::IDisplay& display, hal::IButtons& buttons, hal::IMqtt& mqtt,
              hal::IHttp& http, hal::IPower& power, hal::IClock& clock,
              const ApprovalConfig& config);

  void begin();
  void tick();
  void requestSync();

  State state() const { return state_; }
  const std::string& displayedId() const { return displayedId_; }
  bool lastSyncFailed() const { return syncFailed_; }

  static bool parseIso8601(const std::string& value, int64_t& epochSeconds);
  static std::string truncateUtf8(const std::string& value, size_t maxBytes);

 private:
  struct Pending {
    std::string id;
    std::string agent;
    std::string title;
    std::vector<std::string> lines;
    int64_t expiresAt = 0;
    uint32_t firstSeenMs = 0;
  };

  void handleMqttMessage(const std::string& topic,
                         const std::string& payload);
  void maintainMqtt();
  void performSync(uint32_t nowMs);
  void expireRequests(uint32_t nowMs);
  void updateVisibleState();
  void handleButtons(uint32_t nowMs);
  void sendDecision(bool approve, uint32_t nowMs);
  void render();
  void renderIdle();
  void renderRequest();
  void erasePending(const std::string& id);
  bool containsPending(const std::string& id) const;
  std::string requestsUrl() const;

  hal::IDisplay& display_;
  hal::IButtons& buttons_;
  hal::IMqtt& mqtt_;
  hal::IHttp& http_;
  hal::IClock& clock_;
  ApprovalConfig config_;
  PowerPolicy powerPolicy_;
  State state_ = State::Idle;
  std::vector<Pending> pending_;
  std::vector<std::string> locallyExpiredIds_;
  std::string displayedId_;
  std::string doneMessage_;
  uint32_t doneUntilMs_ = 0;
  bool syncDirty_ = false;
  bool syncFailed_ = false;
  bool hasSyncAttempt_ = false;
  bool hasSuccessfulSync_ = false;
  bool wasMqttConnected_ = false;
  bool sendFailed_ = false;
  uint32_t lastSyncAttemptMs_ = 0;
  uint32_t lastSuccessfulSyncMs_ = 0;
  uint32_t nextSyncRetryMs_ = 0;
  uint32_t nextMqttAttemptMs_ = 0;
  bool syncRetryScheduled_ = false;
  bool mqttRetryScheduled_ = false;
  Backoff syncBackoff_;
  Backoff mqttBackoff_;
};
