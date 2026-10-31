import base64
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from s1play.frames import Frame
from s1play.games import GameProfile
from s1play.law import RunnerLaw

QUESTION_ID = "action"
FRAME_REF = "frame-9c1e"
Questions = dict[str, dict[str, object]]


@dataclass(frozen=True)
class Decision:
    action: str
    scores: Mapping[str, float]
    latency_ms: float


class Policy(Protocol):
    def decide(self, frame: Frame, profile: GameProfile) -> Decision: ...


class RandomPolicy:
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def decide(self, frame: Frame, profile: GameProfile) -> Decision:
        action = self._rng.choice(list(profile.actions))
        return Decision(action, {action: 1.0}, 0.0)


def choice_questions(profile: GameProfile) -> Questions:
    return {
        QUESTION_ID: {
            "type": "choice",
            "instructions": profile.question,
            "criteria": dict(profile.descriptions),
        }
    }


def noul_questions(profile: GameProfile) -> Questions:
    if not profile.questions:
        raise ValueError(f"{profile.name} has no yes/no question set")
    return {qid: {"type": "noul", "instructions": text} for qid, text in profile.questions.items()}


def build_request(model: str, frame: Frame, questions: Questions) -> dict:
    image = "data:image/jpeg;base64," + base64.b64encode(frame).decode()
    return {
        "model": model,
        "state": "Current game frame.",
        "images": [image],
        "questions": questions,
    }


def build_jev_request(model: str, frame: Frame, questions: Questions) -> dict:
    referenced = {
        qid: {**q, "instructions": f"{q['instructions']} The frame is `game_frame` in the state."}
        for qid, q in questions.items()
    }
    return {
        "model": model,
        "state": {"game_frame": FRAME_REF},
        "assets": {
            FRAME_REF: {
                "type": "image",
                "data_base64": base64.b64encode(frame).decode(),
                "format": "jpeg",
            }
        },
        "questions": referenced,
    }


class SystemOneClient:
    def __init__(
        self,
        backend: Literal["jev", "clef-omni"],
        http: httpx.Client | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        if backend == "jev":
            self._url = "https://api.typesafe.ai/v1/systemone"
            self._key = os.environ["TYPESAFE_API_KEY"]
            self._model = "jev-latest"
            self._build = build_jev_request
            self._headers = {"TypeSafe-Danger-Zone-Images": "true"}
        else:
            account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
            self._url = (
                f"https://api.cloudflare.com/client/v4/accounts/{account}"
                "/ai/run/@cf/cloudflare/clef-omni"
            )
            self._key = os.environ["CLOUDFLARE_API_TOKEN"]
            self._model = "clef-omni"
            self._build = build_request
            self._headers = {}
        self._http = http or httpx.Client(timeout=timeout_s)

    def ask(self, frame: Frame, questions: Questions) -> dict:
        resp = self._http.post(
            self._url,
            headers={"Authorization": f"Bearer {self._key}", **self._headers},
            json=self._build(self._model, frame, questions),
        )
        if resp.is_error:
            raise RuntimeError(f"{self._url} returned {resp.status_code}: {resp.text[:500]}")
        body = resp.json()
        body = body.get("result", body)  # Cloudflare's REST API wraps model output in `result`
        return body["answers"]


class ChoicePolicy:
    def __init__(self, client: SystemOneClient) -> None:
        self._client = client

    def decide(self, frame: Frame, profile: GameProfile) -> Decision:
        start = time.perf_counter()
        questions = choice_questions(profile)
        if profile.questions:
            questions |= noul_questions(profile)
        answers = self._client.ask(frame, questions)
        ms = (time.perf_counter() - start) * 1000
        answer = answers[QUESTION_ID]
        screens = {qid: float(a["noul"]) for qid, a in answers.items() if qid != QUESTION_ID}
        return Decision(answer["choice"], {**answer["probabilities"], **screens}, ms)


class QuestionsPolicy:
    def __init__(self, client: SystemOneClient, law: RunnerLaw) -> None:
        self._client = client
        self._law = law

    def decide(self, frame: Frame, profile: GameProfile) -> Decision:
        start = time.perf_counter()
        answers = self._client.ask(frame, noul_questions(profile))
        ms = (time.perf_counter() - start) * 1000
        probs = {qid: float(a["noul"]) for qid, a in answers.items()}
        return Decision(self._law.step(probs), probs, ms)
