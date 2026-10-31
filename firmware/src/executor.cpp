#include "executor.hpp"

static uint8_t stick_to_axis(int8_t pct) {
  return static_cast<uint8_t>(pct * 0xFF / 200 + 0x80);
}

Frame frame_from_command(const Command& command) {
  return Frame{
      command.buttons,           command.hat,
      stick_to_axis(command.lx), stick_to_axis(command.ly),
      stick_to_axis(command.rx), stick_to_axis(command.ry),
  };
}

ExecResult run_commands(const CommandList& list, FrameSink send,
                        SleepFn sleep_ms) {
  const Frame neutral = frame_from_command(Command{});
  for (size_t i = 0; i < list.count; i++) {
    const Command& command = list.items[i];
    if (!send(frame_from_command(command))) {
      send(neutral);
      return ExecResult{false, i};
    }
    sleep_ms(command.hold_ms);
    if (!send(neutral)) {
      return ExecResult{false, i};
    }
    sleep_ms(command.wait_ms);
  }
  return ExecResult{true, list.count};
}
