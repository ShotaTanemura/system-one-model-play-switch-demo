#pragma once

#include <cstdint>

// How long a held state survives without a refresh from the host.
constexpr uint32_t STATE_TIMEOUT_MS = 1000;

// Tracks a held controller state and releases it when the host goes quiet,
// so a crashed or stalled host cannot leave buttons pressed.
class StateHold {
 public:
  void set(uint32_t now_ms);
  void clear();
  // Returns true exactly once per hold, when it has gone STATE_TIMEOUT_MS
  // without a set(). The caller must then send a neutral frame.
  bool expired(uint32_t now_ms);

 private:
  bool active_ = false;
  uint32_t last_set_ms_ = 0;
};
