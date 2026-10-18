#include <algorithm>
#include <cstdio>
#include <deque>
#include <string>
#include <utility>
#include <vector>

#include <unity.h>

#include "ApprovalApp.h"

namespace {
constexpr char kId1[] = "11111111-1111-4111-8111-111111111111";
constexpr char kId2[] = "22222222-2222-4222-8222-222222222222";
constexpr char kFakeId[] = "33333333-3333-4333-8333-333333333333";

struct DisplayMock : hal::IDisplay {
  std::vector<std::vector<std::string>> draws;
  std::vector<uint8_t> brightness;
  int clears = 0;

  void clear() override { ++clears; }
  void drawLines(const std::vector<std::string>& lines) override {
    draws.push_back(lines);
  }
  void setBrightness(uint8_t value) override { brightness.push_back(value); }

  bool sawText(const std::string& text) const {
    for (const auto& draw : draws) {
      for (const auto& line : draw) {
        if (line.find(text) != std::string::npos) return true;
      }
    }
    return false;
  }

  bool lastDrawHasText(const std::string& text) const {
    if (draws.empty()) return false;
    return std::any_of(draws.back().begin(), draws.back().end(),
                       [&text](const std::string& line) {
                         return line.find(text) != std::string::npos;
                       });
  }
};

struct ButtonsMock : hal::IButtons {
  bool pressedA = false;
  bool pressedB = false;
  bool wasPressedA() override {
    const bool value = pressedA;
    pressedA = false;
    return value;
  }
  bool wasPressedB() override {
    const bool value = pressedB;
    pressedB = false;
    return value;
  }
};

struct MqttMock : hal::IMqtt {
  bool isConnected = false;
  bool connectResult = true;
  int connectCalls = 0;
  int loopCalls = 0;
  std::vector<std::string> subscriptions;
  MessageHandler handler;

  bool connect() override {
    ++connectCalls;
    isConnected = connectResult;
    return connectResult;
  }
  bool connected() const override { return isConnected; }
  void subscribe(const char* topic) override { subscriptions.emplace_back(topic); }
  void loop() override { ++loopCalls; }
  void onMessage(MessageHandler value) override { handler = std::move(value); }
  void fire(const std::string& topic, const std::string& payload) {
    if (handler) handler(topic, payload);
  }
};

struct StringReader : hal::IByteReader {
  explicit StringReader(const std::string& value) : data(value) {}
  int read() override {
    if (offset >= data.size()) return -1;
    return static_cast<unsigned char>(data[offset++]);
  }
  size_t readBytes(char* buffer, size_t length) override {
    const size_t count = std::min(length, data.size() - offset);
    data.copy(buffer, count, offset);
    offset += count;
    return count;
  }
  const std::string& data;
  size_t offset = 0;
};

struct HttpMock : hal::IHttp {
  struct Response {
    int status;
    std::string body;
  };
  int getStatus = 200;
  std::string getBody = "[]";
  std::deque<Response> getResponses;
  std::deque<int> postStatuses;
  int getCalls = 0;
  int postCalls = 0;
  std::string lastGetUrl;
  std::string lastGetBearer;
  std::string lastPostUrl;
  std::string lastPostBearer;
  std::string lastPostBody;

