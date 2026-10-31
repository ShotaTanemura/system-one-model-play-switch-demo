# s1play

Lets a System One model (Jev or Clef-omni) play a Switch game. Each step grabs the current frame from OBS, asks the model to choose one action from a per-game menu, and sets that action's held controller state on an ESP32-S3 over Zenoh. The controller firmware in `firmware/` is an unmodified snapshot of [switch-controller-esp32s3-mcp-server](../switch-controller-esp32s3-mcp-server) at `d12f9e6`.

Games: Super Mario Bros. (`mario`) and Donkey Kong Country (`dkc`), played through Nintendo Switch Online.

## Data leaves your machine

The `jev` and `clef-omni` models send every game frame to TypeSafe or Cloudflare. The `random` model and `--dry-run` send nothing outside this machine.

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

## Models and harnesses

`--model random` picks a random action each step and sends nothing outside this machine. `--model jev` and `--model clef-omni` need `--harness harnesses/<model>/vN.toml`. A harness is everything between the model and the controller that can change:

| `kind` | What it does |
|---|---|
| `questions` | Asks the model several yes/no questions about each frame (enemy ahead, gap ahead, airborne, game over, ...). The local rule named by `law` (see `LAWS` in `law.py`, tuned by `[law_params]`) turns the probabilities into RUN, RUN_JUMP or WAIT. |
| `choice` | Baseline. The model picks one action from the menu directly. It also answers the `transition`, `game_over` and `title_screen` questions so auto-restart works. |

`v0.toml` is today's questions and law, and `v0-choice.toml` is the choice baseline. `harnesses/<model>/CHAMPION` names the current best version.

Actions are held controller states, not timed macros. The firmware keeps the last state until the next one arrives and releases everything if none arrives for one second.

## Run

Start Super Mario Bros. by hand (or let `--auto-restart` do it after a game over), then:

```sh
uv run python -m s1play --game mario --model random --dry-run             # frames only, no inputs
uv run python -m s1play --game mario --model random --obs-source avermedia
uv run python -m s1play --game mario --model jev --harness harnesses/jev/v0.toml --obs-source avermedia --max-steps 60
uv run python -m s1play --game mario --model clef-omni --harness harnesses/clef-omni/v0.toml --obs-source avermedia --auto-restart --attempts 10
```

Ctrl-C stops the run and releases all buttons. Each run writes `runs/<timestamp>/log.jsonl` and the frames it saw. With `jev` or `clef-omni` the log also has `attempt`, `life`, `progress` (NES pixels scrolled this life), `best_progress` and `cleared`. The run ends when the HUD world number changes (a cleared level).

## Comparing harnesses

Two checks decide whether a harness beats the model's champion (`harnesses/<model>/CHAMPION`).

```sh
# Offline gate on the 200 labeled frames in bench/mario-1-1/. Uncached frames go to the model API.
uv run python -m s1play.bench --model jev --harness harnesses/jev/v1.toml

# Live verdict. Plays 5 games on the Switch, appends a row to experiments/ledger.tsv.
uv run python -m s1play.eval --model jev --harness harnesses/jev/v0.toml --role baseline
uv run python -m s1play.eval --model jev --harness harnesses/jev/v1.toml --role candidate
```

`bench` passes when action recall (mean recall over RUN, RUN_JUMP and WAIT) does not drop and no question's balanced accuracy drops by more than 0.05. `eval` scores each game by its best scroll progress in NES pixels, with a clear counting as `--level-px`. A candidate wins when the bootstrap 95% CI of its mean minus the champion's is above zero. If that CI includes zero, `eval` plays 5 more games once and pools them. `--role transfer` records a harness on the other model without judging it. `eval` writes no row when a run is interrupted or fails. Fix the cause and run it again.

The labels were written by Claude and checked by a human on a local page: `uv run python -m s1play.review`.

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

The questions policy (`jev`, `clef-omni`) and auto-restart have run on hardware: 5 auto-restarted games each with the `v0` harnesses. Level-clear detection has not fired yet, so it is untested. A `set_state` round trip and a model call take about 10 ms and 150-270 ms, so a game of about 100-175 steps lasts well under a minute.
