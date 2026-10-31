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


MARIO_QUESTIONS = {
    "jump_now": (
        "Should Mario press the jump button right now? Answer yes if Mario stands on the ground "
        "and an enemy (a brown Goomba or a Koopa), a pit, or a pipe or block wall is within about "
        "3 character-widths ahead of him."
    ),
    "enemy_ahead": (
        "Is there an enemy (a brown Goomba or a green Koopa) within about 4 character-widths "
        "in front of Mario?"
    ),
    "gap_ahead": (
        "Is there a gap (a pit with no ground) within about 4 character-widths in front of Mario?"
    ),
    "tall_obstacle_ahead": (
        "Is there a green pipe or a tall stack of blocks within about 3 character-widths "
        "in front of Mario?"
    ),
    "airborne": "Is Mario currently in the air, not standing on the ground or a block?",
    "transition": (
        "Is this a black transition screen, such as the level intro with a lives count or "
        "the death screen, instead of gameplay?"
    ),
    "game_over": "Does the screen say GAME OVER?",
    "title_screen": (
        "Is this the Super Mario Bros. title screen with the big logo and the 1 PLAYER GAME menu?"
    ),
    "level_clear": (
        "Is Mario at the flagpole or inside the castle at the end of the level, "
        "or is a level-complete sequence showing?"
    ),
}

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
    questions=MARIO_QUESTIONS,
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
