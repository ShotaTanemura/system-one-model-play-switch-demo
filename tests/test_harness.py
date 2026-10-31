from pathlib import Path

import httpx
import pytest
from test_s1play import CHOICE_BODY, client_with

from s1play.games import MARIO
from s1play.harness import load
from s1play.law import LAWS, LawConfig, RunnerLaw
from s1play.policy import ChoicePolicy, choice_questions, noul_questions

ROOT = Path(__file__).parent.parent / "harnesses"
MODELS = ["jev", "clef-omni"]


@pytest.mark.parametrize("model", MODELS)
def test_v0_asks_exactly_the_questions_the_law_reads(model):
    profile = load(ROOT / model / "v0.toml").profile(MARIO)
    assert set(noul_questions(profile)) == {
        "jump_now",
        "enemy_ahead",
        "gap_ahead",
        "tall_obstacle_ahead",
        "airborne",
        "transition",
        "game_over",
        "title_screen",
        "level_clear",
    }
    assert noul_questions(profile)["game_over"]["instructions"] == "Does the screen say GAME OVER?"


def test_v0_law_acts_like_the_default_law_on_a_fixed_sequence():
    harness = load(ROOT / "jev" / "v0.toml")
    from_toml = LAWS[harness.law](harness.law_params)
    default = RunnerLaw(LawConfig())
    base = {q: 0.05 for q in harness.questions}
    sequence = [
        base,
        base | {"jump_now": 0.9},
        base | {"airborne": 0.9},
        base | {"jump_now": 0.9, "gap_ahead": 0.8},
        base,
        base,
        base | {"game_over": 0.9},
    ]
    got = [from_toml.step(p) for p in sequence]
    assert got == ["RUN", "RUN_JUMP", "RUN_JUMP", "RUN", "RUN", "RUN", "WAIT"]
    assert got == [default.step(p) for p in sequence]


def test_choice_harness_swaps_the_menu_text_and_keeps_the_screen_questions():
    profile = load(ROOT / "jev" / "v0-choice.toml").profile(MARIO)
    assert choice_questions(profile)["action"]["instructions"].startswith("This is a frame of")
    assert set(profile.questions) == {"transition", "game_over", "title_screen"}


def test_choice_policy_returns_screen_probabilities_next_to_action_scores(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    profile = load(ROOT / "jev" / "v0-choice.toml").profile(MARIO)
    body = {
        "answers": CHOICE_BODY["answers"]
        | {q: {"type": "noul", "noul": 0.1} for q in profile.questions}
        | {"game_over": {"type": "noul", "noul": 0.9}}
    }

    decision = ChoicePolicy(client_with(lambda r: httpx.Response(200, json=body))).decide(
        b"img", profile
    )

    assert decision.action == "RUN_JUMP"
    assert decision.scores == {
        "RUN_JUMP": 0.7,
        "RUN": 0.3,
        "transition": 0.1,
        "game_over": 0.9,
        "title_screen": 0.1,
    }


def test_unknown_law_is_rejected_at_load(tmp_path):
    bad = tmp_path / "v9.toml"
    bad.write_text('kind = "questions"\nlaw = "nope"\nhypothesis = "x"\n')
    with pytest.raises(ValueError, match="nope"):
        load(bad)


def test_choice_harness_must_list_exactly_the_game_actions(tmp_path):
    bad = tmp_path / "v9.toml"
    bad.write_text(
        'kind = "choice"\nhypothesis = "x"\nchoice_question = "q"\n[actions]\nRUN = "r"\n'
    )
    with pytest.raises(ValueError, match="actions must be exactly"):
        load(bad).profile(MARIO)
