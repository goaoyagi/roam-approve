#include "ApprovalApp.h"

#include <algorithm>
#include <cctype>
#include <ctime>
#include <limits>
#include <utility>

#include <ArduinoJson.h>

namespace {
constexpr char kRequestTopicPrefix[] = "roam/approval/request/";
constexpr char kResolvedTopic[] = "roam/approval/resolved";
constexpr size_t kMaxPendings = 8;
constexpr size_t kMaxLines = 4;

bool isDigits(const std::string& value, size_t offset, size_t length) {
  if (offset + length > value.size()) return false;
  for (size_t i = offset; i < offset + length; ++i) {
    if (!std::isdigit(static_cast<unsigned char>(value[i]))) return false;
  }
  return true;
}

bool isLeapYear(int year) {
  return year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
}

int daysInMonth(int year, int month) {
  static constexpr int days[] = {31, 28, 31, 30, 31, 30,
                                 31, 31, 30, 31, 30, 31};
  if (month == 2 && isLeapYear(year)) return 29;
  return days[month - 1];
}

int64_t daysFromCivil(int year, unsigned month, unsigned day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yearOfEra = static_cast<unsigned>(year - era * 400);
  const unsigned adjustedMonth = month > 2 ? month - 3 : month + 9;
  const unsigned dayOfYear = (153 * adjustedMonth + 2) / 5 + day - 1;
  const unsigned dayOfEra =
      yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear;
  return static_cast<int64_t>(era) * 146097 + dayOfEra - 719468;
}

bool isValidId(const std::string& id) {
  if (id.size() != 36) return false;
  for (size_t i = 0; i < id.size(); ++i) {
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (id[i] != '-') return false;
    } else if (!std::isxdigit(static_cast<unsigned char>(id[i]))) {
      return false;
    }
  }
  return true;
}

std::string joinUrl(const std::string& base, const std::string& path) {
  if (!base.empty() && base.back() == '/') return base.substr(0, base.size() - 1) + path;
  return base + path;
}
}  // namespace

PowerPolicy::PowerPolicy(hal::IDisplay& display, hal::IPower& power,
                         uint32_t idleDimMs, uint8_t normalBrightness,
                         uint8_t dimBrightness)
    : display_(display),
      power_(power),
      idleDimMs_(idleDimMs),
      normalBrightness_(normalBrightness),
      dimBrightness_(dimBrightness) {}

void PowerPolicy::begin(uint32_t nowMs) { lastActivityMs_ = nowMs; }

void PowerPolicy::activity(uint32_t nowMs) {
  lastActivityMs_ = nowMs;
  if (!dimmed_) return;
  dimmed_ = false;
  display_.setBrightness(normalBrightness_);
  power_.setCpuMhz(240);
  power_.setWifiSleep(false);
}

void PowerPolicy::tick(uint32_t nowMs) {
  if (dimmed_ || static_cast<uint32_t>(nowMs - lastActivityMs_) < idleDimMs_) {
    return;
  }
  dimmed_ = true;
  display_.setBrightness(dimBrightness_);
  power_.setCpuMhz(80);
  power_.setWifiSleep(true);
}

ApprovalApp::ApprovalApp(hal::IDisplay& display, hal::IButtons& buttons,
                         hal::IMqtt& mqtt, hal::IHttp& http, hal::IPower& power,
                         hal::IClock& clock, const ApprovalConfig& config)
    : display_(display),
      buttons_(buttons),
      mqtt_(mqtt),
      http_(http),
      clock_(clock),
      config_(config),
      powerPolicy_(display, power, config.idleDimMs,
                   config.normalBrightness, config.dimBrightness) {}

void ApprovalApp::begin() {
  const uint32_t nowMs = clock_.millis();
  powerPolicy_.begin(nowMs);
  mqtt_.onMessage([this](const std::string& topic, const std::string& payload) {
    handleMqttMessage(topic, payload);
  });
  requestSync();
  renderIdle();
}

