import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from s1play.controller import (
    NEUTRAL,
    ControllerError,
    ControlState,
    validate,
    validate_state,
)
from s1play.frames import prepare
from s1play.games import GAMES, MARIO
from s1play.harness import load
from s1play.law import LawConfig, RunnerLaw
from s1play.loop import run
from s1play.policy import (
    ChoicePolicy,
    Decision,
    QuestionsPolicy,
    RandomPolicy,
    SystemOneClient,
    build_jev_request,
    build_request,
    choice_questions,
    noul_questions,
)

HARNESS_DIR = Path(__file__).parent.parent / "harnesses" / "jev"
MARIO_Q = load(HARNESS_DIR / "v0.toml").profile(MARIO)


@pytest.mark.parametrize("profile", list(GAMES.values()), ids=list(GAMES))
def test_every_action_is_a_valid_held_state(profile):
    assert set(profile.actions) == set(profile.descriptions)
    assert {"RUN", "RUN_JUMP", "WAIT"} <= set(profile.actions)
    for state in profile.actions.values():
        validate_state(state)


def test_state_payload_is_the_firmware_json():
    assert MARIO.actions["RUN_JUMP"].payload() == {"buttons": ["A", "B"], "hat": "RIGHT"}
    assert NEUTRAL.payload() == {}
    assert ControlState(lx=-50).payload() == {"lx": -50}


@pytest.mark.parametrize(
    "command",
    [
        {"hold_ms": 10_001},
        {"hold_ms": 100, "lx": 101},
        {"hold_ms": 100, "buttons": ["A", "HOME"]},
        {"hold_ms": 100, "buttons": ["CAPTURE"]},
    ],
)
def test_validate_rejects_what_firmware_would_reject_or_we_forbid(command):
    with pytest.raises(ControllerError):
        validate([command])


@pytest.mark.parametrize(
    "state",
    [
        ControlState(buttons=("HOME",)),
        ControlState(buttons=("A", "CAPTURE")),
        ControlState(ry=-101),
    ],
)
def test_validate_state_rejects_forbidden_buttons_and_bad_sticks(state):
    with pytest.raises(ControllerError):
        validate_state(state)


def test_clef_request_body_for_choice_question():
    body = build_request("clef-omni", b"\xff\xd8jpeg", choice_questions(MARIO))
    q = body["questions"]["action"]
    assert body["model"] == "clef-omni"
    assert body["images"] == ["data:image/jpeg;base64,/9hqcGVn"]
    assert q["type"] == "choice"
    assert q["criteria"]["WAIT"] == MARIO.descriptions["WAIT"]


def test_jev_request_references_the_frame_in_every_question():
    body = build_jev_request("jev-latest", b"img", noul_questions(MARIO_Q))
    assert body["state"] == {"game_frame": "frame-9c1e"}
    assert body["assets"] == {
        "frame-9c1e": {"type": "image", "data_base64": "aW1n", "format": "jpeg"}
    }
    assert "images" not in body
    assert all("`game_frame`" in q["instructions"] for q in body["questions"].values())


