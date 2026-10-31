import time
from collections.abc import Mapping

import numpy as np

from s1play.controller import NEUTRAL, Controller
from s1play.frames import FrameSource
from s1play.games import GameProfile
from s1play.policy import Policy
from s1play.progress import ScrollTracker, hud_changed, hud_mask, is_transition, time_visible

GAME_OVER_FRAMES = 3
CLEAR_FRAMES = 2
START_ATTEMPTS = 4
TITLE_WAIT_S = 30.0
GAMEPLAY_WAIT_S = 8.0
SCREEN_THRESHOLD = 0.5
START_PRESS = [{"buttons": ["PLUS"], "hold_ms": 250}]


class RestartError(Exception):
    pass


class EpisodeManager:
    """Follows lives, scroll progress, game over and level clear, and restarts finished games.

    An attempt is one game of three lives. A life ends whenever the screen goes black after
    gameplay, so progress is tracked per life.
    """

    def __init__(self) -> None:
        self.attempt = 1
        self.life = 0
        self.best_progress = 0.0
        self.cleared = False
        self._scroll = ScrollTracker()
        self._hud_template: np.ndarray | None = None
        self._over_streak = 0
        self._title_streak = 0
        self._clear_streak = 0
        self._playing = False
        self._game_seen = False

    @property
    def progress(self) -> float:
        return self._scroll.total

    def observe(self, frame: bytes, scores: Mapping[str, float]) -> bool:
        """Feeds one frame and its screen probabilities.

        Returns True when no game is running: after game over, or when the title screen
        stays up. The caller then calls restart().
        """
        game_over = scores.get("game_over", 0.0) > SCREEN_THRESHOLD
        title = scores.get("title_screen", 0.0) > SCREEN_THRESHOLD
        self._over_streak = self._over_streak + 1 if game_over else 0
        self._title_streak = self._title_streak + 1 if title else 0

        if self._hud_template is not None and hud_changed(self._hud_template, frame):
            self._clear_streak += 1
            if self._clear_streak >= CLEAR_FRAMES:
                self.cleared = True
        else:
            self._clear_streak = 0

        if is_transition(frame):
            if self._playing:
                self.life += 1
            self._playing = False
            self.best_progress = max(self.best_progress, self._scroll.total)
            self._scroll.reset()
        # The title screen's attract demo plays 1-1 without a TIME counter. It is not a game.
        elif not game_over and not title and time_visible(frame):
            self._playing = True
            self._game_seen = True
            if self._hud_template is None:
                self._hud_template = hud_mask(frame)
            self._scroll.update(frame)
        return max(self._over_streak, self._title_streak) >= GAME_OVER_FRAMES

    def restart(
        self,
        frames: FrameSource,
        policy: Policy,
        controller: Controller,
        profile: GameProfile,
    ) -> None:
        controller.set_state(NEUTRAL)
        deadline = time.monotonic() + TITLE_WAIT_S
        while True:
            if time.monotonic() > deadline:
                raise RestartError("title screen did not appear after game over")
            if policy.decide(frames.grab(), profile).scores.get("title_screen", 0.0) > 0.5:
                break
        for _ in range(START_ATTEMPTS):
            controller.send(START_PRESS)
            if self._gameplay_started(frames):
                break
        else:
            raise RestartError("START did not begin a new game")
        if self._game_seen:
            self.attempt += 1
        self._game_seen = False
        self.life = 0
        self._over_streak = 0
        self._title_streak = 0
        self._playing = False
        self._scroll.reset()

    @staticmethod
    def _gameplay_started(frames: FrameSource) -> bool:
        # Not a black screen: the title's attract demo also goes black, but only a real game
        # shows the TIME counter. The first START press is often lost, hence the retries.
        deadline = time.monotonic() + GAMEPLAY_WAIT_S
        while time.monotonic() < deadline:
            if time_visible(frames.grab()):
                return True
            time.sleep(0.1)
        return False
