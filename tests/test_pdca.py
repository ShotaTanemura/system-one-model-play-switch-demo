import shutil
from pathlib import Path

import pytest

from s1play import ledger
from s1play.pdca import PdcaError, gate_fail_row, promote, session_status, violations
from s1play.report import current_rows, markdown

REAL = Path(__file__).parent.parent / "harnesses"


def row(id_, date, decision="rejected", role="candidate", model="jev", played=True, **over):
    base = dict.fromkeys(ledger.COLUMNS, "")
    base |= {
        "id": id_,
        "date": date,
        "model": model,
        "harness": f"{model}/{id_}",
        "role": role,
        "decision": decision,
        "attempt_px": "1.0,2.0" if played else "",
    }
    return base | over


def test_loop_may_change_harnesses_laws_policy_tests_and_experiments_only():
    changed = [
        "harnesses/jev/v2.toml",
        "src/s1play/law.py",
        "src/s1play/policy.py",
        "tests/test_law.py",
        "experiments/ledger.tsv",
        "src/s1play/progress.py",
        "src/s1play/episode.py",
        "src/s1play/eval.py",
        "bench/mario-1-1/labels.jsonl",
    ]
    assert violations(changed) == [
        "src/s1play/progress.py",
        "src/s1play/episode.py",
        "src/s1play/eval.py",
        "bench/mario-1-1/labels.jsonl",
    ]


def test_status_counts_this_sessions_live_evals_and_the_trailing_rejects_of_one_model():
    rows = [
        row("old", "20261031-100000"),
        row("a", "20261031-200000", decision="champion"),
        row("b", "20261031-200100", decision="gate_fail", played=False),
        row("c", "20261031-200200"),
        row("d", "20261031-200300", model="clef-omni"),
        row("e", "20261031-200400", decision="transfer", role="transfer"),
    ]
    assert session_status(rows, "jev", "20261031-190000") == (4, 2)
    assert session_status(rows, "clef-omni", "20261031-190000") == (4, 1)


def test_a_win_resets_the_reject_streak():
    rows = [row("a", "t1"), row("b", "t2"), row("c", "t3", decision="champion")]
    assert session_status(rows, "jev", "t0") == (3, 0)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "harnesses"
    (root / "jev").mkdir(parents=True)
    (root / "jev" / "CHAMPION").write_text("v0\n")
    return root


def test_promote_writes_champion_only_for_a_candidate_win_in_the_ledger(tree):
    rows = [row("v1", "t1", decision="champion", harness="jev/v1")]
    assert "champion is now v1" in promote("jev", tree / "jev" / "v1.toml", rows, tree)
    assert (tree / "jev" / "CHAMPION").read_text() == "v1\n"
    assert "already" in promote("jev", tree / "jev" / "v1.toml", rows, tree)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row("v1", "t1", decision="rejected", harness="jev/v1")],
        [row("v1", "t1", decision="champion", role="baseline", harness="jev/v1")],
    ],
    ids=["no row", "rejected", "baseline row"],
)
def test_promote_refuses_without_a_winning_candidate_row(tree, rows):
    with pytest.raises(PdcaError, match="No winning candidate"):
        promote("jev", tree / "jev" / "v1.toml", rows, tree)
    assert (tree / "jev" / "CHAMPION").read_text() == "v0\n"


def test_gate_fail_row_has_the_gate_scores_and_no_live_results(tmp_path):
    shutil.copy(REAL / "jev" / "v1.toml", tmp_path / "v1.toml")
    path = tmp_path / "jev"
    path.mkdir()
    shutil.move(tmp_path / "v1.toml", path / "v1.toml")

    made = gate_fail_row("jev", path / "v1.toml", 0.5, -0.07, "20261031-210000")
    ledger_path = tmp_path / "ledger.tsv"
    ledger.append(made, ledger_path)

    saved = ledger.read(ledger_path)[0]
    assert (saved["id"], saved["harness"], saved["decision"]) == (
        "20261031-210000-jev-v1-gate",
        "jev/v1",
        "gate_fail",
    )
    assert (saved["gate_action_recall"], saved["gate_worst_delta"]) == ("0.5", "-0.07")
    assert (saved["attempts"], saved["attempt_px"], saved["run_dirs"]) == ("", "", "")
    assert ledger.attempt_px(saved) == []


def test_report_shows_a_gate_fail_row_as_not_played_and_keeps_it_out_of_the_table():
    played = row("a", "t1", decision="champion", mean_best_px="5.0", ci_lo="1.0", ci_hi="9.0",
                 attempts="2", clears="0", role="baseline", harness="jev/v0")  # fmt: skip
    failed = row("b", "t2", decision="gate_fail", played=False, harness="jev/v2")

    text = markdown(current_rows([played, failed]), {"jev": "v0"}, [], {})

    assert "| jev/v2 | candidate | not played | - | gate_fail |  |" in text
    assert "| jev/v2 |" not in text.split("## Model against model")[1]
