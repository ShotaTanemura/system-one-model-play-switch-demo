#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

constexpr size_t MAX_PAYLOAD_BYTES = 4096;
constexpr size_t MAX_COMMANDS = 64;
constexpr uint16_t MAX_HOLD_MS = 10000;
constexpr uint16_t MAX_WAIT_MS = 10000;
constexpr int8_t MIN_STICK = -100;
constexpr int8_t MAX_STICK = 100;

enum : uint16_t {
  BTN_Y = 0x0001,
  BTN_B = 0x0002,
  BTN_A = 0x0004,
  BTN_X = 0x0008,
  BTN_L = 0x0010,
  BTN_R = 0x0020,
  BTN_ZL = 0x0040,
  BTN_ZR = 0x0080,
  BTN_MINUS = 0x0100,
  BTN_PLUS = 0x0200,
  BTN_LCLICK = 0x0400,
  BTN_RCLICK = 0x0800,
  BTN_HOME = 0x1000,
  BTN_CAPTURE = 0x2000,
};

enum : uint8_t {
  HAT_UP = 0x00,
  HAT_UP_RIGHT = 0x01,
  HAT_RIGHT = 0x02,
  HAT_RIGHT_DOWN = 0x03,
  HAT_DOWN = 0x04,
  HAT_DOWN_LEFT = 0x05,
  HAT_LEFT = 0x06,
  HAT_LEFT_UP = 0x07,
  HAT_CENTER = 0x08,
};

struct ButtonName {
  const char* name;
  uint16_t value;
};

inline constexpr ButtonName kButtonNames[] = {
    {"Y", BTN_Y},           {"B", BTN_B},
    {"A", BTN_A},           {"X", BTN_X},
    {"L", BTN_L},           {"R", BTN_R},
    {"ZL", BTN_ZL},         {"ZR", BTN_ZR},
    {"MINUS", BTN_MINUS},   {"PLUS", BTN_PLUS},
    {"LCLICK", BTN_LCLICK}, {"RCLICK", BTN_RCLICK},
    {"HOME", BTN_HOME},     {"CAPTURE", BTN_CAPTURE},
};
inline constexpr size_t kButtonNameCount =
    sizeof(kButtonNames) / sizeof(kButtonNames[0]);

struct HatName {
  const char* name;
  uint8_t value;
};

inline constexpr HatName kHatNames[] = {
    {"UP", HAT_UP},         {"UP_RIGHT", HAT_UP_RIGHT},
    {"RIGHT", HAT_RIGHT},   {"RIGHT_DOWN", HAT_RIGHT_DOWN},
    {"DOWN", HAT_DOWN},     {"DOWN_LEFT", HAT_DOWN_LEFT},
    {"LEFT", HAT_LEFT},     {"LEFT_UP", HAT_LEFT_UP},
    {"CENTER", HAT_CENTER},
};
inline constexpr size_t kHatNameCount =
    sizeof(kHatNames) / sizeof(kHatNames[0]);

struct Command {
  uint16_t buttons = 0;
  uint8_t hat = HAT_CENTER;
  int8_t lx = 0;
  int8_t ly = 0;
  int8_t rx = 0;
  int8_t ry = 0;
  uint16_t hold_ms = 0;
  uint16_t wait_ms = 0;
};

struct CommandList {
  Command items[MAX_COMMANDS];
  size_t count = 0;
};

constexpr size_t MAX_FIELD_LEN = 31;

// error must be a static string literal, never a pointer into the parsed
// JSON (which does not outlive parse_commands()). field is copied into an
// owned buffer, so it may safely come from parsed JSON.
struct ParseResult {
  bool ok = false;
  const char* error = nullptr;
  int index = -1;
  char field[MAX_FIELD_LEN + 1] = "";

  ParseResult() = default;
  ParseResult(bool ok, const char* error, int index, const char* field_in)
      : ok(ok), error(error), index(index) {
    if (field_in) {
      strncpy(field, field_in, MAX_FIELD_LEN);
      field[MAX_FIELD_LEN] = '\0';
    }
  }
};

ParseResult parse_commands(const char* json, size_t len, CommandList* out);

// A held controller state: the Command fields without hold_ms/wait_ms. On
// success hold_ms and wait_ms of *out are 0.
ParseResult parse_state(const char* json, size_t len, Command* out);
