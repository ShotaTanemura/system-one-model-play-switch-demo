import argparse
import os
from datetime import datetime
from pathlib import Path

from s1play.controller import ZenohController
from s1play.episode import EpisodeManager
from s1play.frames import ObsFrameSource
from s1play.games import GAMES
from s1play.harness import build_policy, load
from s1play.loop import run
from s1play.policy import RandomPolicy

MODELS = ["random", "jev", "clef-omni", "startlux"]


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play")
    p.add_argument("--game", choices=list(GAMES), required=True)
    p.add_argument("--model", choices=MODELS, default="random")
    p.add_argument("--harness", type=Path, help="harnesses/<model>/vN.toml (not for random)")
    p.add_argument("--obs-source", default=os.environ.get("OBS_SOURCE", "Switch"))
    p.add_argument("--frame-width", type=int, default=640)
    p.add_argument("--listen", default="tcp/0.0.0.0:7447")
    p.add_argument("--dry-run", action="store_true", help="grab and decide, never send inputs")
    p.add_argument("--max-steps", type=int)
    p.add_argument("--auto-restart", action="store_true", help="restart after game over")
    p.add_argument("--attempts", type=int, help="stop after this many games (with --auto-restart)")
    p.add_argument("--run-dir", type=Path, help="default: runs/<timestamp>")
    args = p.parse_args()

    live_model = args.model != "random"
    if live_model != (args.harness is not None):
        p.error(
            "--harness is required with jev, clef-omni or startlux, and not allowed with random"
        )
    if args.auto_restart and not live_model:
        p.error(
            "--auto-restart needs --model jev, clef-omni or startlux (it reads the screen state)"
        )
    if args.auto_restart and args.dry_run:
        p.error("--auto-restart sends inputs, so it cannot be combined with --dry-run")

    profile = GAMES[args.game]
    if live_model:
        harness = load(args.harness)
        profile = harness.profile(profile)
        policy = build_policy(args.model, harness)
    else:
        policy = RandomPolicy()
    frames = ObsFrameSource(args.obs_source, out_width=args.frame_width)
    controller = None if args.dry_run else ZenohController(args.listen)
    if controller is not None:
        controller.wait_for_device()

    episodes = EpisodeManager() if live_model else None
    run_dir = args.run_dir or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        run(
            frames,
            policy,
            controller,
            profile,
            run_dir,
            args.max_steps,
            episodes,
            args.attempts if args.auto_restart else 1,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if controller is not None:
            controller.close()


if __name__ == "__main__":
    main()
