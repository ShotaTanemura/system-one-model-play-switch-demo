#include <ArduinoJson.h>

#include <cstring>

#include "command.hpp"

namespace {

bool find_button(const char* name, uint16_t* out) {
  for (size_t i = 0; i < kButtonNameCount; ++i) {
    if (strcmp(name, kButtonNames[i].name) == 0) {
      *out = kButtonNames[i].value;
      return true;
    }
  }
  return false;
}

bool find_hat(const char* name, uint8_t* out) {
  for (size_t i = 0; i < kHatNameCount; ++i) {
    if (strcmp(name, kHatNames[i].name) == 0) {
      *out = kHatNames[i].value;
      return true;
    }
  }
  return false;
}

ParseResult fail(const char* error, int index, const char* field) {
  return ParseResult{false, error, index, field};
}

bool in_stick_range(int32_t v) { return v >= MIN_STICK && v <= MAX_STICK; }

// state_only: a held state has no timing, so hold_ms/wait_ms are rejected and
// hold_ms is not required.
ParseResult parse_command(JsonObjectConst obj, int index, Command* cmd,
                          bool state_only = false) {
  bool has_hold = false;

  for (JsonPairConst kv : obj) {
    const char* key = kv.key().c_str();
    JsonVariantConst value = kv.value();

    if (strcmp(key, "buttons") == 0) {
      if (!value.is<JsonArrayConst>()) {
        return fail("buttons must be an array", index, "buttons");
      }
      for (JsonVariantConst b : value.as<JsonArrayConst>()) {
        if (!b.is<const char*>()) {
          return fail("button name must be a string", index, "buttons");
        }
        uint16_t bit;
        if (!find_button(b.as<const char*>(), &bit)) {
          return fail("unknown button", index, "buttons");
        }
        cmd->buttons |= bit;
      }
    } else if (strcmp(key, "hat") == 0) {
      if (!value.is<const char*>()) {
        return fail("hat must be a string", index, "hat");
      }
      if (!find_hat(value.as<const char*>(), &cmd->hat)) {
        return fail("unknown hat", index, "hat");
      }
    } else if (strcmp(key, "lx") == 0 || strcmp(key, "ly") == 0 ||
               strcmp(key, "rx") == 0 || strcmp(key, "ry") == 0) {
      const char* field;
      int8_t* slot;
      if (strcmp(key, "lx") == 0) {
        field = "lx";
        slot = &cmd->lx;
      } else if (strcmp(key, "ly") == 0) {
        field = "ly";
        slot = &cmd->ly;
      } else if (strcmp(key, "rx") == 0) {
        field = "rx";
        slot = &cmd->rx;
      } else {
        field = "ry";
        slot = &cmd->ry;
      }
      if (!value.is<int>()) {
        return fail("stick value must be an integer", index, field);
      }
      int32_t v = value.as<int32_t>();
      if (!in_stick_range(v)) {
        return fail("stick value out of range", index, field);
      }
      *slot = static_cast<int8_t>(v);
    } else if (!state_only &&
               (strcmp(key, "hold_ms") == 0 || strcmp(key, "wait_ms") == 0)) {
      bool is_hold = strcmp(key, "hold_ms") == 0;
      const char* field = is_hold ? "hold_ms" : "wait_ms";
      if (!value.is<int>() || value.as<int32_t>() < 0) {
        return fail("duration must be a non-negative integer", index, field);
      }
      uint32_t v = value.as<uint32_t>();
      uint16_t max_v = is_hold ? MAX_HOLD_MS : MAX_WAIT_MS;
      if (v > max_v) {
        return fail("duration too long", index, field);
      }
      if (is_hold) {
        cmd->hold_ms = static_cast<uint16_t>(v);
        has_hold = true;
      } else {
        cmd->wait_ms = static_cast<uint16_t>(v);
      }
    } else {
      return fail("unrecognized field", index, key);
    }
  }

  if (!state_only && !has_hold) {
    return fail("hold_ms is required", index, "hold_ms");
  }
  return ParseResult{true, nullptr, -1, nullptr};
}

}  // namespace

ParseResult parse_state(const char* json, size_t len, Command* out) {
  if (len > MAX_PAYLOAD_BYTES) {
    return fail("payload too large", -1, nullptr);
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json, len);
  if (err) {
    return fail("malformed json", -1, nullptr);
  }
  if (!doc.is<JsonObjectConst>()) {
    return fail("state must be an object", -1, nullptr);
  }

  Command state;
  ParseResult result =
      parse_command(doc.as<JsonObjectConst>(), -1, &state, /*state_only=*/true);
  if (!result.ok) {
    return result;
  }
  *out = state;
  return ParseResult{true, nullptr, -1, nullptr};
}

ParseResult parse_commands(const char* json, size_t len, CommandList* out) {
  if (len > MAX_PAYLOAD_BYTES) {
    return fail("payload too large", -1, nullptr);
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json, len);
  if (err) {
    return fail("malformed json", -1, nullptr);
  }

  if (!doc["commands"].is<JsonArrayConst>()) {
    return fail("commands must be an array", -1, "commands");
  }
  JsonArrayConst commands = doc["commands"].as<JsonArrayConst>();

  if (commands.size() == 0) {
    return fail("commands must not be empty", -1, "commands");
  }
  if (commands.size() > MAX_COMMANDS) {
    return fail("too many commands", -1, "commands");
  }

  CommandList scratch;
  int index = 0;
  for (JsonVariantConst v : commands) {
    if (!v.is<JsonObjectConst>()) {
      return fail("command must be an object", index, nullptr);
    }
    Command cmd;
    ParseResult result = parse_command(v.as<JsonObjectConst>(), index, &cmd);
    if (!result.ok) {
      return result;
    }
    scratch.items[scratch.count++] = cmd;
    ++index;
  }

  *out = scratch;
  return ParseResult{true, nullptr, -1, nullptr};
}
