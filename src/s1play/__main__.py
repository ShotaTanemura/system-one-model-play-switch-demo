import argparse
import os
from datetime import datetime
from pathlib import Path

from s1play.controller import ZenohController
from s1play.episode import EpisodeManager
from s1play.frames import ObsFrameSource
from s1play.games import GAMES
from s1play.law import RunnerLaw
from s1play.loop import run
from s1play.policy import ChoicePolicy, QuestionsPolicy, RandomPolicy, SystemOneClient

POLICIES = ["random", "jev", "clef-omni", "jev-choice", "clef-omni-choice"]


def build_policy(name: str):
    if name == "random":
        return RandomPolicy()
    backend = name.removesuffix("-choice")
    client = SystemOneClient(backend)
    return (
        ChoicePolicy(client) if name.endswith("-choice") else QuestionsPolicy(client, RunnerLaw())
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play")
    p.add_argument("--game", choices=list(GAMES), required=True)
    p.add_argument("--policy", choices=POLICIES, default="random")
    p.add_argument("--obs-source", default=os.environ.get("OBS_SOURCE", "Switch"))
    p.add_argument("--frame-width", type=int, default=640)
    p.add_argument("--listen", default="tcp/0.0.0.0:7447")
    p.add_argument("--dry-run", action="store_true", help="grab and decide, never send inputs")
    p.add_argument("--max-steps", type=int)
    p.add_argument("--auto-restart", action="store_true", help="restart after game over")
    p.add_argument("--attempts", type=int, help="stop after this many games (with --auto-restart)")
    args = p.parse_args()

    questions_policy = args.policy in ("jev", "clef-omni")
    if args.auto_restart and not questions_policy:
        p.error("--auto-restart needs --policy jev or clef-omni (it reads the screen state)")
    if args.auto_restart and args.dry_run:
        p.error("--auto-restart sends inputs, so it cannot be combined with --dry-run")

    policy = build_policy(args.policy)
    frames = ObsFrameSource(args.obs_source, out_width=args.frame_width)
    controller = None if args.dry_run else ZenohController(args.listen)
    if controller is not None:
        controller.wait_for_device()

    episodes = EpisodeManager() if questions_policy else None
    run_dir = Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        run(
            frames,
            policy,
            controller,
            GAMES[args.game],
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