  int postJson(const std::string& url, const std::string& bearer,
               const std::string& body) override {
    ++postCalls;
    lastPostUrl = url;
    lastPostBearer = bearer;
    lastPostBody = body;
    if (postStatuses.empty()) return 200;
    const int result = postStatuses.front();
    postStatuses.pop_front();
    return result;
  }
  int getJson(const std::string& url, const std::string& bearer,
              const BodyHandler& onBody) override {
    ++getCalls;
    lastGetUrl = url;
    lastGetBearer = bearer;
    Response response{getStatus, getBody};
    if (!getResponses.empty()) {
      response = getResponses.front();
      getResponses.pop_front();
    }
    if (response.status >= 200 && response.status < 300) {
      StringReader reader(response.body);
      onBody(reader);
    }
    return response.status;
  }
};

struct PowerMock : hal::IPower {
  std::vector<uint32_t> cpuMhz;
  std::vector<bool> wifiSleep;
  void setCpuMhz(uint32_t value) override { cpuMhz.push_back(value); }
  void setWifiSleep(bool value) override { wifiSleep.push_back(value); }
};

struct ClockMock : hal::IClock {
  uint32_t nowMs = 0;
  int64_t epoch = 0;
  uint32_t millis() const override { return nowMs; }
  int64_t epochSeconds() const override { return epoch; }
  void advance(uint32_t milliseconds) {
    nowMs += milliseconds;
    if (epoch > 0) epoch += milliseconds / 1000;
  }
};

std::string requestJson(const std::string& id = kId1,
                        const std::string& title = "real title",
                        const std::string& agent = "devin",
                        const std::string& expires = "2026-10-14T19:30:00Z") {
  return "[{\"id\":\"" + id + "\",\"agent\":\"" + agent +
         "\",\"title\":\"" + title +
         "\",\"lines\":[\"detail one\",\"detail two\",\"detail three\","
         "\"detail four\",\"detail five\"],\"expires_at\":\"" + expires +
         "\",\"session_id\":\"ignored\"}]";
}

std::string requestId(size_t index) {
  char buffer[37];
  std::snprintf(buffer, sizeof(buffer), "%08zx-1111-4111-8111-111111111111",
                index + 1);
  return buffer;
}

std::string largeRequestListJson(size_t requests) {
  const std::string detail(256, 'd');
  const std::string ignored(2000, 'x');
  std::string response = "[";
  for (size_t request = 0; request < requests; ++request) {
    if (request > 0) response += ",";
    response += "{\"id\":\"";
    response += requestId(request);
    response +=
        "\",\"agent\":\"devin\",\"title\":\"large request\",\"lines\":[";
    for (size_t line = 0; line < 32; ++line) {
      if (line > 0) response += ",";
      response += "\"" + detail + "\"";
    }
    response +=
        "],\"expires_at\":\"2026-10-14T19:30:00Z\",\"ignored\":\"" +
        ignored + "\"}";
  }
  response += "]";
  return response;
}

struct Fixture {
  DisplayMock display;
  ButtonsMock buttons;
  MqttMock mqtt;
  HttpMock http;
  PowerMock power;
  ClockMock clock;
  ApprovalConfig config;
  ApprovalApp app;

  Fixture() : Fixture(ApprovalConfig{"http://bridge", "test-token"}) {}

  explicit Fixture(ApprovalConfig settings)
      : config(std::move(settings)),
        app(display, buttons, mqtt, http, power, clock, config) {}

  void start() {
    http.getBody = requestJson();
    app.begin();
    app.tick();
  }
  void waitInputGuard() { clock.advance(config.inputGuardMs); }
  void syncAfterSignal(const std::string& topic,
                       const std::string& payload = "{}") {
    mqtt.fire(topic, payload);
    clock.advance(config.syncMinIntervalMs);
    app.tick();
  }
};

void test_mqtt_signal_syncs_and_displays_http_data() {
  Fixture fixture;
  fixture.start();
  TEST_ASSERT_EQUAL(1, fixture.http.getCalls);
  TEST_ASSERT_EQUAL_STRING("http://bridge/v1/requests?status=pending",
                           fixture.http.lastGetUrl.c_str());
  TEST_ASSERT_EQUAL_STRING("test-token", fixture.http.lastGetBearer.c_str());
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());
  TEST_ASSERT_TRUE(fixture.display.sawText("real title"));
  TEST_ASSERT_TRUE(fixture.display.sawText("detail one"));
  TEST_ASSERT_FALSE(fixture.display.sawText("detail four"));
  TEST_ASSERT_EQUAL(2, fixture.mqtt.subscriptions.size());
}

void test_button_a_posts_approve_with_device_credentials() {
  Fixture fixture;
  fixture.start();
  fixture.waitInputGuard();
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(1, fixture.http.postCalls);
  TEST_ASSERT_EQUAL_STRING(
      "http://bridge/v1/requests/11111111-1111-4111-8111-111111111111/decision",
      fixture.http.lastPostUrl.c_str());
  TEST_ASSERT_EQUAL_STRING("test-token", fixture.http.lastPostBearer.c_str());
  TEST_ASSERT_EQUAL_STRING(
      "{\"decision\":\"approve\",\"source\":\"m5stickc\"}",
      fixture.http.lastPostBody.c_str());
  TEST_ASSERT_EQUAL(ApprovalApp::State::Done, fixture.app.state());
}

