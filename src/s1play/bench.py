import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from s1play.games import GAMES
from s1play.harness import Harness, build_policy, load
from s1play.label import BENCH
from s1play.policy import Asker, Decision, Questions, SystemOneClient

CACHE = BENCH.parent / "cache"
THRESHOLD = 0.5
MAX_QUESTION_DROP = 0.05
SCREENS = ("transition", "game_over", "title_screen", "level_clear")


@dataclass(frozen=True)
class Score:
    """`action_recall` is the mean recall over the action classes. Plain accuracy would
    reward a harness for never jumping, since most live frames are RUN or WAIT."""

    action_recall: float
    questions: Mapping[str, float | None]
    by_action: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Gate:
    passed: bool
    action_delta: float
    worst_question: str
    worst_delta: float


class CachingClient:
    """Serves repeated (backend, questions, frame) requests from disk.

    The key leaves out the model version, so clear the cache directory when `jev-latest`
    or `clef-omni` changes underneath it, or when you serve a different `startlux` checkpoint.
    """

    def __init__(self, backend: str, make_inner: Callable[[], Asker], cache: Path = CACHE) -> None:
        self._backend = backend
        self._make_inner = make_inner
        self._inner: Asker | None = None
        self._cache = cache
        self.hits = 0
        self.misses = 0

    def ask(self, frame: bytes, questions: Questions) -> dict:
        digest = hashlib.sha256(
            json.dumps([self._backend, questions], sort_keys=True).encode() + frame
        ).hexdigest()
        path = self._cache / f"{digest}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text())
        self._inner = self._inner or self._make_inner()
        answers = self._inner.ask(frame, questions)
        self._cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answers))
        self.misses += 1
        return answers


def balanced_accuracy(pairs: Sequence[tuple[bool, bool]]) -> float | None:
    """Mean of recall on the yes frames and on the no frames. A class with no frames is skipped."""
    yes = [pred for label, pred in pairs if label]
    no = [not pred for label, pred in pairs if not label]
    parts = [sum(group) / len(group) for group in (yes, no) if group]
    return sum(parts) / len(parts) if parts else None


def score(rows: Sequence[Mapping], decisions: Sequence[Decision]) -> Score:
    """Dead frames count only for the screen questions, since no input has an effect on them."""
    live = [(r, d) for r, d in zip(rows, decisions, strict=True) if not r["dead"]]
    by_action = {}
    for action in sorted({r["action"] for r, _ in live}):
        of_class = [d for r, d in live if r["action"] == action]
        by_action[action] = sum(d.action == action for d in of_class) / len(of_class)
    asked = set.intersection(*(set(d.scores) for d in decisions)) & set(rows[0]["labels"])
    questions = {}
    for qid in sorted(asked):
        used = zip(rows, decisions, strict=True) if qid in SCREENS else iter(live)
        questions[qid] = balanced_accuracy(
            [(r["labels"][qid], d.scores[qid] > THRESHOLD) for r, d in used]
        )
    return Score(sum(by_action.values()) / len(by_action), questions, by_action)


def gate(candidate: Score, champion: Score) -> Gate:
    shared = [
        q
        for q in candidate.questions
        if candidate.questions[q] is not None and champion.questions.get(q) is not None
    ]
    deltas = {q: candidate.questions[q] - champion.questions[q] for q in shared}
    worst = min(deltas, key=deltas.get) if deltas else ""
    worst_delta = deltas.get(worst, 0.0)
    action_delta = candidate.action_recall - champion.action_recall
    passed = action_delta >= 0 and worst_delta >= -MAX_QUESTION_DROP
    return Gate(passed, action_delta, worst, worst_delta)


def decide_all(
    backend: Literal["jev", "clef-omni", "startlux"],
    harness: Harness,
    rows: Sequence[Mapping],
    client: Asker,
    bench_dir: Path = BENCH,
) -> list[Decision]:
    profile = harness.profile(GAMES["mario"])
    out = []
    for row in rows:
        # A fresh policy per frame, so the law's jump-hold state never leaks between frames.
        policy = build_policy(backend, harness, client)
        out.append(policy.decide((bench_dir / row["frame"]).read_bytes(), profile))
    return out


def evaluate(
    backend: Literal["jev", "clef-omni", "startlux"], harness: Harness, rows: Sequence[Mapping]
) -> tuple[Score, CachingClient]:
    client = CachingClient(backend, lambda: SystemOneClient(backend))
    return score(rows, decide_all(backend, harness, rows, client)), client


def champion_path(model: str) -> Path:
    root = Path("harnesses") / model
    return root / f"{(root / 'CHAMPION').read_text().strip()}.toml"


def show(name: str, s: Score) -> None:
    per_class = " ".join(f"{a} {r:.2f}" for a, r in s.by_action.items())
    print(f"{name}: action recall {s.action_recall:.3f} ({per_class})")
    for qid, acc in s.questions.items():
        print(f"  {qid:<20} {'n/a' if acc is None else f'{acc:.3f}'}")


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.bench")
    p.add_argument("--model", choices=["jev", "clef-omni", "startlux"], required=True)
    p.add_argument("--harness", type=Path, required=True)
    p.add_argument("--champion", type=Path, help="default: the model's CHAMPION harness")
    p.add_argument("--limit", type=int, help="use only the first N bench frames")
    args = p.parse_args()

    rows = [json.loads(line) for line in (BENCH / "labels.jsonl").read_text().splitlines()]
    rows = rows[: args.limit]
    print(f"{len(rows)} bench frames. Uncached ones are sent to the {args.model} API.")

    candidate, client = evaluate(args.model, load(args.harness), rows)
    show(args.harness.stem, candidate)
    print(f"cache: {client.hits} hits, {client.misses} requests")

    champion = args.champion or champion_path(args.model)
    if champion.resolve() == args.harness.resolve():
        print("This is the champion, so there is nothing to gate.")
        return
    other, _ = evaluate(args.model, load(champion), rows)
    show(f"champion {champion.stem}", other)
    g = gate(candidate, other)
    print(
        f"{'PASS' if g.passed else 'FAIL'}: action {g.action_delta:+.3f}, "
        f"worst question {g.worst_question} {g.worst_delta:+.3f} (limit -{MAX_QUESTION_DROP})"
    )
    raise SystemExit(0 if g.passed else 1)


if __name__ == "__main__":
    main()
