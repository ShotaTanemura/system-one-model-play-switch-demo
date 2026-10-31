import json
import time
from dataclasses import dataclass
from typing import Protocol

import zenoh

COMMANDS_KEY = "switch-controller/commands"
STATE_KEY = "switch-controller/state"
PING_KEY = "switch-controller/ping"
MAX_COMMANDS = 64
MAX_MS = 10_000
SLACK_S = 5.0
STATE_TIMEOUT_S = 2.0
FORBIDDEN_BUTTONS = {"HOME", "CAPTURE"}

Command = dict[str, object]


class ControllerError(Exception):
    pass


@dataclass(frozen=True)
class ControlState:
    buttons: tuple[str, ...] = ()
    hat: str | None = None
    lx: int = 0
    ly: int = 0
    rx: int = 0
    ry: int = 0

    def payload(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.buttons:
            out["buttons"] = list(self.buttons)
        if self.hat:
            out["hat"] = self.hat
        for name in ("lx", "ly", "rx", "ry"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        return out


NEUTRAL = ControlState()


class Controller(Protocol):
    def send(self, commands: list[Command]) -> int: ...

    def set_state(self, state: ControlState) -> None: ...


def _check_buttons(buttons: object, where: str) -> None:
    if buttons and set(buttons) & FORBIDDEN_BUTTONS:  # type: ignore[arg-type]
        raise ControllerError(f"{where}: HOME and CAPTURE are not allowed")


def _check_sticks(values: dict[str, object], where: str) -> None:
    for field in ("lx", "ly", "rx", "ry"):
        v = values.get(field, 0)
        if not isinstance(v, int) or not -100 <= v <= 100:
            raise ControllerError(f"{where}: {field} must be -100..100")


def validate(commands: list[Command]) -> None:
    if not 1 <= len(commands) <= MAX_COMMANDS:
        raise ControllerError(f"need 1..{MAX_COMMANDS} commands, got {len(commands)}")
    for i, c in enumerate(commands):
        for field in ("hold_ms", "wait_ms"):
            v = c.get(field, 0)
            if not isinstance(v, int) or not 0 <= v <= MAX_MS:
                raise ControllerError(f"command {i}: {field} must be 0..{MAX_MS}")
        _check_sticks(c, f"command {i}")
        _check_buttons(c.get("buttons"), f"command {i}")


def validate_state(state: ControlState) -> None:
    _check_sticks(state.payload(), "state")
    _check_buttons(state.buttons, "state")


def macro_duration_s(commands: list[Command]) -> float:
    return sum(int(c["hold_ms"]) + int(c.get("wait_ms", 0)) for c in commands) / 1000


class ZenohController:
    def __init__(self, listen: str = "tcp/0.0.0.0:7447") -> None:
        config = zenoh.Config.from_json5(
            json.dumps({"mode": "peer", "listen": {"endpoints": [listen]}})
        )
        self._session = zenoh.open(config)

    def ping(self, timeout_s: float = 5.0) -> bool:
        for reply in self._session.get(PING_KEY, timeout=timeout_s):
            if reply.ok is not None:
                return reply.ok.payload.to_string() == "pong"
        return False

    def wait_for_device(self, timeout_s: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.ping(timeout_s=2.0):
                return
        raise ControllerError("ESP32 did not answer ping; is ZENOH_CONNECT pointing at this host?")

    def send(self, commands: list[Command]) -> int:
        validate(commands)
        timeout = macro_duration_s(commands) + SLACK_S
        payload = json.dumps({"commands": commands})
        for reply in self._session.get(COMMANDS_KEY, payload=payload, timeout=timeout):
            if reply.ok is not None:
                return json.loads(reply.ok.payload.to_string())["executed"]
            raise ControllerError(reply.err.payload.to_string())
        raise ControllerError("no reply from controller")

    def set_state(self, state: ControlState) -> None:
        validate_state(state)
        payload = json.dumps(state.payload())
        for reply in self._session.get(STATE_KEY, payload=payload, timeout=STATE_TIMEOUT_S):
            if reply.ok is not None:
                return
            raise ControllerError(reply.err.payload.to_string())
        raise ControllerError("no reply from controller")

    def close(self) -> None:
        self._session.close()