void test_button_b_posts_reject() {
  Fixture fixture;
  fixture.start();
  fixture.waitInputGuard();
  fixture.buttons.pressedB = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(1, fixture.http.postCalls);
  TEST_ASSERT_EQUAL_STRING("{\"decision\":\"reject\",\"source\":\"m5stickc\"}",
                           fixture.http.lastPostBody.c_str());
}

void test_resolved_signal_refreshes_and_clears_gone_request() {
  Fixture fixture;
  fixture.start();
  fixture.http.getResponses.push_back({200, "[]"});
  fixture.syncAfterSignal("roam/approval/resolved", "{\"id\":\"fake\"}");
  TEST_ASSERT_EQUAL(2, fixture.http.getCalls);
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  TEST_ASSERT_TRUE(fixture.app.displayedId().empty());
}

void test_expiry_with_wall_clock_clears_without_decision() {
  Fixture fixture;
  fixture.clock.epoch = 1792006200;
  fixture.http.getBody = requestJson(
      kId1, "expires soon", "devin", "2026-10-14T19:30:01Z");
  fixture.start();
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
}

void test_without_wall_clock_request_stays_until_bridge_drops_it() {
  Fixture fixture;
  fixture.http.getBody = requestJson(
      kId1, "long timeout", "devin", "2026-10-14T19:30:00Z");
  fixture.start();
  for (int i = 0; i < 40; ++i) {
    fixture.clock.advance(30000);
    fixture.app.tick();
  }
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());

  fixture.http.getBody = "[]";
  fixture.clock.advance(30000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
}

void test_power_policy_transitions_only_once() {
  DisplayMock display;
  PowerMock power;
  PowerPolicy policy(display, power, 100, 100, 8);
  policy.begin(0);
  policy.tick(99);
  TEST_ASSERT_EQUAL(0, display.brightness.size());
  policy.tick(100);
  policy.tick(200);
  TEST_ASSERT_TRUE(policy.isDimmed());
  TEST_ASSERT_EQUAL(1, display.brightness.size());
  TEST_ASSERT_EQUAL(8, display.brightness[0]);
  TEST_ASSERT_EQUAL(1, power.cpuMhz.size());
  TEST_ASSERT_EQUAL(80, power.cpuMhz[0]);
  TEST_ASSERT_TRUE(power.wifiSleep[0]);
  policy.activity(201);
  TEST_ASSERT_FALSE(policy.isDimmed());
  TEST_ASSERT_EQUAL(2, display.brightness.size());
  TEST_ASSERT_EQUAL(100, display.brightness[1]);
  TEST_ASSERT_EQUAL(240, power.cpuMhz[1]);
  TEST_ASSERT_FALSE(power.wifiSleep[1]);
  policy.activity(202);
  TEST_ASSERT_EQUAL(2, display.brightness.size());
}

void test_new_request_wakes_and_dimmed_press_only_wakes() {
  ApprovalConfig config{"http://bridge", "test-token"};
  config.idleDimMs = 100;
  Fixture fixture(config);
  fixture.start();
  fixture.clock.advance(100);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(8, fixture.display.brightness.back());
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
  TEST_ASSERT_EQUAL(100, fixture.display.brightness.back());

  fixture.clock.advance(100);
  fixture.app.tick();
  fixture.http.getBody = requestJson(kId2, "new request");
  fixture.http.getResponses.push_back({200, fixture.http.getBody});
  fixture.mqtt.fire("roam/approval/request/" + std::string(kId2), "ignored");
  fixture.clock.advance(900);
  fixture.app.tick();
  TEST_ASSERT_EQUAL_STRING(kId2, fixture.app.displayedId().c_str());
  TEST_ASSERT_EQUAL(100, fixture.display.brightness.back());
  TEST_ASSERT_FALSE(fixture.power.wifiSleep.back());
}

