#include <Arduino.h>
// SwitchControllerESP32.h has no include guard -- included from exactly one
// TU.
#include <SwitchControllerESP32.h>
#include <WiFi.h>
#include <zenoh-pico.h>

#include "command.hpp"
#include "executor.hpp"
#include "state_hold.hpp"

#define KEYEXPR_PING "switch-controller/ping"
#define KEYEXPR_COMMANDS "switch-controller/commands"
#define KEYEXPR_STATE "switch-controller/state"

static_assert(BTN_Y == static_cast<uint16_t>(Button::Y));
static_assert(BTN_B == static_cast<uint16_t>(Button::B));
static_assert(BTN_A == static_cast<uint16_t>(Button::A));
static_assert(BTN_X == static_cast<uint16_t>(Button::X));
static_assert(BTN_L == static_cast<uint16_t>(Button::L));
static_assert(BTN_R == static_cast<uint16_t>(Button::R));
static_assert(BTN_ZL == static_cast<uint16_t>(Button::ZL));
static_assert(BTN_ZR == static_cast<uint16_t>(Button::ZR));
static_assert(BTN_MINUS == static_cast<uint16_t>(Button::MINUS));
static_assert(BTN_PLUS == static_cast<uint16_t>(Button::PLUS));
static_assert(BTN_LCLICK == static_cast<uint16_t>(Button::LCLICK));
static_assert(BTN_RCLICK == static_cast<uint16_t>(Button::RCLICK));
static_assert(BTN_HOME == static_cast<uint16_t>(Button::HOME));
static_assert(BTN_CAPTURE == static_cast<uint16_t>(Button::CAPTURE));

static_assert(HAT_UP == static_cast<uint8_t>(Hat::UP));
static_assert(HAT_UP_RIGHT == static_cast<uint8_t>(Hat::UP_RIGHT));
static_assert(HAT_RIGHT == static_cast<uint8_t>(Hat::RIGHT));
static_assert(HAT_RIGHT_DOWN == static_cast<uint8_t>(Hat::RIGHT_DOWN));
static_assert(HAT_DOWN == static_cast<uint8_t>(Hat::DOWN));
static_assert(HAT_DOWN_LEFT == static_cast<uint8_t>(Hat::DOWN_LEFT));
static_assert(HAT_LEFT == static_cast<uint8_t>(Hat::LEFT));
static_assert(HAT_LEFT_UP == static_cast<uint8_t>(Hat::LEFT_UP));
static_assert(HAT_CENTER == static_cast<uint8_t>(Hat::CENTER));

static z_owned_session_t session;
static z_owned_queryable_t ping_queryable;
static z_owned_queryable_t commands_queryable;
static z_owned_queryable_t state_queryable;

static CommandList g_commands;
static SemaphoreHandle_t g_idle;
static SemaphoreHandle_t g_job_ready;
static z_owned_query_t g_pending_query;

// Held states reach the HID endpoint only through loop(), the single writer.
// The queue has length 1 and is overwritten, so only the latest state counts.
static QueueHandle_t g_state_queue;
static StateHold g_state_hold;
static volatile bool g_macro_running = false;

static void ping_query_handler(z_loaned_query_t* query, void* arg) {
  z_view_keyexpr_t ke;
  z_view_keyexpr_from_str_unchecked(&ke, KEYEXPR_PING);
  z_owned_bytes_t payload;
  z_bytes_from_static_str(&payload, "pong");
  if (z_query_reply(query, z_view_keyexpr_loan(&ke), z_bytes_move(&payload),
                    NULL) != 0) {
    Serial.println("z_query_reply failed");
  }
}

static bool make_reply_payload(const char* body, z_owned_bytes_t* out) {
  if (z_bytes_copy_from_str(out, body) != 0) {
    Serial.println("z_bytes_copy_from_str failed");
    return false;
  }
  return true;
}

static void reply_ok_json(const z_loaned_query_t* query, const char* keyexpr,
                          const char* body) {
  z_owned_bytes_t reply_payload;
  if (!make_reply_payload(body, &reply_payload)) return;
  z_view_keyexpr_t ke;
  z_view_keyexpr_from_str_unchecked(&ke, keyexpr);
  if (z_query_reply(query, z_view_keyexpr_loan(&ke),
                    z_bytes_move(&reply_payload), NULL) != 0) {
    Serial.println("z_query_reply failed");
  }
}