void ApprovalApp::requestSync() { syncDirty_ = true; }

void ApprovalApp::handleMqttMessage(const std::string& topic,
                                    const std::string& payload) {
  (void)payload;
  if (topic == kResolvedTopic ||
      topic.compare(0, sizeof(kRequestTopicPrefix) - 1, kRequestTopicPrefix) ==
          0) {
    requestSync();
  }
}

void ApprovalApp::maintainMqtt() {
  mqtt_.loop();
  if (!mqtt_.connected()) wasMqttConnected_ = false;
  uint32_t nowMs = clock_.millis();
  if (!mqtt_.connected() &&
      (!mqttRetryScheduled_ ||
       static_cast<int32_t>(nowMs - nextMqttAttemptMs_) >= 0)) {
    if (mqtt_.connect() && mqtt_.connected()) {
      mqttBackoff_.reset();
      mqttRetryScheduled_ = false;
    } else {
      nextMqttAttemptMs_ = nowMs + mqttBackoff_.nextDelayMs();
      mqttRetryScheduled_ = true;
    }
  }

  const bool connected = mqtt_.connected();
  if (connected && !wasMqttConnected_) {
    mqtt_.subscribe("roam/approval/request/+");
    mqtt_.subscribe(kResolvedTopic);
    requestSync();
    mqttBackoff_.reset();
    mqttRetryScheduled_ = false;
  }
  wasMqttConnected_ = connected;
}

std::string ApprovalApp::requestsUrl() const {
  return joinUrl(config_.bridgeUrl, "/v1/requests?status=pending");
}