void test_http_post_failure_shows_error_and_repress_retries() {
  Fixture fixture;
  fixture.start();
  fixture.waitInputGuard();
  fixture.http.postStatuses.push_back(-1);
  fixture.http.postStatuses.push_back(200);
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_TRUE(fixture.display.sawText("send failed, retry"));
  TEST_ASSERT_EQUAL(6, fixture.display.draws.back().size());
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(2, fixture.http.postCalls);
  TEST_ASSERT_EQUAL(ApprovalApp::State::Done, fixture.app.state());
}

void test_http_404_and_409_drop_request_and_resync_without_error() {
  for (int status : {404, 409}) {
    Fixture fixture;
    fixture.start();
    fixture.waitInputGuard();
    fixture.http.postStatuses.push_back(status);
    fixture.http.getResponses.push_back({200, "[]"});
    fixture.buttons.pressedB = true;
    fixture.app.tick();
    TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
    TEST_ASSERT_FALSE(fixture.display.sawText("send failed, retry"));
    fixture.clock.advance(1000);
    fixture.app.tick();
    TEST_ASSERT_EQUAL(2, fixture.http.getCalls);
    TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  }
}

void test_fake_mqtt_payload_is_never_shown_or_decided() {
  Fixture fixture;
  fixture.http.getResponses.push_back({200, "[]"});
  fixture.start();
  fixture.http.getBody = "[]";
  fixture.mqtt.fire(
      "roam/approval/request/" + std::string(kFakeId),
      "{\"id\":\"" + std::string(kFakeId) +
          "\",\"title\":\"FAKE MQTT TITLE\",\"agent\":\"attacker\"}");
  fixture.buttons.pressedA = true;
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
  TEST_ASSERT_FALSE(fixture.display.sawText("FAKE MQTT TITLE"));
  TEST_ASSERT_FALSE(fixture.display.sawText(kFakeId));
  TEST_ASSERT_FALSE(fixture.display.sawText("attacker"));
}

void test_request_disappearing_from_http_list_cannot_be_decided() {
  Fixture fixture;
  fixture.start();
  fixture.http.getResponses.push_back({200, "[]"});
  fixture.syncAfterSignal("roam/approval/request/" + std::string(kId1));
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
}

void test_send_failure_does_not_carry_over_to_next_request() {
  Fixture fixture;
  fixture.start();
  fixture.waitInputGuard();
  fixture.http.postStatuses.push_back(-1);
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_TRUE(fixture.display.lastDrawHasText("send failed, retry"));

  fixture.http.getResponses.push_back({200, requestJson(kId2, "request B")});
  fixture.syncAfterSignal("roam/approval/resolved");
  TEST_ASSERT_EQUAL_STRING(kId2, fixture.app.displayedId().c_str());
  TEST_ASSERT_FALSE(fixture.display.lastDrawHasText("send failed, retry"));
}

void test_simultaneous_button_presses_only_count_as_activity() {
  ApprovalConfig config{"http://bridge", "test-token"};
  config.idleDimMs = 100;
  Fixture fixture(config);
  fixture.start();

  fixture.buttons.pressedA = true;
  fixture.buttons.pressedB = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);

  fixture.clock.advance(100);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(8, fixture.display.brightness.back());

  fixture.buttons.pressedA = true;
  fixture.buttons.pressedB = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
  TEST_ASSERT_EQUAL(100, fixture.display.brightness.back());
  fixture.clock.advance(99);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(100, fixture.display.brightness.back());
  fixture.clock.advance(1);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(8, fixture.display.brightness.back());
}

void test_large_pending_response_is_streamed() {
  Fixture fixture;
  fixture.http.getBody = largeRequestListJson(20);
  TEST_ASSERT_TRUE(fixture.http.getBody.size() > 200000);
  fixture.app.begin();
  fixture.app.tick();

  TEST_ASSERT_FALSE(fixture.app.lastSyncFailed());
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(requestId(0).c_str(),
                           fixture.app.displayedId().c_str());
  TEST_ASSERT_EQUAL_STRING("devin 1/8",
                           fixture.display.draws.back()[0].c_str());
}

