#include <unity.h>

#include <cstring>
#include <string>

#include "command.hpp"

namespace {

CommandList list;

void expect_ok(const char* json, size_t expected_count) {
  ParseResult r = parse_commands(json, strlen(json), &list);
  TEST_ASSERT_TRUE(r.ok);
  TEST_ASSERT_EQUAL(expected_count, list.count);
}

void expect_reject(const char* json, int expected_index,
                   const char* expected_field) {
  ParseResult r = parse_commands(json, strlen(json), &list);
  TEST_ASSERT_FALSE(r.ok);
  TEST_ASSERT_EQUAL(expected_index, r.index);
  TEST_ASSERT_EQUAL_STRING(expected_field ? expected_field : "", r.field);
}

}  // namespace

void test_valid_multi_command_list() {
  expect_ok(R"({"commands":[{"buttons":["A","B"],"hold_ms":100,"wait_ms":50},)"
            R"({"hat":"UP","hold_ms":200}]})",
            2);
  TEST_ASSERT_EQUAL_UINT16(BTN_A | BTN_B, list.items[0].buttons);
  TEST_ASSERT_EQUAL_UINT16(100, list.items[0].hold_ms);
  TEST_ASSERT_EQUAL_UINT16(50, list.items[0].wait_ms);
  TEST_ASSERT_EQUAL_UINT8(HAT_UP, list.items[1].hat);
}

void test_combo_buttons() {
  expect_ok(R"({"commands":[{"buttons":["A","B","X"],"hold_ms":10}]})", 1);
  TEST_ASSERT_EQUAL_UINT16(BTN_A | BTN_B | BTN_X, list.items[0].buttons);
}

void test_hat_only() {
  expect_ok(R"({"commands":[{"hat":"LEFT","hold_ms":10}]})", 1);
  TEST_ASSERT_EQUAL_UINT8(HAT_LEFT, list.items[0].hat);
  TEST_ASSERT_EQUAL_UINT16(0, list.items[0].buttons);
}

void test_stick_only() {
  expect_ok(
      R"({"commands":[{"lx":-100,"ly":0,"rx":50,"ry":100,"hold_ms":10}]})", 1);
  TEST_ASSERT_EQUAL_INT8(-100, list.items[0].lx);
  TEST_ASSERT_EQUAL_INT8(0, list.items[0].ly);
  TEST_ASSERT_EQUAL_INT8(50, list.items[0].rx);
  TEST_ASSERT_EQUAL_INT8(100, list.items[0].ry);
}

void test_hold_ms_only_is_pure_wait() {
  expect_ok(R"({"commands":[{"hold_ms":300}]})", 1);
  TEST_ASSERT_EQUAL_UINT16(0, list.items[0].buttons);
  TEST_ASSERT_EQUAL_UINT8(HAT_CENTER, list.items[0].hat);
  TEST_ASSERT_EQUAL_UINT16(300, list.items[0].hold_ms);
}

void test_unknown_button_rejected() {
  expect_reject(R"({"commands":[{"buttons":["Z"],"hold_ms":10}]})", 0,
                "buttons");
}

void test_unknown_hat_rejected() {
  expect_reject(R"({"commands":[{"hat":"DIAGONAL","hold_ms":10}]})", 0, "hat");
}

void test_hold_ms_over_limit_rejected() {
  expect_reject(R"({"commands":[{"hold_ms":10001}]})", 0, "hold_ms");
}

void test_stick_out_of_range_rejected() {
  expect_reject(R"({"commands":[{"lx":101,"hold_ms":10}]})", 0, "lx");
  expect_reject(R"({"commands":[{"lx":-101,"hold_ms":10}]})", 0, "lx");
}

void test_empty_array_rejected() {
  expect_reject(R"({"commands":[]})", -1, "commands");
}

void test_too_many_commands_rejected() {
  std::string json = R"({"commands":[)";
  for (int i = 0; i < 65; ++i) {
    if (i > 0) json += ",";
    json += R"({"hold_ms":1})";
  }
  json += "]}";
  expect_reject(json.c_str(), -1, "commands");
}

void test_malformed_json_rejected() {
  expect_reject(R"({"commands":)", -1, nullptr);
}

void test_missing_commands_key_rejected() {
  expect_reject(R"({})", -1, "commands");
}

void test_commands_not_an_array_rejected() {
  expect_reject(R"({"commands":"nope"})", -1, "commands");
}

void test_unknown_key_in_command_rejected() {
  expect_reject(R"({"commands":[{"buttton":"A","hold_ms":10}]})", 0, "buttton");
}

void test_payload_too_large_rejected() {
  std::string json = R"({"commands":[{"hold_ms":1,"note":")";
  json.append(4096, 'x');
  json += "\"}]}";
  expect_reject(json.c_str(), -1, nullptr);
}