void ApprovalApp::performSync(uint32_t nowMs) {
  if (hasSuccessfulSync_ &&
      static_cast<uint32_t>(nowMs - lastSuccessfulSyncMs_) >=
          config_.periodicSyncMs) {
    requestSync();
  }
  if (!syncDirty_) return;
  if (hasSyncAttempt_ &&
      static_cast<uint32_t>(nowMs - lastSyncAttemptMs_) <
          config_.syncMinIntervalMs) {
    return;
  }
  if (syncRetryScheduled_ &&
      static_cast<int32_t>(nowMs - nextSyncRetryMs_) < 0) {
    return;
  }

  std::string body;
  lastSyncAttemptMs_ = nowMs;
  hasSyncAttempt_ = true;
  const int status = http_.getJson(requestsUrl(), config_.deviceToken, body);
  if (status < 200 || status >= 300 ||
      body.size() > hal::kMaxHttpResponseBytes) {
    syncFailed_ = true;
    syncDirty_ = true;
    nextSyncRetryMs_ = nowMs + syncBackoff_.nextDelayMs();
    syncRetryScheduled_ = true;
    render();
    return;
  }

  JsonDocument filter;
  filter[0]["id"] = true;
  filter[0]["agent"] = true;
  filter[0]["title"] = true;
  filter[0]["lines"][0] = true;
  filter[0]["expires_at"] = true;
  JsonDocument document;
  const DeserializationError error =
      deserializeJson(document, body, DeserializationOption::Filter(filter),
                     DeserializationOption::NestingLimit(8));
  if (error || !document.is<JsonArray>()) {
    syncFailed_ = true;
    syncDirty_ = true;
    nextSyncRetryMs_ = nowMs + syncBackoff_.nextDelayMs();
    syncRetryScheduled_ = true;
    render();
    return;
  }

  std::vector<Pending> next;
  std::vector<std::string> responseIds;
  const int64_t epochNow = clock_.epochSeconds();
  for (JsonVariantConst value : document.as<JsonArrayConst>()) {
    const char* id = value["id"] | static_cast<const char*>(nullptr);
    if (id == nullptr || !isValidId(id)) continue;
    responseIds.emplace_back(id);
    if (std::find(locallyExpiredIds_.begin(), locallyExpiredIds_.end(), id) !=
            locallyExpiredIds_.end() ||
        next.size() >= kMaxPendings) {
      continue;
    }
    const char* agent = value["agent"] | static_cast<const char*>(nullptr);
    const char* title = value["title"] | static_cast<const char*>(nullptr);
    const char* expires = value["expires_at"] | static_cast<const char*>(nullptr);
    if (agent == nullptr || title == nullptr || expires == nullptr) {
      continue;
    }

    Pending item;
    item.id = id;
    item.agent = agent;
    item.title = title;
    if (!parseIso8601(expires, item.expiresAt)) continue;
    JsonArrayConst lineValues = value["lines"].as<JsonArrayConst>();
    for (JsonVariantConst line : lineValues) {
      if (item.lines.size() >= kMaxLines) break;
      const char* text = line | static_cast<const char*>(nullptr);
      if (text != nullptr) item.lines.emplace_back(text);
    }

    auto previous = std::find_if(
        pending_.begin(), pending_.end(),
        [&item](const Pending& candidate) { return candidate.id == item.id; });
    if (previous != pending_.end()) {
      item.firstSeenMs = previous->firstSeenMs;
    } else {
      item.firstSeenMs = nowMs;
    }
    const bool expired =
        epochNow > 0 ? epochNow >= item.expiresAt
                     : static_cast<uint32_t>(nowMs - item.firstSeenMs) >=
                           config_.fallbackTimeoutMs;
    if (expired) {
      locallyExpiredIds_.push_back(item.id);
    } else {
      next.push_back(std::move(item));
    }
  }
  locallyExpiredIds_.erase(
      std::remove_if(locallyExpiredIds_.begin(), locallyExpiredIds_.end(),
                     [&responseIds](const std::string& id) {
                       return std::find(responseIds.begin(), responseIds.end(),
                                        id) == responseIds.end();
                     }),
      locallyExpiredIds_.end());

  bool hasNewRequest = false;
  for (const Pending& item : next) {
    if (!containsPending(item.id)) {
      hasNewRequest = true;
      break;
    }
  }
  pending_ = std::move(next);
  syncDirty_ = false;
  syncFailed_ = false;
  syncRetryScheduled_ = false;
  syncBackoff_.reset();
  hasSuccessfulSync_ = true;
  lastSuccessfulSyncMs_ = nowMs;
  if (hasNewRequest) powerPolicy_.activity(nowMs);
  updateVisibleState();
}

void ApprovalApp::expireRequests(uint32_t nowMs) {
  const int64_t epochNow = clock_.epochSeconds();
  const size_t before = pending_.size();
  for (const Pending& item : pending_) {
    const bool expired =
        epochNow > 0 ? epochNow >= item.expiresAt
                     : static_cast<uint32_t>(nowMs - item.firstSeenMs) >=
                           config_.fallbackTimeoutMs;
    if (expired &&
        std::find(locallyExpiredIds_.begin(), locallyExpiredIds_.end(),
                  item.id) == locallyExpiredIds_.end()) {
      locallyExpiredIds_.push_back(item.id);
    }
  }
  pending_.erase(
      std::remove_if(pending_.begin(), pending_.end(),
                     [this, nowMs, epochNow](const Pending& item) {
                       if (epochNow > 0) return epochNow >= item.expiresAt;
                       return static_cast<uint32_t>(nowMs - item.firstSeenMs) >=
                              config_.fallbackTimeoutMs;
                     }),
      pending_.end());
  if (pending_.size() != before) updateVisibleState();
}

bool ApprovalApp::containsPending(const std::string& id) const {
  return std::any_of(pending_.begin(), pending_.end(),
                     [&id](const Pending& item) { return item.id == id; });
}

void ApprovalApp::erasePending(const std::string& id) {
  pending_.erase(std::remove_if(pending_.begin(), pending_.end(),
                                [&id](const Pending& item) {
                                  return item.id == id;
                                }),
                 pending_.end());
}

