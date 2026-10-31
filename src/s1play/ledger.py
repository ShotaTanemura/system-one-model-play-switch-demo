import csv
from dataclasses import dataclass, fields
from pathlib import Path

LEDGER = Path("experiments/ledger.tsv")


@dataclass(frozen=True)
class Row:
    id: str
    date: str
    model: str
    harness: str
    parent: str
    kind: str
    role: str
    hypothesis: str
    gate_action_recall: float | None
    gate_worst_delta: float | None
    attempts: int | None
    attempt_px: tuple[float, ...]
    mean_best_px: float | None
    ci_lo: float | None
    ci_hi: float | None
    delta_ci_lo: float | None
    clears: int | None
    decision: str
    run_dirs: tuple[str, ...]


COLUMNS = [f.name for f in fields(Row)]


def _dump(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple):
        return ",".join(str(v) for v in value)
    return " ".join(str(value).split())


def append(row: Row, path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    with path.open("a", newline="") as f:
        out = csv.writer(f, delimiter="\t", lineterminator="\n")
        if fresh:
            out.writerow(COLUMNS)
        out.writerow([_dump(getattr(row, c)) for c in COLUMNS])


def read(path: Path = LEDGER) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def champion_row(rows: list[dict[str, str]], model: str, harness: str) -> dict[str, str] | None:
    """The latest row where `harness` became (or started as) the model's champion."""
    won = [
        r
        for r in rows
        if r["model"] == model and r["harness"] == harness and r["decision"] == "champion"
    ]
    return won[-1] if won else None


def attempt_px(row: dict[str, str]) -> list[float]:
    """Empty for a gate_fail row, which never played."""
    return [float(v) for v in row["attempt_px"].split(",") if v]
