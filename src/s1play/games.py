from collections.abc import Mapping
from dataclasses import dataclass, field

from s1play.controller import ControlState

WAIT = ControlState()


@dataclass(frozen=True)
class GameProfile:
    name: str
    question: str
    actions: Mapping[str, ControlState]
    descriptions: Mapping[str, str]
    questions: Mapping[str, str] = field(default_factory=dict)


MARIO = GameProfile(
    name="mario",
    question=(
        "This is a frame of Super Mario Bros. Pick the next input that makes progress "
        "to the right while avoiding enemies and pits."
    ),
    actions={
        "RUN": ControlState(hat="RIGHT", buttons=("B",)),
        "RUN_JUMP": ControlState(hat="RIGHT", buttons=("A", "B")),
        "WALK": ControlState(hat="RIGHT"),
        "WALK_JUMP": ControlState(hat="RIGHT", buttons=("A",)),
        "WAIT": WAIT,
    },
    descriptions={
        "RUN": "Run right. Use when the path ahead is clear.",
        "RUN_JUMP": "Running jump to the right. Use to clear a gap, pipe or enemy.",
        "WALK": "Walk right slowly. Use when close to an enemy and about to react.",
        "WALK_JUMP": "Short jump while walking right. Use to hop a close enemy.",
        "WAIT": "Do nothing. Use on transition screens or when waiting is safest.",
    },
)

DKC = GameProfile(
    name="dkc",
    question=(
        "This is a frame of Donkey Kong Country. Pick the next input that makes progress "
        "to the right while avoiding enemies, barrels and pits."
    ),
    actions={
        "RUN": ControlState(hat="RIGHT", buttons=("Y",)),
        "RUN_JUMP": ControlState(hat="RIGHT", buttons=("B", "Y")),
        "WALK": ControlState(hat="RIGHT"),
        "WALK_JUMP": ControlState(hat="RIGHT", buttons=("B",)),
        "WAIT": WAIT,
    },
    descriptions={
        "RUN": "Run right. Use when the path ahead is clear.",
        "RUN_JUMP": "Running jump to the right. Use to clear a gap or an enemy.",
        "WALK": "Walk right slowly. Use when close to an enemy and about to react.",
        "WALK_JUMP": "Short jump while walking right. Use to bounce on a close enemy.",
        "WAIT": "Do nothing. Use on transition screens or when waiting is safest.",
    },
)

GAMES: Mapping[str, GameProfile] = {g.name: g for g in (MARIO, DKC)}