void ApprovalApp::updateVisibleState() {
  if (state_ == State::Sending || state_ == State::Done) return;
  const std::string previousId = displayedId_;
  if (pending_.empty()) {
    displayedId_.clear();
    state_ = State::Idle;
  } else {
    displayedId_ = pending_.front().id;
    state_ = State::Showing;
  }
  if (displayedId_ != previousId) sendFailed_ = false;
  if (displayedId_ != previousId || state_ == State::Showing) render();
  else renderIdle();
}

void ApprovalApp::handleButtons(uint32_t nowMs) {
  const bool approve = buttons_.wasPressedA();
  const bool reject = buttons_.wasPressedB();
  if (!approve && !reject) return;

  const bool wasDimmed = powerPolicy_.isDimmed();
  powerPolicy_.activity(nowMs);
  if (wasDimmed) {
    render();
    return;
  }
  if (approve == reject) return;
  if (state_ != State::Showing || displayedId_.empty()) return;

  const bool stillPending = containsPending(displayedId_);
  if (!stillPending) {
    displayedId_.clear();
    state_ = State::Idle;
    renderIdle();
    return;
  }
  sendDecision(approve, nowMs);
}

void ApprovalApp::sendDecision(bool approve, uint32_t nowMs) {
  const std::string id = displayedId_;
  state_ = State::Sending;
  sendFailed_ = false;
  render();
  const std::string decision = approve ? "approve" : "reject";
  JsonDocument bodyDocument;
  bodyDocument["decision"] = decision;
  bodyDocument["source"] = config_.source;
  std::string body;
  serializeJson(bodyDocument, body);
  const int status = http_.postJson(
      joinUrl(config_.bridgeUrl, "/v1/requests/" + id + "/decision"),
      config_.deviceToken, body);

  if (status == 200) {
    erasePending(id);
    doneMessage_ = approve ? "Approved" : "Rejected";
    state_ = State::Done;
    doneUntilMs_ = nowMs + config_.doneDisplayMs;
    render();
  } else if (status == 404 || status == 409) {
    erasePending(id);
    displayedId_.clear();
    state_ = State::Idle;
    requestSync();
    renderIdle();
  } else {
    state_ = State::Showing;
    sendFailed_ = true;
    render();
  }
}

void ApprovalApp::tick() {
  maintainMqtt();
  uint32_t nowMs = clock_.millis();
  performSync(nowMs);
  expireRequests(nowMs);

  if (state_ == State::Done &&
      static_cast<int32_t>(nowMs - doneUntilMs_) >= 0) {
    state_ = State::Idle;
    displayedId_.clear();
    requestSync();
    renderIdle();
  }
  handleButtons(nowMs);
  powerPolicy_.tick(clock_.millis());
}

void ApprovalApp::render() {
  if (state_ == State::Idle) {
    renderIdle();
  } else if (state_ == State::Showing) {
    renderRequest();
  } else if (state_ == State::Sending) {
    display_.clear();
    display_.drawLines({"Sending..."});
  } else {
    display_.clear();
    display_.drawLines({doneMessage_});
  }
}

void ApprovalApp::renderIdle() {
  display_.clear();
  std::vector<std::string> lines{"roam-approve", "waiting..."};
  if (syncFailed_) lines.emplace_back("bridge err");
  display_.drawLines(lines);
}

void ApprovalApp::renderRequest() {
  auto current = std::find_if(
      pending_.begin(), pending_.end(), [this](const Pending& item) {
        return item.id == displayedId_;
      });
  if (current == pending_.end()) {
    renderIdle();
    return;
  }

  display_.clear();
  std::vector<std::string> lines;
  std::string header = truncateUtf8(current->agent, 15) + " " +
                       std::to_string(
                           static_cast<size_t>(current - pending_.begin()) + 1) +
                       "/" + std::to_string(pending_.size());
  lines.push_back(truncateUtf8(header, 20));
  lines.push_back(truncateUtf8(current->title, 20));
  const size_t maxDetails = sendFailed_ ? 2 : 3;
  const size_t visibleDetails =
      std::min<size_t>(maxDetails, current->lines.size());
  for (size_t i = 0; i < visibleDetails; ++i) {
    lines.push_back(truncateUtf8(current->lines[i], 20));
  }
  if (sendFailed_) lines.push_back("send failed, retry");
  lines.push_back("A:OK  B:NG");
  display_.drawLines(lines);
}

