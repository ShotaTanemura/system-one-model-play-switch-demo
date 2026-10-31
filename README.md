# s1play

Lets a System One model (Jev or Clef-omni) play a Switch game. Each step grabs the current frame from OBS, asks the model to choose one action from a per-game menu, and sets that action's held controller state on an ESP32-S3 over Zenoh. The controller firmware in `firmware/` is an unmodified snapshot of [switch-controller-esp32s3-mcp-server](../switch-controller-esp32s3-mcp-server) at `d12f9e6`.

Games: Super Mario Bros. (`mario`) and Donkey Kong Country (`dkc`), played through Nintendo Switch Online.

## Data leaves your machine

The `jev` and `clef-omni` policies send every game frame to TypeSafe or Cloudflare. The `random` policy and `--dry-run` send nothing outside this machine.

## Setup

1. Build and flash the ESP32 from `firmware/` (see [firmware/README.md](firmware/README.md)). First copy `firmware/secrets.ini.example` to `firmware/secrets.ini` (gitignored), then set your WiFi SSID and password and `ZENOH_CONNECT` to `tcp/<this-machine-ip>:7447`.
2. In OBS, enable the WebSocket server (Tools > WebSocket Server Settings) and name the capture source, for example `Switch`.
3. Stop the reference MCP server. Only one peer can listen on `:7447`.
4. Export credentials in your own shell. Never commit them.

   ```sh
   export OBS_WS_PASSWORD=...
   export TYPESAFE_API_KEY=...          # jev
   export CLOUDFLARE_ACCOUNT_ID=...     # clef-omni
   export CLOUDFLARE_API_TOKEN=...      # clef-omni
   ```

5. `uv sync`

## Policies

| `--policy` | What it does |
|---|---|
| `random` | Picks a random action each step. Nothing leaves this machine. |
| `jev`, `clef-omni` | Asks the model several yes/no questions about each frame (enemy ahead, gap ahead, airborne, game over, ...). A small local rule in `law.py` turns the probabilities into RUN, RUN_JUMP or WAIT. |
| `jev-choice`, `clef-omni-choice` | Baseline: the model picks one action from the game's menu directly. |

Actions are held controller states, not timed macros. The firmware keeps the last state until the next one arrives and releases everything if none arrives for one second.

## Run

Start Super Mario Bros. by hand (or let `--auto-restart` do it after a game over), then:

```sh
uv run python -m s1play --game mario --policy random --dry-run             # frames only, no inputs
uv run python -m s1play --game mario --policy random --obs-source avermedia
uv run python -m s1play --game mario --policy jev --obs-source avermedia --max-steps 60
uv run python -m s1play --game mario --policy clef-omni --obs-source avermedia --auto-restart --attempts 10
```

Ctrl-C stops the run and releases all buttons. Each run writes `runs/<timestamp>/log.jsonl` and the frames it saw. With `jev` or `clef-omni` the log also has `attempt`, `life`, `progress` (NES pixels scrolled this life), `best_progress` and `cleared`. The run ends when the HUD world number changes (a cleared level).

## Tools

```sh
# After flashing the firmware: hold RUN for 3 s, then check the watchdog
uv run python -m s1play.hold --action RUN --seconds 3
uv run python -m s1play.hold --action RUN --seconds 3 --no-refresh

# Ask the model about saved frames (sends them to TypeSafe or Cloudflare)
uv run python -m s1play.probe runs/<timestamp> --backend jev --steps 0,26,33
```

## Tests

```sh
uv run pytest
# firmware, from firmware/
uv run pio test -e native
```

## Status

Unit tests pass. On real hardware (ESP32-S3, OBS, Super Mario Bros.):

- Held states work, and the firmware watchdog releases the buttons after about 1 s without an update.
- With the old timed macros, Mario scrolled 8-19 NES px/s (walking is about 90). With held states, the random policy scrolls about 83 NES px/s.
- A `set_state` round trip takes about 8 ms median after `WiFi.setSleep(false)` (it was 50 ms median and 350 ms worst case with modem sleep on).
- The firmware connects to the host once, at boot. After a host restart, press RESET on the ESP32 while the host is listening.
- The first START press on the title screen is often lost. Auto-restart retries until the TIME counter shows.

Not yet run on hardware: the questions policy (`jev`, `clef-omni`), auto-restart and level-clear detection. Jev's request format works for the choice policy; its `noul` answer shape is assumed. The Clef-omni policies have not run against the live API.