void test_fake_resolved_or_empty_retained_does_not_hide_http_pending() {
  Fixture fixture;
  fixture.start();
  fixture.syncAfterSignal("roam/approval/resolved", "{}");
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());

  fixture.mqtt.fire("roam/approval/request/" + std::string(kId1), "");
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());
}

void test_mqtt_burst_is_debounced_to_one_trailing_sync() {
  Fixture fixture;
  fixture.start();
  for (int i = 0; i < 100; ++i) {
    fixture.mqtt.fire("roam/approval/request/" + std::to_string(i), "ignored");
  }
  fixture.app.tick();
  TEST_ASSERT_EQUAL(1, fixture.http.getCalls);
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(2, fixture.http.getCalls);
}

void test_mqtt_reconnect_subscribes_and_syncs() {
  Fixture fixture;
  fixture.start();
  fixture.mqtt.isConnected = false;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(2, fixture.mqtt.connectCalls);
  TEST_ASSERT_EQUAL(4, fixture.mqtt.subscriptions.size());
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(2, fixture.http.getCalls);
}

void test_sync_failure_shows_error_and_retries() {
  Fixture fixture;
  fixture.http.getStatus = -1;
  fixture.http.getBody = "[]";
  fixture.start();
  TEST_ASSERT_TRUE(fixture.app.lastSyncFailed());
  TEST_ASSERT_TRUE(fixture.display.sawText("bridge err"));
  fixture.http.getResponses.push_back({200, "[]"});
  fixture.clock.advance(1000);
  fixture.app.tick();
  TEST_ASSERT_FALSE(fixture.app.lastSyncFailed());
  TEST_ASSERT_EQUAL(2, fixture.http.getCalls);
}


void test_bridge_shaped_pending_list_is_shown() {
  Fixture fixture;
  fixture.clock.epoch = 0;  // no wall clock
  fixture.http.getBody =
      "[{\"id\":\"3c351d3c-ee01-43c0-9eca-86321308bc63\",\"agent\":\"devin-cli\","
      "\"session_id\":\"step6-2\",\"title\":\"SHOW THIS\",\"lines\":[\"line-one\","
      "\"line-two\"],\"timeout_s\":300,\"created_at\":\"2026-10-18T11:49:16.015828Z\","
      "\"status\":\"pending\",\"decided_by\":null,"
      "\"expires_at\":\"2026-10-18T11:54:16.015828Z\"}]";
  fixture.app.begin();
  fixture.app.tick();
  TEST_ASSERT_FALSE(fixture.app.lastSyncFailed());
  TEST_ASSERT_EQUAL_STRING("3c351d3c-ee01-43c0-9eca-86321308bc63",
                           fixture.app.displayedId().c_str());
  TEST_ASSERT_TRUE(fixture.display.sawText("SHOW THIS"));
  TEST_ASSERT_TRUE(fixture.display.sawText("line-one"));
}

void test_false_local_expiry_does_not_stick_across_syncs() {
  Fixture fixture;
  // Far-future wall clock incorrectly treats the request as expired.
  fixture.clock.epoch = 2000000000;
  fixture.http.getBody = requestJson();
  fixture.start();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  TEST_ASSERT_TRUE(fixture.app.displayedId().empty());

  // Once the clock is trusted again (or unset), Bridge pending must reappear.
  fixture.clock.epoch = 0;
  fixture.syncAfterSignal("roam/approval/request/" + std::string(kId1), "{}");
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());
}

void test_iso8601_parser() {
  int64_t epoch = 0;
  TEST_ASSERT_TRUE(
      ApprovalApp::parseIso8601("1970-01-01T00:00:00Z", epoch));
  TEST_ASSERT_EQUAL_INT64(0, epoch);
  TEST_ASSERT_TRUE(ApprovalApp::parseIso8601(
      "2026-10-14T19:30:00.123456Z", epoch));
  TEST_ASSERT_EQUAL_INT64(1792006200, epoch);
  int64_t offsetEpoch = 0;
  TEST_ASSERT_TRUE(ApprovalApp::parseIso8601(
      "2026-10-14T21:30:00+02:00", offsetEpoch));
  TEST_ASSERT_EQUAL_INT64(epoch, offsetEpoch);
  TEST_ASSERT_TRUE(ApprovalApp::parseIso8601(
      "2026-10-14T19:30:00+00:00", offsetEpoch));
  TEST_ASSERT_EQUAL_INT64(epoch, offsetEpoch);
  TEST_ASSERT_FALSE(
      ApprovalApp::parseIso8601("2026-02-30T19:30:00Z", epoch));
  TEST_ASSERT_FALSE(
      ApprovalApp::parseIso8601("2026-10-14T19:30:00", epoch));
}

