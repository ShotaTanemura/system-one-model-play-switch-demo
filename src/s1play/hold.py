import argparse
import time

from s1play.controller import NEUTRAL, ZenohController
from s1play.games import GAMES

REFRESH_S = 0.2


def main() -> None:
    p = argparse.ArgumentParser(
        prog="s1play.hold", description="Hold one action on the controller, to test the firmware"
    )
    p.add_argument("--game", choices=list(GAMES), default="mario")
    p.add_argument("--action", default="RUN", help="an action name of the game, e.g. RUN")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument(
        "--no-refresh",
        action="store_true",
        help="send the state once and go quiet, so the firmware watchdog releases it",
    )
    p.add_argument("--listen", default="tcp/0.0.0.0:7447")
    args = p.parse_args()

    state = GAMES[args.game].actions[args.action]
    controller = ZenohController(args.listen)
    try:
        controller.wait_for_device()
        started = time.monotonic()
        controller.set_state(state)
        print(f"holding {args.action} {state.payload()} for {args.seconds}s")
        while time.monotonic() - started < args.seconds:
            time.sleep(REFRESH_S)
            if not args.no_refresh:
                controller.set_state(state)
    finally:
        if args.no_refresh:
            print("no refresh sent: the firmware should have released the buttons after ~1 s")
        else:
            controller.set_state(NEUTRAL)
        controller.close()


if __name__ == "__main__":
    main()
