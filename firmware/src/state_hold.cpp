#include "state_hold.hpp"

void StateHold::set(uint32_t now_ms) {
  active_ = true;
  last_set_ms_ = now_ms;
}

void StateHold::clear() { active_ = false; }

bool StateHold::expired(uint32_t now_ms) {
  // Unsigned subtraction stays correct across the millis() wraparound.
  if (active_ && now_ms - last_set_ms_ >= STATE_TIMEOUT_MS) {
    active_ = false;
    return true;
  }
  return false;
}