static void reply_err_json(const z_loaned_query_t* query, const char* body) {
  z_owned_bytes_t reply_payload;
  if (!make_reply_payload(body, &reply_payload)) return;
  if (z_query_reply_err(query, z_bytes_move(&reply_payload), NULL) != 0) {
    Serial.println("z_query_reply_err failed");
  }
}

static bool send_frame(const Frame& frame) {
  USB_JoystickReport_Input_t report = {};
  report.Button = frame.buttons;
  report.Hat = frame.hat;
  report.LX = frame.lx;
  report.LY = frame.ly;
  report.RX = frame.rx;
  report.RY = frame.ry;
  // sendReportOnly() returns void, discarding sendReport()'s bool.
  SwitchController().sendReportOnly(report);
  return SwitchController().sendReport();
}

static void sleep_ms(uint32_t ms) { delay(ms); }

static void state_query_handler(z_loaned_query_t* query, void* arg) {
  if (g_macro_running) {
    reply_err_json(query, "{\"error\":\"busy\"}");
    return;
  }

  z_owned_slice_t slice;
  z_bytes_to_slice(z_query_payload(query), &slice);
  const char* json =
      reinterpret_cast<const char*>(z_slice_data(z_slice_loan(&slice)));
  size_t len = z_slice_len(z_slice_loan(&slice));

  Command state;
  ParseResult result = parse_state(json, len, &state);
  z_slice_drop(z_slice_move(&slice));

  if (!result.ok) {
    char body[160];
    snprintf(body, sizeof(body), "{\"error\":\"%s\",\"field\":\"%s\"}",
             result.error, result.field);
    reply_err_json(query, body);
    Serial.printf("state rejected: %s (field %s)\n", result.error,
                  result.field);
    return;
  }

  Frame frame = frame_from_command(state);
  xQueueOverwrite(g_state_queue, &frame);
  reply_ok_json(query, KEYEXPR_STATE, "{\"ok\":true}");
}

// Called from loop() only, which owns the HID endpoint.
static void service_held_state() {
  Frame frame;
  if (xQueueReceive(g_state_queue, &frame, 0) == pdTRUE) {
    send_frame(frame);
    g_state_hold.set(millis());
  }
  if (g_state_hold.expired(millis())) {
    send_frame(frame_from_command(Command{}));
  }
}

static void commands_query_handler(z_loaned_query_t* query, void* arg) {
  if (xSemaphoreTake(g_idle, 0) != pdTRUE) {
    reply_err_json(query, "{\"error\":\"busy\"}");
    return;
  }

  z_owned_slice_t slice;
  z_bytes_to_slice(z_query_payload(query), &slice);
  const char* json =
      reinterpret_cast<const char*>(z_slice_data(z_slice_loan(&slice)));
  size_t len = z_slice_len(z_slice_loan(&slice));

  ParseResult result = parse_commands(json, len, &g_commands);
  z_slice_drop(z_slice_move(&slice));

  if (!result.ok) {
    char body[160];
    snprintf(body, sizeof(body),
             "{\"error\":\"%s\",\"index\":%d,\"field\":\"%s\"}", result.error,
             result.index, result.field);
    reply_err_json(query, body);
    Serial.printf("commands rejected: %s (index %d, field %s)\n", result.error,
                  result.index, result.field);
    xSemaphoreGive(g_idle);
    return;
  }

  if (z_query_clone(&g_pending_query, query) != 0) {
    Serial.println("z_query_clone failed");
    reply_err_json(query, "{\"error\":\"clone_failed\"}");
    xSemaphoreGive(g_idle);
    return;
  }

  xSemaphoreGive(g_job_ready);
}

