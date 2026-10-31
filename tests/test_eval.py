import json
from pathlib import Path

import pytest

from s1play import ledger
from s1play.eval import (
    EvalError,
    attempt_scores,
    delta_ci,
    ended,
    mean_ci,
    run_eval,
    verdict,
)

ROOT = Path(__file__).parent.parent / "harnesses" / "jev"
LEVEL = 3328.0


def log_rows(games, clear_in=None, interrupt_last=False):
    """One row per progress value. A game's last three rows show the game-over screen."""
    rows = []
    for attempt, progress in enumerate(games, start=1):
        for i, px in enumerate(progress):
            over = i >= len(progress) - 3 and not (interrupt_last and attempt == len(games))
            rows.append(
                {
                    "step": len(rows),
                    "action": "RUN",
                    "scores": {"game_over": 0.9 if over else 0.05, "title_screen": 0.05},
                    "attempt": attempt,
                    "life": 0,
                    "progress": px,
                    "best_progress": 99999,
                    "cleared": attempt == clear_in and i == len(progress) - 1,
                }
            )
    return rows


def write_log(run_dir, rows):
    run_dir.mkdir(parents=True)
    (run_dir / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def fake_play(batches):
    """Each call writes the next batch of games as a log, and returns exit code 0."""
    calls = []

    def play(run_dir, attempts):
        calls.append((run_dir, attempts))
        write_log(run_dir, log_rows([[0, px, px, px] for px in batches[len(calls) - 1]]))
        return 0

    play.calls = calls
    return play


def test_attempt_score_is_the_best_life_and_ignores_the_cross_attempt_best_progress():
    rows = log_rows([[10, 80, 0, 50, 50, 50], [0, 30, 30, 30]])
    assert attempt_scores(rows, LEVEL) == [80, 30]


def test_a_clear_scores_the_level_length():
    rows = log_rows([[10, 20, 20, 20], [0, 500, 500, 500]], clear_in=2)
    assert attempt_scores(rows, LEVEL) == [20, LEVEL]


def test_a_log_ends_only_on_a_game_over_screen_or_a_clear():
    assert ended(log_rows([[10, 20, 30, 40]]))
    assert not ended(log_rows([[10, 20, 30, 40]], interrupt_last=True))
    assert ended(log_rows([[10, 20, 30, 40]], clear_in=1, interrupt_last=True))


def test_bootstrap_of_constant_values_is_exact():
    assert mean_ci([100.0] * 5) == (100.0, 100.0, 100.0)
    assert delta_ci([200.0] * 5, [100.0] * 5) == (100.0, 100.0)


@pytest.mark.parametrize(
    ("candidate", "decision", "needs_more"),
    [
        ([900.0] * 5, "champion", False),
        ([100.0] * 5, "rejected", False),
        ([50.0] * 5, "rejected", False),
        ([100.0, 200.0, 300.0, 400.0, 500.0], "rejected", True),
    ],
    ids=["clear win", "no gain", "clear loss", "overlap"],
)
def test_candidate_must_beat_the_champion_and_overlap_earns_one_more_batch(
    candidate, decision, needs_more
):
    champion = [100.0, 200.0, 300.0, 400.0, 500.0] if needs_more else [100.0] * 5
    result = verdict("candidate", candidate, champion, extended=False)
    assert (result.decision, result.needs_more) == (decision, needs_more)
    assert not verdict("candidate", candidate, champion, extended=True).needs_more


def test_baseline_becomes_champion_and_transfer_is_only_recorded():
    assert verdict("baseline", [1.0], None, extended=False).decision == "champion"
    assert verdict("transfer", [1.0], None, extended=False).decision == "transfer"


def test_baseline_run_writes_a_ledger_row(tmp_path):
    play = fake_play([[100, 200, 300, 400, 500]])
    path = tmp_path / "ledger.tsv"

    row = run_eval(
        "jev", ROOT / "v0.toml", "baseline", 5, play, "20261031-190000",
        ledger_path=path, runs_dir=tmp_path / "runs",
    )  # fmt: skip
    ledger.append(row, path)

    saved = ledger.read(path)[0]
    assert saved["id"] == "20261031-190000-jev-v0"
    assert (saved["attempts"], saved["mean_best_px"], saved["decision"]) == (
        "5",
        "300.0",
        "champion",
    )
    assert saved["attempt_px"] == "100.0,200.0,300.0,400.0,500.0"
    assert saved["delta_ci_lo"] == ""
    assert play.calls == [(tmp_path / "runs" / "20261031-190000-jev-v0", 5)]


def baseline(tmp_path):
    path = tmp_path / "ledger.tsv"
    row = run_eval(
        "jev", ROOT / "v0.toml", "baseline", 5, fake_play([[100, 200, 300, 400, 500]]), "t0",
        ledger_path=path, runs_dir=tmp_path / "runs0",
    )  # fmt: skip
    ledger.append(row, path)
    return path


def test_winning_candidate_is_gated_against_the_champions_ledger_row(tmp_path):
    path = baseline(tmp_path)
    row = run_eval(
        "jev", ROOT / "v1.toml", "candidate", 5, fake_play([[900] * 5]), "t1",
        ledger_path=path, runs_dir=tmp_path / "runs1", gate=(0.91, -0.01),
    )  # fmt: skip
    assert (row.decision, row.parent, row.gate_action_recall) == ("champion", "v0", 0.91)
    assert row.delta_ci_lo is not None and row.delta_ci_lo > 0


def test_overlapping_candidate_runs_one_extension_and_pools_both_batches(tmp_path):
    path = baseline(tmp_path)
    play = fake_play([[100, 200, 300, 400, 500], [100, 200, 300, 400, 500]])

    row = run_eval(
        "jev", ROOT / "v1.toml", "candidate", 5, play, "t1",
        ledger_path=path, runs_dir=tmp_path / "runs1",
    )  # fmt: skip

    assert [call[0].name for call in play.calls] == ["t1-jev-v1", "t1-jev-v1-ext"]
    assert (row.attempts, row.decision) == (10, "rejected")
    assert len(row.run_dirs) == 2


def test_candidate_without_a_champion_baseline_is_an_error(tmp_path):
    with pytest.raises(EvalError, match="baseline"):
        run_eval(
            "jev", ROOT / "v1.toml", "candidate", 5, fake_play([[1] * 5]), "t",
            ledger_path=tmp_path / "none.tsv", runs_dir=tmp_path / "runs",
        )  # fmt: skip


def test_interrupted_run_raises_and_leaves_no_row(tmp_path):
    def play(run_dir, attempts):
        write_log(run_dir, log_rows([[1, 2, 3, 4]] * 5, interrupt_last=True))
        return 0

    path = tmp_path / "ledger.tsv"
    with pytest.raises(EvalError, match="interrupted"):
        run_eval(
            "jev", ROOT / "v0.toml", "baseline", 5, play, "t",
            ledger_path=path, runs_dir=tmp_path / "runs",
        )  # fmt: skip
    assert not path.exists()


def test_failed_play_raises_with_the_run_dir(tmp_path):
    with pytest.raises(EvalError, match="exited with 2"):
        run_eval(
            "jev", ROOT / "v0.toml", "baseline", 5, lambda d, n: 2, "t",
            ledger_path=tmp_path / "l.tsv", runs_dir=tmp_path / "runs",
        )  # fmt: skip


def test_ledger_writes_one_header_and_keeps_free_text_on_one_line(tmp_path):
    path = baseline(tmp_path)
    row = ledger.read(path)[0]
    assert list(row) == ledger.COLUMNS
    assert len(path.read_text().splitlines()) == 2
