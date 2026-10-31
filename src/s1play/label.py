import argparse
import itertools
import json
import random
import shutil
from pathlib import Path

BENCH = Path("bench/mario-1-1")
FRAMES_PER_DEATH = 3
SEED = 0


def _rows(run: Path) -> list[dict]:
    log = run / "log.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def death_frames(rows: list[dict]) -> list[int]:
    """Steps just before a life ended. Only logs with a `life` column can say."""
    out = []
    for prev, nxt in itertools.pairwise(rows):
        if "life" in prev and nxt.get("life", prev["life"]) > prev["life"]:
            out += range(max(0, prev["step"] - FRAMES_PER_DEATH + 1), prev["step"] + 1)
    return out


def pick(runs: dict[str, list[dict]], total: int) -> list[tuple[str, int]]:
    """Every pre-death frame first, then evenly spaced frames from each run, capped at `total`."""
    deaths = {(name, step) for name, rows in runs.items() for step in death_frames(rows)}
    pool = sum(len(rows) for rows in runs.values())
    spaced = set()
    for name, rows in runs.items():
        want = round(total * len(rows) / pool)
        stride = max(1, len(rows) // max(1, want))
        spaced |= {(name, row["step"]) for row in rows[::stride]}
    rest = sorted(spaced - deaths)
    room = max(0, total - len(deaths))
    if len(rest) > room:
        rest = random.Random(SEED).sample(rest, room)
    return sorted(deaths | set(rest))[:total]


def sample(runs_dir: Path, total: int) -> None:
    runs = {d.name: _rows(d) for d in sorted(runs_dir.iterdir()) if d.is_dir()}
    runs = {name: rows for name, rows in runs.items() if rows}
    (BENCH / "frames").mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, step in pick(runs, total):
        frame = f"frames/{name}_{step:06d}.jpg"
        shutil.copyfile(runs_dir / name / "frames" / f"{step:06d}.jpg", BENCH / frame)
        manifest.append({"frame": frame, "source_run": name, "step": step})
    (BENCH / "manifest.jsonl").write_text("".join(json.dumps(m) + "\n" for m in manifest))
    print(f"{len(manifest)} frames copied to {BENCH / 'frames'}")


def audit_sample(frames: list[str], fraction: float = 0.1) -> list[str]:
    k = max(1, round(len(frames) * fraction))
    return random.Random(SEED).sample(frames, k)


def audit(fraction: float, unsure: bool, unreviewed: bool) -> None:
    labels = [json.loads(line) for line in (BENCH / "labels.jsonl").read_text().splitlines()]
    if unsure:
        shown = [r for r in labels if r["note"].startswith("unsure:")]
    else:
        picked = set(audit_sample([r["frame"] for r in labels], fraction))
        shown = [r for r in labels if r["frame"] in picked]
    if unreviewed:
        shown = [r for r in shown if not r.get("reviewed")]
    for row in sorted(shown, key=lambda r: r["frame"]):
        yes = ",".join(q for q, v in row["labels"].items() if v) or "-"
        dead = " DEAD" if row["dead"] else ""
        print(f"{BENCH / row['frame']}  action={row['action']}{dead}  yes={yes}  {row['note']}")


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.label")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="copy a stratified frame set from runs/ into bench/")
    s.add_argument("--runs", type=Path, default=Path("runs"))
    s.add_argument("--total", type=int, default=200)
    a = sub.add_parser("audit", help="list a random sample of labels for a human to check")
    a.add_argument("--fraction", type=float, default=0.1)
    a.add_argument("--unsure", action="store_true", help="list the labels the labeler doubted")
    a.add_argument("--unreviewed", action="store_true", help="skip frames a human already reviewed")
    args = p.parse_args()
    if args.cmd == "sample":
        sample(args.runs, args.total)
    else:
        audit(args.fraction, args.unsure, args.unreviewed)


if __name__ == "__main__":
    main()
