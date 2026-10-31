# firmware

Snapshot of `firmware/` from [switch-controller-esp32s3-mcp-server](../../switch-controller-esp32s3-mcp-server) at commit `d12f9e6`.

## Getting Started

### Prerequisites

Repo-wide setup: [root README](../../switch-controller-esp32s3-mcp-server/README.md)

### Installation

```sh
cd firmware
uv sync
```

## Usage

Before the first build, copy the secrets template and fill in your WiFi credentials and the host's zenoh endpoint (placeholder values compile fine, but the file must exist — `uv run pio run` fails otherwise):

```sh
cp secrets.ini.example secrets.ini
```

Build:

```sh
uv run pio run
```

zenoh-pico's build shells out to `cmake`; it comes from the root `mise install` (see [ADR-0007](../../switch-controller-esp32s3-mcp-server/docs/adr/0007-mise-manages-cmake-for-zenoh-pico.md)). Without mise active in your shell, the build fails with `FileNotFoundError: ... 'cmake'`.

Flash (needs a USB cable to the board):

```sh
uv run pio run -t upload
```

The board's only USB port is dedicated to emulating a Switch controller (`ARDUINO_USB_MODE=0`), so there's no USB serial for uploads — put the board in bootloader mode manually (hold BOOT, tap RESET, release BOOT) before running the upload.

For the same reason, `Serial` output goes out UART0 (pins D6/D7, GPIO43/44) at 115200 baud, not over USB — read it with an external USB-TTL adapter.

## CI

PRs touching `firmware/` are built and format-checked by GitHub Actions ([ADR-0011](../../switch-controller-esp32s3-mcp-server/docs/adr/0011-github-actions-ci-for-firmware.md)).

## Changes from the snapshot

Added in this repo, on top of `d12f9e6`:

- `switch-controller/state` queryable: payload is one JSON object with `buttons`, `hat`, `lx`, `ly`, `rx`, `ry` (no `hold_ms` or `wait_ms`). The state is applied immediately, the reply is `{"ok":true}`, and the state stays held until replaced.
- Watchdog: if no state arrives for `STATE_TIMEOUT_MS` (1000 ms), the firmware sends a neutral frame, so a stalled or crashed host cannot leave buttons pressed.
- A `state` request during a `commands` macro is rejected with `{"error":"busy"}`. A macro cancels any held state.
- `loop()` is the only HID writer. The Zenoh callback passes the latest state through a one-slot queue.
- The pure parts live in `src/state_hold.{hpp,cpp}` and `parse_state()`; tests are in `test/test_state_hold/` and `test/test_command_parser/`.
- `WiFi.setSleep(false)` after the WiFi connects. With modem sleep on, a Zenoh round trip measured median 50 ms and p90 150 ms.
