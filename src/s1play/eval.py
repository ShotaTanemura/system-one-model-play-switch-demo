import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from s1play import ledger
from s1play.harness import load
from s1play.ledger import Row

ROLES = ("baseline", "candidate", "transfer")
BOOTSTRAP = 10_000
SEED = 0
ENDED_FRAMES = 3
SCREEN_THRESHOLD = 0.5
# Assumed, not measured: 224 tiles of 16 px, minus the 256 px screen. Replace it with the
# scroll of a real clear, and re-run with --level-px; the ledger keeps clears separately.
LEVEL_PX = 3328.0

Play = Callable[[Path, int], int]


class EvalError(Exception):
    pass


@dataclass(frozen=True)
class Verdict:
    decision: str
    delta_lo: float | None = None
    delta_hi: float | None = None
    needs_more: bool = False


def read_log(run_dir: Path) -> list[dict]:
    lines = (run_dir / "log.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def attempt_scores(rows: Sequence[dict], level_px: float) -> list[float]:
    """Best progress per attempt. `best_progress` in the log spans attempts, so take the
    maximum of the per-life `progress` instead. A cleared level counts as `level_px`."""
    best: dict[int, float] = defaultdict(float)
    for r in rows:
        best[r["attempt"]] = (
            level_px if r["cleared"] else max(best[r["attempt"]], float(r["progress"]))
        )
    return [best[a] for a in sorted(best)]


def ended(rows: Sequence[dict]) -> bool:
    """True when the log stops on a finished game, not on an interrupt in the middle of one."""
    tail = rows[-ENDED_FRAMES:]
    if rows and rows[-1]["cleared"]:
        return True
    over = [max(r["scores"]["game_over"], r["scores"]["title_screen"]) for r in tail]
    return len(tail) == ENDED_FRAMES and all(p > SCREEN_THRESHOLD for p in over)


def _means(values: Sequence[float], rng: np.random.Generator) -> np.ndarray:
    return rng.choice(np.asarray(values), size=(BOOTSTRAP, len(values))).mean(axis=1)


def mean_ci(values: Sequence[float]) -> tuple[float, float, float]:
    lo, hi = np.percentile(_means(values, np.random.default_rng(SEED)), [2.5, 97.5])
    return float(np.mean(values)), float(lo), float(hi)


def delta_ci(candidate: Sequence[float], champion: Sequence[float]) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    diff = _means(candidate, rng) - _means(champion, rng)
    lo, hi = np.percentile(diff, [2.5, 97.5])
    return float(lo), float(hi)


def verdict(role: str, px: Sequence[float], champion_px: Sequence[float] | None, extended: bool):
    if role == "transfer":
        return Verdict("transfer")
    if role == "baseline":
        return Verdict("champion")
    assert champion_px is not None
    lo, hi = delta_ci(px, champion_px)
    if lo > 0:
        return Verdict("champion", lo, hi)
    return Verdict("rejected", lo, hi, needs_more=hi > 0 and not extended)


def collect(play: Play, run_dir: Path, attempts: int, level_px: float) -> tuple[list[float], bool]:
    code = play(run_dir, attempts)
    if code != 0:
        raise EvalError(f"s1play exited with {code}. No ledger row was written; see {run_dir}.")
    rows = read_log(run_dir)
    scores = attempt_scores(rows, level_px)
    cleared = any(r["cleared"] for r in rows)
    if not rows or not ended(rows) or (len(scores) != attempts and not cleared):
        raise EvalError(
            f"{run_dir} has {len(scores)} of {attempts} finished games, so it was interrupted. "
            "No ledger row was written."
        )
    return scores, cleared


def run_eval(
    model: str,
    harness_path: Path,
    role: str,
    attempts: int,
    play: Play,
    stamp: str,
    ledger_path: Path = ledger.LEDGER,
    runs_dir: Path = Path("runs"),
    level_px: float = LEVEL_PX,
    gate: tuple[float, float] | None = None,
) -> Row:
    harness = load(harness_path)
    champion_px = None
    if role == "candidate":
        champ_name = (harness_path.parent / "CHAMPION").read_text().strip()
        champ = ledger.champion_row(ledger.read(ledger_path), model, champ_name)
        if champ is None:
            raise EvalError(f"No {model} {champ_name} baseline in {ledger_path}. Run it first.")
        champion_px = ledger.attempt_px(champ)

    run_id = f"{stamp}-{model}-{harness.name}"
    dirs = [runs_dir / run_id]
    px, cleared = collect(play, dirs[0], attempts, level_px)
    result = verdict(role, px, champion_px, extended=False)
    if result.needs_more and not cleared:
        dirs.append(runs_dir / f"{run_id}-ext")
        more, cleared = collect(play, dirs[1], attempts, level_px)
        px += more
        result = verdict(role, px, champion_px, extended=True)

    mean, lo, hi = mean_ci(px)
    return Row(
        id=run_id,
        date=stamp,
        model=model,
        harness=harness.name,
        parent=harness.parent,
        kind=harness.kind,
        role=role,
        hypothesis=harness.hypothesis,
        gate_action_recall=gate[0] if gate else None,
        gate_worst_delta=gate[1] if gate else None,
        attempts=len(px),
        attempt_px=tuple(round(v, 1) for v in px),
        mean_best_px=round(mean, 1),
        ci_lo=round(lo, 1),
        ci_hi=round(hi, 1),
        delta_ci_lo=None if result.delta_lo is None else round(result.delta_lo, 1),
        clears=sum(v >= level_px for v in px),
        decision=result.decision,
        run_dirs=tuple(str(d) for d in dirs),
    )


def subprocess_play(model: str, harness: Path, obs_source: str, listen: str) -> Play:
    def play(run_dir: Path, attempts: int) -> int:
        cmd = [
            sys.executable, "-m", "s1play", "--game", "mario", "--model", model,
            "--harness", str(harness), "--obs-source", obs_source, "--listen", listen,
            "--auto-restart", "--attempts", str(attempts), "--run-dir", str(run_dir),
        ]  # fmt: skip
        return subprocess.run(cmd, check=False).returncode

    return play


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.eval")
    p.add_argument("--model", choices=["jev", "clef-omni"], required=True)
    p.add_argument("--harness", type=Path, required=True)
    p.add_argument("--role", choices=ROLES, required=True)
    p.add_argument("--attempts", type=int, default=5)
    p.add_argument("--obs-source", default=os.environ.get("OBS_SOURCE", "Switch"))
    p.add_argument("--listen", default="tcp/0.0.0.0:7447")
    p.add_argument("--level-px", type=float, default=LEVEL_PX)
    p.add_argument("--gate-recall", type=float, help="from s1play.bench, for the ledger row")
    p.add_argument("--gate-worst", type=float, help="from s1play.bench, for the ledger row")
    args = p.parse_args()

    gate = (args.gate_recall, args.gate_worst) if args.gate_recall is not None else None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    play = subprocess_play(args.model, args.harness, args.obs_source, args.listen)
    print(
        f"Playing {args.attempts} games with {args.model} {args.harness.stem}. Every frame is sent "
        "to the model API. Stop the reference MCP server first, and press RESET on the ESP32 "
        "while this host is listening."
    )
    try:
        row = run_eval(
            args.model, args.harness, args.role, args.attempts, play, stamp,
            level_px=args.level_px, gate=gate,
        )  # fmt: skip
    except EvalError as e:
        raise SystemExit(str(e)) from e
    ledger.append(row)
    ci = f"[{row.ci_lo}, {row.ci_hi}]"
    print(f"{row.id}: mean best {row.mean_best_px} NES px over {row.attempts} games, 95% CI {ci}")
    print(f"per game: {list(row.attempt_px)}  clears: {row.clears}")
    print(
        f"decision: {row.decision}"
        + (f" (delta CI lower bound {row.delta_ci_lo})" if row.delta_ci_lo is not None else "")
    )
    if row.role == "candidate" and row.decision == "champion":
        print(f"Win. Write {args.harness.stem} to {args.harness.parent / 'CHAMPION'}.")


if __name__ == "__main__":
    main()
