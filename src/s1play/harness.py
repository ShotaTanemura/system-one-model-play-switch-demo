import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from s1play.games import GameProfile
from s1play.law import LAWS
from s1play.policy import ChoicePolicy, Policy, QuestionsPolicy, SystemOneClient


@dataclass(frozen=True)
class Harness:
    """Everything between the model and the controller that a PDCA iteration may change."""

    name: str
    kind: Literal["questions", "choice"]
    hypothesis: str
    questions: Mapping[str, str]
    parent: str = ""
    law: str = ""
    law_params: Mapping[str, float] = field(default_factory=dict)
    choice_question: str = ""
    actions: Mapping[str, str] = field(default_factory=dict)

    def profile(self, base: GameProfile) -> GameProfile:
        if self.kind == "questions":
            return replace(base, questions=self.questions)
        if set(self.actions) != set(base.actions):
            raise ValueError(f"{self.name}: actions must be exactly {sorted(base.actions)}")
        return replace(
            base,
            question=self.choice_question,
            descriptions=self.actions,
            questions=self.questions,
        )


def load(path: Path) -> Harness:
    raw = tomllib.loads(path.read_text())
    harness = Harness(
        name=path.stem,
        kind=raw["kind"],
        hypothesis=raw["hypothesis"],
        questions=raw.get("questions", {}),
        parent=raw.get("parent", ""),
        law=raw.get("law", ""),
        law_params=raw.get("law_params", {}),
        choice_question=raw.get("choice_question", ""),
        actions=raw.get("actions", {}),
    )
    if harness.kind == "questions" and harness.law not in LAWS:
        raise ValueError(f"{path}: law {harness.law!r} is not one of {sorted(LAWS)}")
    return harness


def build_policy(backend: Literal["jev", "clef-omni"], harness: Harness) -> Policy:
    client = SystemOneClient(backend)
    if harness.kind == "choice":
        return ChoicePolicy(client)
    return QuestionsPolicy(client, LAWS[harness.law](harness.law_params))
