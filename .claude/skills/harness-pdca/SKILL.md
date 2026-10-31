---
name: harness-pdca
description: Run one session of the Plan, Do, Check, Act loop that improves a System One model's Super Mario Bros. harness. Use for /harness-pdca <jev|clef-omni>, or when asked to improve a model's harness and compare it with the other model.
---

# Harness PDCA

The argument is the model, `jev` or `clef-omni`. A harness is a versioned file `harnesses/<model>/vN.toml`. The champion is named in `harnesses/<model>/CHAMPION`. A candidate replaces it only after a live batch beats it. Run every command with `uv run`. If uv cannot write its cache in a sandbox, call `.venv/bin/python -m ...` instead.

## Before the first iteration

1. Run `python -m s1play.pdca now` and keep the stamp as `SINCE`.
2. `git status --short` must be empty. Ask the user to commit or move stray files, because `pdca guard` reads the working tree.
3. Say what leaves the machine, then ask the user to confirm before any command that sends frames. Say it once per session, with the target and the size.
   - `bench` sends up to 200 frames of the labeled set to TypeSafe (jev) or Cloudflare (clef-omni). Cached frames are not resent.
   - `eval` sends every frame of 5 to 10 games, about 500 to 1500 requests, to the same service.
4. Check that the keys are set without printing them: `[ -n "$TYPESAFE_API_KEY" ]` for jev, `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` for clef-omni. Never ask for a value and never echo one. If a key is missing, tell the user to export it in their own shell.
5. Ask the user to confirm the hardware before `eval`. OBS shows the Switch, the reference MCP server is stopped, the ESP32 was reset while this host listens, and the game sits at the Super Mario Bros. title screen or its demo, not on the Famicom launcher.

## One iteration

**Plan.**
- Run `python -m s1play.report`, read `experiments/REPORT.md`, and view the champion row's `deaths.jpg`. The "Progress where each life ended" line shows where lives stop.
- Name the dominant stopping point and what the frames show there.
- Write one falsifiable hypothesis with numbers, such as "lives ending near 590 px fall from 8 of 15 to 4 or fewer". Change one thing per iteration.
- Copy the champion to `harnesses/<model>/v<N+1>.toml`. Set `parent` and `hypothesis`, then make the change. Decision logic that does not fit the TOML becomes a new named entry in `LAWS` in `law.py`, with a test. Never edit an existing law, because older ledger rows must stay reproducible.

**Do.**
- `python -m pytest`, `ruff check .`, then `python -m s1play.pdca guard`. Guard fails on any file outside harnesses, `law.py`, `policy.py`, tests and experiments. If a fix to measurement is needed, stop and tell the user. It changes how rows compare.
- `python -m s1play.bench --model <m> --harness <file>`. Exit 0 is PASS and 1 is FAIL. Keep the printed action recall delta and worst question delta.
- On FAIL, run `python -m s1play.pdca gate-fail --model <m> --harness <file> --recall <delta> --worst <delta>` and skip to "After each iteration". A gate failure plays no games.

**Check.**
- `python -m s1play.eval --model <m> --harness <file> --role candidate --gate-recall <delta> --gate-worst <delta>`.
- A non-zero exit, a RestartError or a lost ESP32 means stop. Tell the user and wait. The run wrote no row. Do not retry on your own.

**Act.**
- On a win, `eval` prints "Win". Run `python -m s1play.pdca promote --model <m> --harness <file>`. It refuses without a winning candidate row. Then ask the user to ready the hardware for a transfer batch. Run the new harness on the other model with `--role transfer`, so the report can show whether the gain carries over.
- On a loss, the row is already in the ledger. Keep the harness file so the row stays reproducible.
- Run `python -m s1play.report`, then commit locally: the harness file, any law and test changes, `harnesses/*/CHAMPION` and `experiments/`. The message names the hypothesis, the numbers and the decision. Never push.

## After each iteration

Run `python -m s1play.pdca status --model <m> --since <SINCE>`. Exit 2 means a stop rule was reached, either 3 of the model's candidates rejected in a row or 6 live evaluations this session. Stop, regenerate the report, and give the user the champion table and what the sheets show.

## Reading results

- Each row is 5 games, or 10 when the CIs overlapped. Say so, and quote the CI with the mean.
- A game's score is the best of its three lives. Read the per-life line before crediting a gain. A win that rests on 2 or 3 lives is weak.
- Compare with the champion's own row. Never compare across models, because each model has its own thresholds.
- Do not rerun a rejected candidate hoping for a better draw. Change the hypothesis.
