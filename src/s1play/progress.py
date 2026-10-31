import io

import numpy as np
from PIL import Image

NES_WIDTH = 256
DARK = 40.0
DOWNSCALED_WIDTH = 160
# Widest scroll between two frames that still matches, in downscaled px. A model that takes
# seconds a step scrolls 80-90 NES px between frames, and a window of 40 (64 NES px) scored it 0.
MAX_SHIFT = 100
MIN_CORRELATION = 0.4
# Sky rows of a game-viewport frame, as fractions of its height. The ground bricks repeat
# every 16 NES pixels, so they cannot tell a 16 px scroll from none; clouds, hills, pipes
# and floating blocks can.
SKY_ROWS = (0.16, 0.78)
# "1-1" in the HUD, as fractions of a game-viewport frame.
HUD_WORLD_BOX = (0.59, 0.065, 0.69, 0.10)
# The TIME counter digits. Blank on the title screen and during the attract demo.
HUD_TIME_BOX = (0.78, 0.065, 0.91, 0.10)
TIME_VISIBLE_PIXELS = 60


def _gray(frame: bytes, width: int | None = None) -> np.ndarray:
    im = Image.open(io.BytesIO(frame)).convert("L")
    if width:
        im = im.resize((width, round(im.height * width / im.width)), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32)


def luminance(frame: bytes) -> float:
    return float(_gray(frame, 80).mean())


def is_transition(frame: bytes) -> bool:
    return luminance(frame) < DARK


def _sky_edges(gray: np.ndarray) -> np.ndarray:
    top, bottom = (round(gray.shape[0] * f) for f in SKY_ROWS)
    return np.abs(np.diff(gray[top:bottom], axis=1))


class ScrollTracker:
    """Sums how far the screen scrolled, in NES pixels, from consecutive game-viewport frames."""

    def __init__(self) -> None:
        self._prev: np.ndarray | None = None
        self._prev_dark = True
        self.total = 0.0

    def reset(self) -> None:
        self._prev = None
        self._prev_dark = True
        self.total = 0.0

    def update(self, frame: bytes) -> float:
        gray = _gray(frame, DOWNSCALED_WIDTH)
        dark = bool(gray.mean() < DARK)
        edges = _sky_edges(gray)
        prev, prev_dark = self._prev, self._prev_dark
        self._prev, self._prev_dark = edges, dark
        if prev is None or dark or prev_dark:
            return 0.0
        width = edges.shape[1]
        best_corr, best_shift = 0.0, 0
        for shift in range(MAX_SHIFT + 1):
            a, b = prev[:, shift:], edges[:, : width - shift]
            corr = float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))
            if corr > best_corr:
                best_corr, best_shift = corr, shift
        if best_corr < MIN_CORRELATION:
            return 0.0
        moved = best_shift * NES_WIDTH / DOWNSCALED_WIDTH
        self.total += moved
        return moved


def hud_mask(frame: bytes) -> np.ndarray:
    gray = _gray(frame)
    h, w = gray.shape
    left, top, right, bottom = HUD_WORLD_BOX
    return gray[round(top * h) : round(bottom * h), round(left * w) : round(right * w)] > 200


def hud_changed(template: np.ndarray, frame: bytes, threshold: float = 0.25) -> bool:
    mask = hud_mask(frame)
    if mask.shape != template.shape:
        return False
    # A black frame between screens has no HUD at all. That is not a new world number.
    if mask.sum() < template.sum() / 2:
        return False
    return (mask ^ template).sum() / max(1, template.sum()) > threshold


def time_visible(frame: bytes) -> bool:
    gray = _gray(frame)
    h, w = gray.shape
    left, top, right, bottom = HUD_TIME_BOX
    box = gray[round(top * h) : round(bottom * h), round(left * w) : round(right * w)]
    return int((box > 200).sum()) > TIME_VISIBLE_PIXELS