std::string ApprovalApp::truncateUtf8(const std::string& value,
                                      size_t maxBytes) {
  if (value.size() <= maxBytes) return value;
  size_t end = maxBytes;
  while (end > 0 &&
         (static_cast<unsigned char>(value[end]) & 0xC0) == 0x80) {
    --end;
  }
  if (end == maxBytes) return value.substr(0, end);
  const unsigned char lead = static_cast<unsigned char>(value[end]);
  size_t sequenceLength = 1;
  if ((lead & 0xE0) == 0xC0) sequenceLength = 2;
  else if ((lead & 0xF0) == 0xE0) sequenceLength = 3;
  else if ((lead & 0xF8) == 0xF0) sequenceLength = 4;
  if (end + sequenceLength > maxBytes) return value.substr(0, end);
  return value.substr(0, maxBytes);
}

bool ApprovalApp::parseIso8601(const std::string& value,
                               int64_t& epochSeconds) {
  if (value.size() < 20 || value[4] != '-' || value[7] != '-' ||
      (value[10] != 'T' && value[10] != 't') || value[13] != ':' ||
      value[16] != ':' || !isDigits(value, 0, 4) ||
      !isDigits(value, 5, 2) || !isDigits(value, 8, 2) ||
      !isDigits(value, 11, 2) || !isDigits(value, 14, 2) ||
      !isDigits(value, 17, 2)) {
    return false;
  }

  const int year = std::stoi(value.substr(0, 4));
  const int month = std::stoi(value.substr(5, 2));
  const int day = std::stoi(value.substr(8, 2));
  const int hour = std::stoi(value.substr(11, 2));
  const int minute = std::stoi(value.substr(14, 2));
  const int second = std::stoi(value.substr(17, 2));
  if (year < 1 || month < 1 || month > 12 || day < 1 ||
      day > daysInMonth(year, month) || hour > 23 || minute > 59 ||
      second > 59) {
    return false;
  }

  size_t offset = 19;
  if (offset < value.size() && value[offset] == '.') {
    ++offset;
    const size_t fractionStart = offset;
    while (offset < value.size() &&
           std::isdigit(static_cast<unsigned char>(value[offset]))) {
      ++offset;
    }
    if (offset == fractionStart) return false;
  }

  int timezoneOffset = 0;
  if (offset < value.size() && (value[offset] == 'Z' || value[offset] == 'z')) {
    ++offset;
  } else if (offset + 6 == value.size() &&
             (value[offset] == '+' || value[offset] == '-') &&
             value[offset + 3] == ':' && isDigits(value, offset + 1, 2) &&
             isDigits(value, offset + 4, 2)) {
    const int zoneHour = std::stoi(value.substr(offset + 1, 2));
    const int zoneMinute = std::stoi(value.substr(offset + 4, 2));
    if (zoneHour > 23 || zoneMinute > 59) return false;
    timezoneOffset = (zoneHour * 60 + zoneMinute) * 60;
    if (value[offset] == '-') timezoneOffset = -timezoneOffset;
    offset += 6;
  } else {
    return false;
  }
  if (offset != value.size()) return false;

  const int64_t days = daysFromCivil(year, static_cast<unsigned>(month),
                                    static_cast<unsigned>(day));
  epochSeconds = days * 86400 + hour * 3600 + minute * 60 + second -
                 timezoneOffset;
  return true;
}