void setup() {
  Serial.begin(115200);
  switchcontrolleresp32_init();
  USB.begin();

  g_idle = xSemaphoreCreateBinary();
  g_job_ready = xSemaphoreCreateBinary();
  g_state_queue = xQueueCreate(1, sizeof(Frame));
  if (g_idle == NULL || g_job_ready == NULL || g_state_queue == NULL) {
    Serial.println("xSemaphoreCreateBinary failed");
    return;
  }
  xSemaphoreGive(g_idle);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);
  }
  // Modem sleep adds 100-300 ms spikes to every Zenoh round trip (measured:
  // median 50 ms, p90 150 ms).
  WiFi.setSleep(false);

  // ZENOH_C_STANDARD=99 (set by zenoh-pico's extra_script.py here) disables the
  // z_loan_mut()/z_move() macros, so the typed z_<type>_* forms are used
  // directly.
  z_owned_config_t config;
  z_config_default(&config);
  zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_MODE_KEY, "client");
  zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_CONNECT_KEY,
                   ZENOH_CONNECT);

  // z_open() auto-starts the read/lease tasks; zp_start_*_task() are deprecated
  // no-ops as of 1.10.
  if (z_open(&session, z_config_move(&config), NULL) != 0) {
    Serial.println("z_open failed");
    return;
  }
  Serial.println("zenoh session opened");

  z_owned_closure_query_t ping_callback;
  z_closure_query(&ping_callback, ping_query_handler, NULL, NULL);
  z_view_keyexpr_t ping_ke;
  z_view_keyexpr_from_str_unchecked(&ping_ke, KEYEXPR_PING);
  if (z_declare_queryable(z_session_loan(&session), &ping_queryable,
                          z_view_keyexpr_loan(&ping_ke),
                          z_closure_query_move(&ping_callback), NULL) != 0) {
    Serial.println("z_declare_queryable failed");
    return;
  }
  Serial.println("queryable declared on " KEYEXPR_PING);

  z_owned_closure_query_t commands_callback;
  z_closure_query(&commands_callback, commands_query_handler, NULL, NULL);
  z_view_keyexpr_t commands_ke;
  z_view_keyexpr_from_str_unchecked(&commands_ke, KEYEXPR_COMMANDS);
  if (z_declare_queryable(z_session_loan(&session), &commands_queryable,
                          z_view_keyexpr_loan(&commands_ke),
                          z_closure_query_move(&commands_callback),
                          NULL) != 0) {
    Serial.println("z_declare_queryable failed");
    return;
  }
  Serial.println("queryable declared on " KEYEXPR_COMMANDS);

  z_owned_closure_query_t state_callback;
  z_closure_query(&state_callback, state_query_handler, NULL, NULL);
  z_view_keyexpr_t state_ke;
  z_view_keyexpr_from_str_unchecked(&state_ke, KEYEXPR_STATE);
  if (z_declare_queryable(z_session_loan(&session), &state_queryable,
                          z_view_keyexpr_loan(&state_ke),
                          z_closure_query_move(&state_callback), NULL) != 0) {
    Serial.println("z_declare_queryable failed");
    return;
  }
  Serial.println("queryable declared on " KEYEXPR_STATE);
}

void loop() {
  if (xSemaphoreTake(g_job_ready, pdMS_TO_TICKS(10)) != pdTRUE) {
    service_held_state();
    return;
  }
  // A macro starts and ends with a neutral frame, so any held state is over.
  g_macro_running = true;
  g_state_hold.clear();
  xQueueReset(g_state_queue);
  ExecResult result = run_commands(g_commands, send_frame, sleep_ms);
  g_macro_running = false;
  const z_loaned_query_t* query = z_query_loan(&g_pending_query);
  if (result.ok) {
    char body[32];
    snprintf(body, sizeof(body), "{\"executed\":%zu}", result.index);
    reply_ok_json(query, KEYEXPR_COMMANDS, body);
    Serial.printf("commands executed: %zu\n", result.index);
  } else {
    char body[64];
    snprintf(body, sizeof(body),
             "{\"error\":\"hid_send_failed\",\"index\":%zu}", result.index);
    reply_err_json(query, body);
    Serial.printf("commands hid_send_failed at index %zu\n", result.index);
  }
  z_query_drop(z_query_move(&g_pending_query));
  xSemaphoreGive(g_idle);
}
