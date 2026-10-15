#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <ArduinoJson.h>

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
  // Presses within this window after the displayed request changes are
  // ignored so a press aimed at the previous request never decides a new one.
  uint32_t inputGuardMs = 1000;
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
  // The built-in LCD font is ASCII only: each UTF-8 code point becomes one
  // cell, non-ASCII is shown as '?', and the result is capped at maxChars.
  static std::string toDisplayText(const std::string& value, size_t maxChars);

 private:
  struct Pending {
    std::string id;
    std::string agent;
    std::string title;
    std::vector<std::string> lines;
    int64_t expiresAt = 0;
  };

  bool readPendingList(hal::IByteReader& body, int64_t epochNow,
                       std::vector<Pending>& next,
                       std::vector<std::string>& responseIds);
  void collectPending(const JsonDocument& element, int64_t epochNow,
                      std::vector<Pending>& next,
                      std::vector<std::string>& responseIds);
  bool isExpired(const Pending& item, int64_t epochNow) const;
  void draw(const std::vector<std::string>& lines);

  void handleMqttMessage(const std::string& topic,
                         const std::string& payload);
  void maintainMqtt();
  void performSync(uint32_t nowMs);
  void expireRequests();
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
  std::vector<std::string> drawnLines_;
  bool hasDrawn_ = false;
  uint32_t displayChangedMs_ = 0;
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
