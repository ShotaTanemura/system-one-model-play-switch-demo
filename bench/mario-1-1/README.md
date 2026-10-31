# Mario 1-1 bench frames

200 frames sampled from `runs/` by `python -m s1play.label sample`: every frame in the 3 steps before a life ended, then evenly spaced frames per run. Labels were written by Claude from the images and audited by a human before this set was frozen.

`labels.jsonl` row: `frame`, `source_run`, `labels` (the 9 yes/no questions of `harnesses/*/v0.toml`), `action`, `dead`, `note`.

- `action` is WAIT on non-gameplay screens, RUN_JUMP when `jump_now` is true, else RUN.
- `dead: true` means Mario is in the death animation or off screen. No input has an effect, so `action` is WAIT, and the gate leaves these frames out of action accuracy and out of the ahead/airborne questions. They still count for `transition`, `game_over`, `title_screen` and `level_clear`.
- A `note` starting with `unsure:` marks a doubtful label.
- Only 11 frames are RUN_JUMP, so action accuracy is dominated by RUN and WAIT. Read the per-question accuracy of `jump_now` next to it.
- `reviewed: true` means a human checked the frame and its labels on the review screen (`python -m s1play.review`). All 200 frames were reviewed before this set was frozen.