void test_missing_hold_ms_rejected() {
  expect_reject(R"({"commands":[{"buttons":["A"]}]})", 0, "hold_ms");
}

void test_rejected_request_does_not_clobber_prior_accepted_list() {
  expect_ok(R"({"commands":[{"buttons":["A"],"hold_ms":10},)"
            R"({"buttons":["B"],"hold_ms":20},)"
            R"({"buttons":["X"],"hold_ms":30}]})",
            3);
  Command accepted[3];
  std::memcpy(accepted, list.items, sizeof(accepted));

  expect_reject(R"({"commands":[{"buttons":["A"],"hold_ms":10},)"
                R"({"buttons":["Z"],"hold_ms":10}]})",
                1, "buttons");
  TEST_ASSERT_EQUAL(3, list.count);
  TEST_ASSERT_EQUAL_MEMORY(accepted, list.items, sizeof(accepted));
}

void test_state_parses_buttons_hat_and_sticks() {
  Command state;
  const char* json = R"({"buttons":["B","A"],"hat":"RIGHT","lx":-50})";
  ParseResult r = parse_state(json, strlen(json), &state);
  TEST_ASSERT_TRUE(r.ok);
  TEST_ASSERT_EQUAL_UINT16(BTN_B | BTN_A, state.buttons);
  TEST_ASSERT_EQUAL_UINT8(HAT_RIGHT, state.hat);
  TEST_ASSERT_EQUAL_INT8(-50, state.lx);
  TEST_ASSERT_EQUAL_UINT16(0, state.hold_ms);
}

void test_state_empty_object_is_neutral() {
  Command state;
  state.buttons = BTN_A;
  ParseResult r = parse_state("{}", 2, &state);
  TEST_ASSERT_TRUE(r.ok);
  TEST_ASSERT_EQUAL_UINT16(0, state.buttons);
  TEST_ASSERT_EQUAL_UINT8(HAT_CENTER, state.hat);
}

void test_state_rejects_timing_fields() {
  Command state;
  const char* json = R"({"buttons":["A"],"hold_ms":100})";
  ParseResult r = parse_state(json, strlen(json), &state);
  TEST_ASSERT_FALSE(r.ok);
  TEST_ASSERT_EQUAL_STRING("hold_ms", r.field);
}

void test_state_rejects_unknown_button_and_non_object() {
  Command state;
  const char* bad_button = R"({"buttons":["TURBO"]})";
  TEST_ASSERT_FALSE(parse_state(bad_button, strlen(bad_button), &state).ok);
  TEST_ASSERT_FALSE(parse_state("[1]", 3, &state).ok);
  TEST_ASSERT_FALSE(parse_state("nope", 4, &state).ok);
}

void test_rejected_state_does_not_clobber_prior_state() {
  Command state;
  const char* ok_json = R"({"buttons":["A"]})";
  TEST_ASSERT_TRUE(parse_state(ok_json, strlen(ok_json), &state).ok);
  const char* bad = R"({"buttons":["A"],"lx":999})";
  TEST_ASSERT_FALSE(parse_state(bad, strlen(bad), &state).ok);
  TEST_ASSERT_EQUAL_UINT16(BTN_A, state.buttons);
  TEST_ASSERT_EQUAL_INT8(0, state.lx);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_valid_multi_command_list);
  RUN_TEST(test_combo_buttons);
  RUN_TEST(test_hat_only);
  RUN_TEST(test_stick_only);
  RUN_TEST(test_hold_ms_only_is_pure_wait);
  RUN_TEST(test_unknown_button_rejected);
  RUN_TEST(test_unknown_hat_rejected);
  RUN_TEST(test_hold_ms_over_limit_rejected);
  RUN_TEST(test_stick_out_of_range_rejected);
  RUN_TEST(test_empty_array_rejected);
  RUN_TEST(test_too_many_commands_rejected);
  RUN_TEST(test_malformed_json_rejected);
  RUN_TEST(test_missing_commands_key_rejected);
  RUN_TEST(test_commands_not_an_array_rejected);
  RUN_TEST(test_unknown_key_in_command_rejected);
  RUN_TEST(test_payload_too_large_rejected);
  RUN_TEST(test_missing_hold_ms_rejected);
  RUN_TEST(test_rejected_request_does_not_clobber_prior_accepted_list);
  RUN_TEST(test_state_parses_buttons_hat_and_sticks);
  RUN_TEST(test_state_empty_object_is_neutral);
  RUN_TEST(test_state_rejects_timing_fields);
  RUN_TEST(test_state_rejects_unknown_button_and_non_object);
  RUN_TEST(test_rejected_state_does_not_clobber_prior_state);
  return UNITY_END();
}
