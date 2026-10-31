import argparse
import json
from pathlib import Path

from s1play.frames import prepare
from s1play.games import GAMES
from s1play.policy import SystemOneClient, noul_questions


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.probe", description="Ask the model about saved frames")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--backend", choices=["jev", "clef-omni"], required=True)
    p.add_argument("--steps", required=True, help="comma-separated step numbers, e.g. 0,26,33")
    p.add_argument("--game", choices=list(GAMES), default="mario")
    p.add_argument(
        "--crop-old",
        action="store_true",
        help="frames are from a run made before frame cropping existed",
    )
    args = p.parse_args()

    questions = noul_questions(GAMES[args.game])
    client = SystemOneClient(args.backend)
    rows = [json.loads(line) for line in (args.run_dir / "log.jsonl").read_text().splitlines()]
    by_step = {r["step"]: r for r in rows}

    ids = list(questions)
    print("step  " + " ".join(f"{qid[:9]:>9}" for qid in ids))
    for step in (int(s) for s in args.steps.split(",")):
        frame = (args.run_dir / by_step[step]["frame"]).read_bytes()
        if args.crop_old:
            frame = prepare(frame)
        answers = client.ask(frame, questions)
        print(f"{step:4d}  " + " ".join(f"{answers[qid]['noul']:9.2f}" for qid in ids))


if __name__ == "__main__":
    main()
