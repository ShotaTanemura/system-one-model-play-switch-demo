from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class LawConfig:
    threshold: float = 0.5
    base_hold_steps: int = 2
    long_hold_steps: int = 3


class RunnerLaw:
    """Turns yes/no probabilities into an action name for a side-scrolling runner.

    The default is RUN. A jump is held for a few steps because jump height grows
    with how long the button stays down, and it is never re-triggered in the air. A jump
    needs a fresh press, so after every jump the button is released for one step.
    """

    def __init__(self, config: LawConfig | None = None) -> None:
        self._cfg = config or LawConfig()
        self._jump_steps_left = 0
        self._a_held = False

    def step(self, p: Mapping[str, float]) -> str:
        t = self._cfg.threshold
        if p["transition"] > t or p["game_over"] > t or p["title_screen"] > t:
            self._jump_steps_left = 0
            self._a_held = False
            return "WAIT"
        if self._jump_steps_left > 0:
            self._jump_steps_left -= 1
            return "RUN_JUMP"
        if self._a_held:
            self._a_held = False
            return "RUN"
        if p["airborne"] > t:
            return "RUN"
        if p["jump_now"] > t:
            long_jump = p["gap_ahead"] > t or p["tall_obstacle_ahead"] > t
            hold = self._cfg.long_hold_steps if long_jump else self._cfg.base_hold_steps
            self._jump_steps_left = hold - 1
            self._a_held = True
            return "RUN_JUMP"
        return "RUN"
