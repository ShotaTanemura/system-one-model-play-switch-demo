#pragma once

#include "command.hpp"

struct Frame {
  uint16_t buttons;
  uint8_t hat, lx, ly, rx, ry;
};

struct ExecResult {
  bool ok;
  size_t index;
};

using FrameSink = bool (*)(const Frame&);
using SleepFn = void (*)(uint32_t);

Frame frame_from_command(const Command& command);
ExecResult run_commands(const CommandList& list, FrameSink send,
                        SleepFn sleep_ms);