void test_display_text_counts_code_points_and_masks_non_ascii() {
  TEST_ASSERT_EQUAL_STRING(
      "abc??d", ApprovalApp::toDisplayText("abc日本d", 20).c_str());
  TEST_ASSERT_EQUAL_STRING(
      "abcdefghijklmnopq???",
      ApprovalApp::toDisplayText("abcdefghijklmnopq日本語テキスト", 20).c_str());
  TEST_ASSERT_EQUAL_STRING(
      "12?4", ApprovalApp::toDisplayText("12\xf0\x9f\x8c\x8b" "4", 20).c_str());
  TEST_ASSERT_EQUAL_STRING("a b",
                           ApprovalApp::toDisplayText("a\tb", 20).c_str());
  TEST_ASSERT_EQUAL_STRING("abc", ApprovalApp::toDisplayText("abcdef", 3).c_str());
}

std::string twoRequestsJson() {
  const std::string first = requestJson(kId1, "seen title");
  const std::string second = requestJson(kId2, "unseen title");
  return first.substr(0, first.size() - 1) + "," + second.substr(1);
}

void test_press_is_applied_to_request_seen_before_sync() {
  Fixture fixture;
  fixture.http.getBody = twoRequestsJson();
  fixture.app.begin();
  fixture.app.tick();
  fixture.waitInputGuard();
  TEST_ASSERT_EQUAL_STRING(kId1, fixture.app.displayedId().c_str());

  fixture.http.getResponses.push_back({200, requestJson(kId2, "unseen title")});
  fixture.mqtt.fire("roam/approval/resolved", "{}");
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(1, fixture.http.postCalls);
  TEST_ASSERT_TRUE(fixture.http.lastPostUrl.find(kId1) != std::string::npos);
  TEST_ASSERT_TRUE(fixture.http.lastPostUrl.find(kId2) == std::string::npos);
}

void test_press_right_after_display_switch_is_ignored() {
  Fixture fixture;
  fixture.http.getBody = twoRequestsJson();
  fixture.app.begin();
  fixture.app.tick();
  fixture.waitInputGuard();

  fixture.http.getBody = requestJson(kId2, "unseen title");
  fixture.mqtt.fire("roam/approval/resolved", "{}");
  fixture.app.tick();
  TEST_ASSERT_EQUAL_STRING(kId2, fixture.app.displayedId().c_str());

  fixture.clock.advance(fixture.config.inputGuardMs - 1);
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());

  fixture.clock.advance(1);
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(1, fixture.http.postCalls);
  TEST_ASSERT_TRUE(fixture.http.lastPostUrl.find(kId2) != std::string::npos);
}

void test_new_request_appearing_ignores_immediate_press() {
  Fixture fixture;
  fixture.http.getResponses.push_back({200, "[]"});
  fixture.start();
  fixture.waitInputGuard();
  fixture.http.getBody = requestJson();
  fixture.mqtt.fire("roam/approval/request/" + std::string(kId1), "");
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Showing, fixture.app.state());
  fixture.buttons.pressedA = true;
  fixture.app.tick();
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
}

