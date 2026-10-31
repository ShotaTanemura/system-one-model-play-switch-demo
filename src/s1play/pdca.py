import argparse
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from s1play import ledger
from s1play.harness import load
from s1play.ledger import Row

MAX_REJECTS = 3
MAX_LIVE_EVALS = 6
HARNESSES = Path("harnesses")
# The loop may write only these. Frame capture, the controller, progress tracking, the
# episode manager, the bench labels and the bench, eval, ledger and report code stay fixed,
# so a score never moves because the thing measuring it changed.
ALLOWED = ("harnesses/", "src/s1play/law.py", "src/s1play/policy.py", "tests/", "experiments/")


class PdcaError(Exception):
    pass


def violations(paths: Sequence[str]) -> list[str]:
    return [p for p in paths if not p.startswith(ALLOWED)]


def changed_paths() -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line[3:].split(" -> ")[-1] for line in out.splitlines()]


def session_status(rows: Sequence[dict[str, str]], model: str, since: str) -> tuple[int, int]:
    """Live evaluations since `since`, and how many of the model's candidates in a row lost."""
    mine = [r for r in rows if r["date"] >= since]
    live = sum(1 for r in mine if r["attempt_px"])
    streak = 0
    for r in reversed([r for r in mine if r["model"] == model and r["role"] == "candidate"]):
        if r["decision"] not in ("rejected", "gate_fail"):
            break
        streak += 1
    return live, streak


def gate_fail_row(model: str, harness_path: Path, recall: float, worst: float, stamp: str) -> Row:
    harness = load(harness_path)
    return Row(
        id=f"{stamp}-{model}-{harness.name}-gate",
        date=stamp,
        model=model,
        harness=f"{harness_path.parent.name}/{harness.name}",
        parent=harness.parent,
        kind=harness.kind,
        role="candidate",
        hypothesis=harness.hypothesis,
        gate_action_recall=recall,
        gate_worst_delta=worst,
        attempts=None,
        attempt_px=(),
        mean_best_px=None,
        ci_lo=None,
        ci_hi=None,
        delta_ci_lo=None,
        clears=None,
        decision="gate_fail",
        run_dirs=(),
    )


def promote(
    model: str, harness_path: Path, rows: Sequence[dict[str, str]], root: Path = HARNESSES
) -> str:
    """Writes CHAMPION, but only for a harness whose latest champion row is a candidate win."""
    name = harness_path.stem
    champion_file = root / model / "CHAMPION"
    if champion_file.read_text().strip() == name:
        return f"{model} {name} is already the champion."
    won = ledger.champion_row(list(rows), model, f"{model}/{name}")
    if won is None or won["role"] != "candidate":
        raise PdcaError(f"No winning candidate row for {model}/{name} in the ledger.")
    champion_file.write_text(f"{name}\n")
    return f"{model} champion is now {name} (row {won['id']})."


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.pdca")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="exit 2 when the session's stop rule is reached")
    s.add_argument("--model", required=True)
    s.add_argument("--since", required=True, help="session start, YYYYMMDD-HHMMSS")
    sub.add_parser("guard", help="exit 1 if a file outside the loop's allow-list changed")
    g = sub.add_parser("gate-fail", help="log a candidate that failed the offline gate")
    g.add_argument("--model", required=True)
    g.add_argument("--harness", type=Path, required=True)
    g.add_argument("--recall", type=float, required=True)
    g.add_argument("--worst", type=float, required=True)
    w = sub.add_parser("promote", help="make a winning candidate the model's champion")
    w.add_argument("--model", required=True)
    w.add_argument("--harness", type=Path, required=True)
    sub.add_parser("now", help="print a session start stamp")
    args = p.parse_args()

    if args.cmd == "now":
        print(datetime.now().strftime("%Y%m%d-%H%M%S"))
    elif args.cmd == "guard":
        bad = violations(changed_paths())
        if bad:
            raise SystemExit("These files are fixed during the loop:\n  " + "\n  ".join(bad))
        print("ok: only loop files changed")
    elif args.cmd == "status":
        live, streak = session_status(ledger.read(), args.model, args.since)
        print(f"live evals this session: {live}/{MAX_LIVE_EVALS}")
        print(f"{args.model} candidates rejected in a row: {streak}/{MAX_REJECTS}")
        if live >= MAX_LIVE_EVALS or streak >= MAX_REJECTS:
            print("Stop rule reached. Regenerate the report and tell the user.")
            raise SystemExit(2)
    elif args.cmd == "gate-fail":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        ledger.append(gate_fail_row(args.model, args.harness, args.recall, args.worst, stamp))
        print("logged gate_fail")
    else:
        try:
            print(promote(args.model, args.harness, ledger.read()))
        except PdcaError as e:
            raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
