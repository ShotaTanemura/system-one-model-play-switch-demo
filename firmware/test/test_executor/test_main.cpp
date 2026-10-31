#include <unity.h>

#include <vector>

#include "executor.hpp"

namespace {

struct Event {
  bool is_sleep;
  Frame frame;
  uint32_t ms;
};

std::vector<Event> trace;
int fail_at_call = -1;
int call_count = 0;

bool fake_send(const Frame& frame) {
  bool ok = call_count != fail_at_call;
  trace.push_back(Event{false, frame, 0});
  call_count++;
  return ok;
}

void fake_sleep(uint32_t ms) { trace.push_back(Event{true, Frame{}, ms}); }

void reset() {
  trace.clear();
  fail_at_call = -1;
  call_count = 0;
}

CommandList one_command(Command command) {
  CommandList list;
  list.count = 1;
  list.items[0] = command;
  return list;
}

void expect_send(size_t at, const Frame& frame) {
  TEST_ASSERT_FALSE(trace[at].is_sleep);
  TEST_ASSERT_EQUAL_MEMORY(&frame, &trace[at].frame, sizeof(Frame));
}

void expect_sleep(size_t at, uint32_t ms) {
  TEST_ASSERT_TRUE(trace[at].is_sleep);
  TEST_ASSERT_EQUAL_UINT32(ms, trace[at].ms);
}

}  // namespace

void test_stick_to_axis_endpoints_and_midpoint() {
  Command command;
  command.lx = -100;
  command.ly = 0;
  command.rx = 100;
  command.ry = 50;
  Frame frame = frame_from_command(command);
  TEST_ASSERT_EQUAL_UINT8(1, frame.lx);
  TEST_ASSERT_EQUAL_UINT8(0x80, frame.ly);
  TEST_ASSERT_EQUAL_UINT8(255, frame.rx);
  TEST_ASSERT_EQUAL_UINT8(191, frame.ry);
}

void test_buttons_and_hat_passthrough() {
  Command command;
  command.buttons = BTN_A | BTN_B;
  command.hat = HAT_UP;
  Frame frame = frame_from_command(command);
  TEST_ASSERT_EQUAL_UINT16(BTN_A | BTN_B, frame.buttons);
  TEST_ASSERT_EQUAL_UINT8(HAT_UP, frame.hat);
  TEST_ASSERT_EQUAL_UINT8(0x80, frame.lx);
}

void test_single_command_emits_frame_hold_neutral_wait() {
  reset();
  Command command;
  command.buttons = BTN_A;
  command.hold_ms = 100;
  command.wait_ms = 50;
  CommandList list = one_command(command);

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_TRUE(result.ok);
  TEST_ASSERT_EQUAL(1, result.index);
  TEST_ASSERT_EQUAL(4, trace.size());
  expect_send(0, frame_from_command(command));
  expect_sleep(1, 100);
  expect_send(2, frame_from_command(Command{}));
  expect_sleep(3, 50);
}

void test_multi_command_ordering() {
  reset();
  CommandList list;
  list.count = 2;
  list.items[0] = Command{};
  list.items[0].buttons = BTN_A;
  list.items[0].hold_ms = 10;
  list.items[0].wait_ms = 20;
  list.items[1] = Command{};
  list.items[1].buttons = BTN_B;
  list.items[1].hold_ms = 30;
  list.items[1].wait_ms = 40;

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_TRUE(result.ok);
  TEST_ASSERT_EQUAL(2, result.index);
  TEST_ASSERT_EQUAL(8, trace.size());
  expect_send(0, frame_from_command(list.items[0]));
  expect_sleep(1, 10);
  expect_send(2, frame_from_command(Command{}));
  expect_sleep(3, 20);
  expect_send(4, frame_from_command(list.items[1]));
  expect_sleep(5, 30);
  expect_send(6, frame_from_command(Command{}));
  expect_sleep(7, 40);
}

void test_hold_ms_only_command_emits_two_neutral_frames() {
  reset();
  Command command;
  command.hold_ms = 300;
  CommandList list = one_command(command);

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_TRUE(result.ok);
  Frame neutral = frame_from_command(Command{});
  expect_send(0, neutral);
  expect_sleep(1, 300);
  expect_send(2, neutral);
  expect_sleep(3, 0);
}

void test_zero_hold_and_wait_still_emit_sends() {
  reset();
  Command command;
  command.buttons = BTN_A;
  CommandList list = one_command(command);

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_TRUE(result.ok);
  TEST_ASSERT_EQUAL(4, trace.size());
  expect_sleep(1, 0);
  expect_sleep(3, 0);
}

void test_abort_on_failed_press_frame() {
  reset();
  Command command;
  command.buttons = BTN_A;
  command.hold_ms = 10;
  CommandList list = one_command(command);
  fail_at_call = 0;

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_FALSE(result.ok);
  TEST_ASSERT_EQUAL(0, result.index);
  TEST_ASSERT_EQUAL(2, trace.size());
  expect_send(0, frame_from_command(command));
  expect_send(1, frame_from_command(Command{}));
}

void test_abort_on_failed_neutral_frame() {
  reset();
  Command command;
  command.buttons = BTN_A;
  command.hold_ms = 10;
  CommandList list = one_command(command);
  fail_at_call = 1;

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_FALSE(result.ok);
  TEST_ASSERT_EQUAL(0, result.index);
  TEST_ASSERT_EQUAL(3, trace.size());
  expect_send(0, frame_from_command(command));
  expect_sleep(1, 10);
  expect_send(2, frame_from_command(Command{}));
}

void test_abort_skips_remaining_commands() {
  reset();
  CommandList list;
  list.count = 3;
  list.items[0] = Command{};
  list.items[0].buttons = BTN_A;
  list.items[1] = Command{};
  list.items[1].buttons = BTN_B;
  list.items[2] = Command{};
  list.items[2].buttons = BTN_X;
  fail_at_call = 2;

  ExecResult result = run_commands(list, fake_send, fake_sleep);

  TEST_ASSERT_FALSE(result.ok);
  TEST_ASSERT_EQUAL(1, result.index);
  TEST_ASSERT_EQUAL(6, trace.size());
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_stick_to_axis_endpoints_and_midpoint);
  RUN_TEST(test_buttons_and_hat_passthrough);
  RUN_TEST(test_single_command_emits_frame_hold_neutral_wait);
  RUN_TEST(test_multi_command_ordering);
  RUN_TEST(test_hold_ms_only_command_emits_two_neutral_frames);
  RUN_TEST(test_zero_hold_and_wait_still_emit_sends);
  RUN_TEST(test_abort_on_failed_press_frame);
  RUN_TEST(test_abort_on_failed_neutral_frame);
  RUN_TEST(test_abort_skips_remaining_commands);
  return UNITY_END();
}
