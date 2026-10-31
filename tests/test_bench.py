from pathlib import Path

import pytest

from s1play.bench import (
    CachingClient,
    Score,
    balanced_accuracy,
    decide_all,
    gate,
    score,
)
from s1play.harness import load

V0 = load(Path(__file__).parent.parent / "harnesses" / "jev" / "v0.toml")
QUESTIONS = list(V0.questions)


class FakeClient:
    def __init__(self, by_frame: dict[bytes, dict[str, float]]) -> None:
        self.by_frame = by_frame
        self.calls = 0

    def ask(self, frame, questions):
        self.calls += 1
        probs = self.by_frame[frame]
        return {qid: {"type": "noul", "noul": probs.get(qid, 0.05)} for qid in questions}


def row(name, action="RUN", dead=False, **yes):
    return {
        "frame": f"frames/{name}.jpg",
        "labels": {q: q in yes for q in QUESTIONS},
        "action": action,
        "dead": dead,
    }


def bench_dir(tmp_path, names):
    (tmp_path / "frames").mkdir()
    for name in names:
        (tmp_path / "frames" / f"{name}.jpg").write_bytes(name.encode())
    return tmp_path


def test_balanced_accuracy_averages_recall_on_each_class():
    pairs = [(True, True), (True, False), (False, False), (False, False), (False, True)]
    assert balanced_accuracy(pairs) == pytest.approx((1 / 2 + 2 / 3) / 2)
    assert balanced_accuracy([(False, False), (False, False)]) == 1.0
    assert balanced_accuracy([]) is None


def test_score_counts_dead_frames_only_for_the_screen_questions(tmp_path):
    rows = [
        row("a"),
        row("b", action="RUN_JUMP", jump_now=True),
        row("c", action="RUN_JUMP", jump_now=True),
        row("d", action="WAIT", dead=True),
    ]
    directory = bench_dir(tmp_path, "abcd")
    client = FakeClient({b"a": {}, b"b": {"jump_now": 0.9}, b"c": {"jump_now": 0.1}, b"d": {}})

    result = score(rows, decide_all("jev", V0, rows, client, directory))

    assert result.action_acc == pytest.approx(2 / 3)
    assert result.questions["jump_now"] == pytest.approx(0.75)
    assert result.questions["game_over"] == 1.0


def test_each_frame_gets_a_fresh_law_so_a_jump_hold_does_not_leak(tmp_path):
    rows = [row("a"), row("b")]
    directory = bench_dir(tmp_path, "ab")
    client = FakeClient({b"a": {"jump_now": 0.9}, b"b": {}})

    decisions = decide_all("jev", V0, rows, client, directory)

    assert [d.action for d in decisions] == ["RUN_JUMP", "RUN"]


@pytest.mark.parametrize(
    ("candidate", "passed", "worst"),
    [
        (Score(0.8, {"a": 0.9, "b": 0.84}), True, "b"),
        (Score(0.8, {"a": 0.9, "b": 0.80}), False, "b"),
        (Score(0.79, {"a": 0.9, "b": 0.85}), False, "b"),
        (Score(0.9, {"a": 0.95, "b": 0.86}), True, "b"),
    ],
    ids=["small drop", "drop over 0.05", "action regresses", "all better"],
)
def test_gate_needs_action_accuracy_and_no_big_question_drop(candidate, passed, worst):
    champion = Score(0.8, {"a": 0.9, "b": 0.86})
    result = gate(candidate, champion)
    assert result.passed is passed
    assert result.worst_question == worst


def test_gate_ignores_questions_only_one_side_asks_or_cannot_score():
    candidate = Score(0.8, {"a": 0.9, "new": 0.1, "empty": None})
    champion = Score(0.8, {"a": 0.9, "old": 0.9, "empty": 0.5})
    assert gate(candidate, champion).passed is True


def test_cache_answers_a_repeat_from_disk_without_calling_or_building_the_api(tmp_path):
    inner = FakeClient({b"img": {"jump_now": 0.9}})
    first = CachingClient("jev", lambda: inner, tmp_path)
    questions = {"jump_now": {"type": "noul", "instructions": "q"}}

    answers = first.ask(b"img", questions)
    first.ask(b"img", questions)

    assert answers["jump_now"]["noul"] == 0.9
    assert (inner.calls, first.hits, first.misses) == (1, 1, 1)

    def no_api():
        raise AssertionError("cache should have answered")

    again = CachingClient("jev", no_api, tmp_path)
    assert again.ask(b"img", questions) == answers
    assert CachingClient("clef-omni", lambda: inner, tmp_path).ask(b"img", questions) == answers
    assert inner.calls == 2