void test_unchanged_screen_is_not_redrawn() {
  Fixture fixture;
  fixture.start();
  const size_t draws = fixture.display.draws.size();
  const int clears = fixture.display.clears;
  for (int i = 0; i < 5; ++i) {
    fixture.syncAfterSignal("roam/approval/resolved");
  }
  fixture.clock.advance(30000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(7, fixture.http.getCalls);
  TEST_ASSERT_EQUAL(draws, fixture.display.draws.size());
  TEST_ASSERT_EQUAL(clears, fixture.display.clears);
}

void test_malformed_or_truncated_list_fails_sync() {
  const std::string full = requestJson();
  for (const std::string& body :
       {std::string("{}"), std::string("[1 2]"), full.substr(0, full.size() / 2),
        full.substr(0, full.size() - 1), std::string("")}) {
    Fixture fixture;
    fixture.http.getBody = body;
    fixture.app.begin();
    fixture.app.tick();
    TEST_ASSERT_TRUE(fixture.app.lastSyncFailed());
    TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  }
}

void test_whitespace_around_list_is_accepted() {
  Fixture fixture;
  fixture.http.getBody = " \n[ ]\n";
  fixture.app.begin();
  fixture.app.tick();
  TEST_ASSERT_FALSE(fixture.app.lastSyncFailed());

  const std::string pretty = "[\n  " + requestJson().substr(1, requestJson().size() - 2) + " ,\n " +
                             requestJson(kId2).substr(1, requestJson(kId2).size() - 2) + "\n]";
  fixture.http.getBody = pretty;
  fixture.syncAfterSignal("roam/approval/resolved");
  TEST_ASSERT_FALSE(fixture.app.lastSyncFailed());
  TEST_ASSERT_EQUAL_STRING("devin 1/2", fixture.display.draws.back()[0].c_str());
}

void test_backoff_exponential_cap_and_reset() {
  Backoff backoff(1000, 3000);
  TEST_ASSERT_EQUAL(1000, backoff.nextDelayMs());
  TEST_ASSERT_EQUAL(2000, backoff.nextDelayMs());
  TEST_ASSERT_EQUAL(3000, backoff.nextDelayMs());
  TEST_ASSERT_EQUAL(3000, backoff.nextDelayMs());
  backoff.reset();
  TEST_ASSERT_EQUAL(1000, backoff.nextDelayMs());
}

}  // namespace

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_mqtt_signal_syncs_and_displays_http_data);
  RUN_TEST(test_button_a_posts_approve_with_device_credentials);
  RUN_TEST(test_button_b_posts_reject);
  RUN_TEST(test_resolved_signal_refreshes_and_clears_gone_request);
  RUN_TEST(test_expiry_with_wall_clock_clears_without_decision);
  RUN_TEST(test_without_wall_clock_request_stays_until_bridge_drops_it);
  RUN_TEST(test_power_policy_transitions_only_once);
  RUN_TEST(test_new_request_wakes_and_dimmed_press_only_wakes);
  RUN_TEST(test_http_post_failure_shows_error_and_repress_retries);
  RUN_TEST(test_http_404_and_409_drop_request_and_resync_without_error);
  RUN_TEST(test_fake_mqtt_payload_is_never_shown_or_decided);
  RUN_TEST(test_request_disappearing_from_http_list_cannot_be_decided);
  RUN_TEST(test_send_failure_does_not_carry_over_to_next_request);
  RUN_TEST(test_simultaneous_button_presses_only_count_as_activity);
  RUN_TEST(test_large_pending_response_is_streamed);
  RUN_TEST(test_fake_resolved_or_empty_retained_does_not_hide_http_pending);
  RUN_TEST(test_mqtt_burst_is_debounced_to_one_trailing_sync);
  RUN_TEST(test_mqtt_reconnect_subscribes_and_syncs);
  RUN_TEST(test_sync_failure_shows_error_and_retries);
  RUN_TEST(test_bridge_shaped_pending_list_is_shown);
  RUN_TEST(test_false_local_expiry_does_not_stick_across_syncs);
  RUN_TEST(test_iso8601_parser);
  RUN_TEST(test_display_text_counts_code_points_and_masks_non_ascii);
  RUN_TEST(test_press_is_applied_to_request_seen_before_sync);
  RUN_TEST(test_press_right_after_display_switch_is_ignored);
  RUN_TEST(test_new_request_appearing_ignores_immediate_press);
  RUN_TEST(test_unchanged_screen_is_not_redrawn);
  RUN_TEST(test_malformed_or_truncated_list_fails_sync);
  RUN_TEST(test_whitespace_around_list_is_accepted);
  RUN_TEST(test_backoff_exponential_cap_and_reset);
  return UNITY_END();
}
