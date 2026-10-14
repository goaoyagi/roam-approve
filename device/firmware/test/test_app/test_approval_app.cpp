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
              std::string& outBody) override {
    ++getCalls;
    lastGetUrl = url;
    lastGetBearer = bearer;
    if (!getResponses.empty()) {
      const Response response = getResponses.front();
      getResponses.pop_front();
      outBody = response.body;
      return response.status;
    }
    outBody = getBody;
    return getStatus;
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

void test_fallback_expiry_without_wall_clock() {
  ApprovalConfig config{"http://bridge", "test-token"};
  config.fallbackTimeoutMs = 2000;
  Fixture fixture(config);
  fixture.http.getBody = requestJson(
      kId1, "fallback", "devin", "2026-10-14T19:30:00Z");
  fixture.start();
  fixture.clock.advance(2000);
  fixture.app.tick();
  TEST_ASSERT_EQUAL(ApprovalApp::State::Idle, fixture.app.state());
  TEST_ASSERT_EQUAL(0, fixture.http.postCalls);
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

void test_utf8_truncation_preserves_codepoint_boundaries() {
  const std::string japanese = "abcdefghijklmnopq日本";
  const std::string truncated = ApprovalApp::truncateUtf8(japanese, 19);
  TEST_ASSERT_EQUAL(17, truncated.size());
  TEST_ASSERT_EQUAL_STRING("abcdefghijklmnopq", truncated.c_str());
  const std::string fourByte = "1234567890123456\xf0\x9f\x8c\x8b";
  TEST_ASSERT_EQUAL_STRING("1234567890123456",
                           ApprovalApp::truncateUtf8(fourByte, 18).c_str());
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

void runTest(void (*test)()) {
  RUN_TEST(test);
}
}  // namespace

int main() {
  UNITY_BEGIN();
  runTest(test_mqtt_signal_syncs_and_displays_http_data);
  runTest(test_button_a_posts_approve_with_device_credentials);
  runTest(test_button_b_posts_reject);
  runTest(test_resolved_signal_refreshes_and_clears_gone_request);
  runTest(test_expiry_with_wall_clock_clears_without_decision);
  runTest(test_fallback_expiry_without_wall_clock);
  runTest(test_power_policy_transitions_only_once);
  runTest(test_new_request_wakes_and_dimmed_press_only_wakes);
  runTest(test_http_post_failure_shows_error_and_repress_retries);
  runTest(test_http_404_and_409_drop_request_and_resync_without_error);
  runTest(test_fake_mqtt_payload_is_never_shown_or_decided);
  runTest(test_request_disappearing_from_http_list_cannot_be_decided);
  runTest(test_fake_resolved_or_empty_retained_does_not_hide_http_pending);
  runTest(test_mqtt_burst_is_debounced_to_one_trailing_sync);
  runTest(test_mqtt_reconnect_subscribes_and_syncs);
  runTest(test_sync_failure_shows_error_and_retries);
  runTest(test_iso8601_parser);
  runTest(test_utf8_truncation_preserves_codepoint_boundaries);
  runTest(test_backoff_exponential_cap_and_reset);
  return UNITY_END();
}
