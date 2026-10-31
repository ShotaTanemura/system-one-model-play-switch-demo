import io

import pytest
from PIL import Image
from test_progress import hud_frame, level_frame, time_frame

from s1play.controller import NEUTRAL
from s1play.episode import EpisodeManager, RestartError
from s1play.games import MARIO
from s1play.policy import Decision

BLACK = io.BytesIO()
Image.new("RGB", (640, 495), (0, 0, 0)).save(BLACK, "JPEG")
BLACK = BLACK.getvalue()
PLAYING = {"game_over": 0.05, "title_screen": 0.05}


def test_game_over_is_reported_after_three_consecutive_frames():
    episodes = EpisodeManager()
    over = {"game_over": 0.9, "title_screen": 0.05}
    assert [episodes.observe(BLACK, over) for _ in range(3)] == [False, False, True]
    episodes.observe(level_frame(0), PLAYING)
    assert episodes.observe(BLACK, over) is False


def test_a_title_screen_that_stays_up_asks_for_a_start_without_counting_an_attempt():
    episodes = EpisodeManager()
    title = {"game_over": 0.05, "title_screen": 0.9}
    assert [episodes.observe(level_frame(0), title) for _ in range(3)] == [False, False, True]

    controller = RecordingController()
    frames = ScriptedFrames(level_frame(0), time_frame())
    episodes.restart(frames, TitlePolicy(0.9), controller, MARIO)
    assert episodes.attempt == 1


def test_the_title_attract_demo_is_not_a_game_so_the_first_real_game_is_attempt_one():
    episodes = EpisodeManager()
    demo = {"game_over": 0.0, "title_screen": 0.01}
    for offset in (0, 80, 160):
        episodes.observe(level_frame(offset, timer=False), demo)
    assert episodes.progress == 0.0

    title = {"game_over": 0.05, "title_screen": 0.95}
    assert [episodes.observe(level_frame(0), title) for _ in range(3)] == [False, False, True]
    episodes.restart(ScriptedFrames(time_frame()), TitlePolicy(0.9), RecordingController(), MARIO)
    assert episodes.attempt == 1


def test_each_life_ends_at_a_black_screen_and_best_progress_is_kept():
    episodes = EpisodeManager()
    episodes.observe(BLACK, PLAYING)  # level intro, not a life
    episodes.observe(level_frame(0), PLAYING)
    episodes.observe(level_frame(80), PLAYING)
    assert episodes.life == 0 and abs(episodes.progress - 32) <= 2

    episodes.observe(BLACK, PLAYING)  # death
    assert episodes.life == 1
    assert episodes.progress == 0.0
    assert abs(episodes.best_progress - 32) <= 2


def test_level_clear_needs_the_world_digit_to_change_twice_in_a_row():
    episodes = EpisodeManager()
    episodes.observe(hud_frame(10), PLAYING)
    episodes.observe(hud_frame(26), PLAYING)
    assert not episodes.cleared
    episodes.observe(hud_frame(10), PLAYING)
    episodes.observe(hud_frame(26), PLAYING)
    assert not episodes.cleared
    episodes.observe(hud_frame(26), PLAYING)
    assert episodes.cleared


class ScriptedFrames:
    def __init__(self, *frames):
        self._frames = list(frames)

    def grab(self):
        return self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]


class TitlePolicy:
    def __init__(self, title_probability):
        self._p = title_probability

    def decide(self, frame, profile):
        return Decision("WAIT", {"title_screen": self._p}, 0.0)


class RecordingController:
    def __init__(self):
        self.sent, self.states = [], []

    def send(self, commands):
        self.sent.append(commands)
        return len(commands)

    def set_state(self, state):
        self.states.append(state)


def test_restart_presses_plus_on_the_title_screen_and_starts_a_new_attempt():
    episodes = EpisodeManager()
    episodes.observe(level_frame(0), PLAYING)
    controller = RecordingController()
    episodes.restart(
        ScriptedFrames(level_frame(0), time_frame()), TitlePolicy(0.9), controller, MARIO
    )

    assert controller.states == [NEUTRAL]
    assert controller.sent == [[{"buttons": ["PLUS"], "hold_ms": 250}]]
    assert (episodes.attempt, episodes.life) == (2, 0)


def test_restart_retries_the_press_until_the_intro_screen_appears(monkeypatch):
    monkeypatch.setattr("s1play.episode.GAMEPLAY_WAIT_S", 0.2)
    episodes = EpisodeManager()
    controller = RecordingController()
    frames = ScriptedFrames(*([level_frame(0, timer=False)] * 4), time_frame())
    episodes.restart(frames, TitlePolicy(0.9), controller, MARIO)
    assert len(controller.sent) >= 2


def test_restart_gives_up_when_start_never_registers(monkeypatch):
    monkeypatch.setattr("s1play.episode.GAMEPLAY_WAIT_S", 0.1)
    controller = RecordingController()
    with pytest.raises(RestartError, match="START"):
        EpisodeManager().restart(
            ScriptedFrames(level_frame(0, timer=False)), TitlePolicy(0.9), controller, MARIO
        )
    assert len(controller.sent) == 4


class ScriptedPolicy:
    def __init__(self, *scores):
        self._scores = list(scores)

    def decide(self, frame, profile):
        return Decision("WAIT", self._scores.pop(0), 0.0)


def test_loop_restarts_after_game_over_then_stops_at_the_attempt_limit(tmp_path):
    from s1play.loop import run

    over = {"game_over": 0.9, "title_screen": 0.05}
    title = {"game_over": 0.05, "title_screen": 0.9}
    policy = ScriptedPolicy(PLAYING, over, over, over, title, over, over, over)
    controller = RecordingController()
    episodes = EpisodeManager()

    frames = ScriptedFrames(level_frame(0), BLACK, BLACK, BLACK, BLACK, time_frame())
    steps = run(frames, policy, controller, MARIO, tmp_path, None, episodes, max_attempts=2)

    assert steps == 7
    assert controller.sent == [[{"buttons": ["PLUS"], "hold_ms": 250}]]
    assert episodes.attempt == 2
    assert controller.states[-1] == NEUTRAL