def test_noul_questions_cover_what_the_law_reads():
    assert set(noul_questions(MARIO_Q)) == {
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
    with pytest.raises(ValueError):
        noul_questions(GAMES["dkc"])


CHOICE_BODY = {
    "model": "jev-1.13.0",
    "answers": {
        "action": {
            "type": "choice",
            "choice": "RUN_JUMP",
            "probabilities": {"RUN_JUMP": 0.7, "RUN": 0.3},
            "confidence": 0.8,
        }
    },
    "usage": {"input_tokens": 10, "output_tokens": 1},
}


def client_with(handler, backend="jev"):
    return SystemOneClient(backend, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_choice_policy_over_jev_sends_bearer_and_header(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["images_header"] = request.headers["typesafe-danger-zone-images"]
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json=CHOICE_BODY)

    decision = ChoicePolicy(client_with(handler)).decide(b"img", MARIO)

    assert seen == {
        "url": "https://api.typesafe.ai/v1/systemone",
        "auth": "Bearer test-key",
        "images_header": "true",
        "model": "jev-latest",
    }
    assert decision.action == "RUN_JUMP"
    assert decision.scores["RUN"] == 0.3


def noul_body(**probs):
    base = {qid: 0.05 for qid in MARIO_Q.questions}
    base.update(probs)
    return {"answers": {qid: {"type": "noul", "noul": p} for qid, p in base.items()}}


def test_questions_policy_unwraps_cloudflare_result_and_applies_the_law(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/accounts/acct/ai/run/@cf/cloudflare/clef-omni" in str(request.url)
        return httpx.Response(200, json={"result": noul_body(jump_now=0.9), "success": True})

    policy = QuestionsPolicy(client_with(handler, "clef-omni"), RunnerLaw())
    decision = policy.decide(b"img", MARIO_Q)

    assert decision.action == "RUN_JUMP"
    assert decision.scores["jump_now"] == 0.9


def test_http_error_message_includes_server_response(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error":"asset frame-9c1e is not referenced"}')

    with pytest.raises(RuntimeError, match="400: .*not referenced"):
        ChoicePolicy(client_with(handler)).decide(b"img", MARIO)


def p(**overrides):
    base = {qid: 0.05 for qid in MARIO_Q.questions}
    base.update(overrides)
    return base


def test_law_runs_by_default_and_jumps_once_without_retriggering_in_the_air():
    law = RunnerLaw(LawConfig(base_hold_steps=1, long_hold_steps=2))
    assert [
        law.step(p()),
        law.step(p(jump_now=0.9)),
        law.step(p(jump_now=0.9, airborne=0.9)),
        law.step(p(airborne=0.9)),
        law.step(p()),
    ] == ["RUN", "RUN_JUMP", "RUN", "RUN", "RUN"]


def test_law_holds_a_longer_jump_for_gaps_and_tall_obstacles():
    law = RunnerLaw(LawConfig(base_hold_steps=1, long_hold_steps=2))
    assert [law.step(p(jump_now=0.9, gap_ahead=0.8)), law.step(p()), law.step(p())] == [
        "RUN_JUMP",
        "RUN_JUMP",
        "RUN",
    ]


def test_law_releases_the_jump_button_for_a_step_between_jumps():
    law = RunnerLaw(LawConfig(base_hold_steps=1, long_hold_steps=2))
    jump = p(jump_now=0.9)
    assert [law.step(jump), law.step(jump), law.step(jump), law.step(jump)] == [
        "RUN_JUMP",
        "RUN",
        "RUN_JUMP",
        "RUN",
    ]


def test_default_law_holds_a_jump_for_two_steps_and_a_long_one_for_three():
    law = RunnerLaw()
    plain = [law.step(p(jump_now=0.9)), law.step(p(airborne=0.9)), law.step(p(airborne=0.9))]
    law = RunnerLaw()
    long = [law.step(p(jump_now=0.9, gap_ahead=0.8)), law.step(p()), law.step(p()), law.step(p())]
    assert plain == ["RUN_JUMP", "RUN_JUMP", "RUN"]
    assert long == ["RUN_JUMP", "RUN_JUMP", "RUN_JUMP", "RUN"]


@pytest.mark.parametrize("screen", ["transition", "game_over", "title_screen"])
def test_law_waits_on_non_gameplay_screens_and_cancels_a_jump(screen):
    law = RunnerLaw()
    law.step(p(jump_now=0.9, gap_ahead=0.8))
    assert law.step(p(**{screen: 0.9})) == "WAIT"
    assert law.step(p()) == "RUN"


def test_prepare_crops_pillars_and_scales_to_the_requested_width():
    src = Image.new("RGB", (1280, 720), (255, 0, 0))
    src.paste(Image.new("RGB", (880, 680), (0, 0, 255)), (200, 0))
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=95)

    out = Image.open(io.BytesIO(prepare(buf.getvalue(), out_width=640)))

    assert out.size == (640, 495)
    r, _, b = out.getpixel((2, 2))
    assert b > 200 and r < 60
    r, _, b = out.getpixel((637, 492))
    assert b > 200 and r < 60


class FakeFrames:
    def grab(self):
        return b"jpeg"


class FakeController:
    def __init__(self):
        self.states = []

    def send(self, commands):
        return len(commands)

    def set_state(self, state):
        self.states.append(state)


class FixedPolicy:
    def decide(self, frame, profile):
        return Decision("RUN_JUMP", {"RUN_JUMP": 0.9}, 12.0)


def test_loop_holds_the_action_state_logs_each_step_and_ends_neutral(tmp_path):
    controller = FakeController()
    steps = run(FakeFrames(), FixedPolicy(), controller, MARIO, tmp_path, max_steps=2)

    assert steps == 2
    assert controller.states == [MARIO.actions["RUN_JUMP"]] * 2 + [NEUTRAL]
    rows = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert [r["action"] for r in rows] == ["RUN_JUMP", "RUN_JUMP"]
    assert rows[1]["frame"] == "frames/000001.jpg"
    assert (tmp_path / rows[1]["frame"]).read_bytes() == b"jpeg"


def test_loop_releases_all_buttons_when_the_policy_fails(tmp_path):
    class Boom:
        def decide(self, frame, profile):
            raise RuntimeError("api down")

    controller = FakeController()
    with pytest.raises(RuntimeError):
        run(FakeFrames(), Boom(), controller, MARIO, tmp_path, max_steps=1)
    assert controller.states == [NEUTRAL]


def test_dry_run_never_sets_state(tmp_path):
    run(FakeFrames(), RandomPolicy(seed=0), None, MARIO, tmp_path, max_steps=3)
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 3
