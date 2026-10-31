import json
import time
from pathlib import Path

from s1play.controller import NEUTRAL, Controller
from s1play.episode import EpisodeManager
from s1play.frames import FrameSource
from s1play.games import GameProfile
from s1play.policy import Policy


def run(
    frames: FrameSource,
    policy: Policy,
    controller: Controller | None,
    profile: GameProfile,
    run_dir: Path,
    max_steps: int | None = None,
    episodes: EpisodeManager | None = None,
    max_attempts: int | None = None,
) -> int:
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    step = 0
    with (run_dir / "log.jsonl").open("a") as log:
        try:
            while max_steps is None or step < max_steps:
                t0 = time.perf_counter()
                frame = frames.grab()
                t1 = time.perf_counter()
                decision = policy.decide(frame, profile)
                t2 = time.perf_counter()
                if controller is not None:
                    controller.set_state(profile.actions[decision.action])
                t3 = time.perf_counter()

                frame_path = f"frames/{step:06d}.jpg"
                (run_dir / frame_path).write_bytes(frame)
                row = {
                    "step": step,
                    "action": decision.action,
                    "scores": decision.scores,
                    "frame": frame_path,
                    "grab_ms": round((t1 - t0) * 1000, 1),
                    "decide_ms": round((t2 - t1) * 1000, 1),
                    "send_ms": round((t3 - t2) * 1000, 1),
                }
                game_over = False
                if episodes is not None:
                    game_over = episodes.observe(frame, decision.scores)
                    row |= {
                        "attempt": episodes.attempt,
                        "life": episodes.life,
                        "progress": round(episodes.progress, 1),
                        "best_progress": round(episodes.best_progress, 1),
                        "cleared": episodes.cleared,
                    }
                log.write(json.dumps(row) + "\n")
                log.flush()
                top = sorted(decision.scores.items(), key=lambda kv: -kv[1])[:3]
                print(
                    f"{step:5d} {decision.action:<9} "
                    + " ".join(f"{k}={v:.2f}" for k, v in top)
                    + f" grab={row['grab_ms']}ms decide={row['decide_ms']}ms set={row['send_ms']}ms"
                )
                step += 1
                if episodes is not None and episodes.cleared:
                    print(
                        f"cleared the level on attempt {episodes.attempt}, life {episodes.life + 1}"
                    )
                    break
                if game_over:
                    print(f"no game running, best progress {episodes.best_progress:.0f} NES px")
                    if controller is None or (max_attempts and episodes.attempt >= max_attempts):
                        break
                    episodes.restart(frames, policy, controller, profile)
        finally:
            if controller is not None:
                controller.set_state(NEUTRAL)
    return step
