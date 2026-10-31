import base64
import io
import os
from typing import Protocol

import obsws_python as obs
from PIL import Image

Frame = bytes

# Game viewport inside a 16:9 capture of the Switch: the NES picture sits between black
# pillars, and the bottom strip is the NSO hint bar. Fractions of width and height.
GAME_CROP = (0.15625, 0.0, 0.84375, 0.9444)


class FrameSource(Protocol):
    def grab(self) -> Frame: ...


def prepare(
    jpeg: bytes,
    crop: tuple[float, float, float, float] = GAME_CROP,
    out_width: int = 640,
    quality: int = 85,
) -> Frame:
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    w, h = im.size
    left, top, right, bottom = crop
    im = im.crop((round(left * w), round(top * h), round(right * w), round(bottom * h)))
    out_height = round(im.height * out_width / im.width)
    im = im.resize((out_width, out_height), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class ObsFrameSource:
    def __init__(
        self,
        source: str,
        capture: tuple[int, int] = (960, 540),
        crop: tuple[float, float, float, float] = GAME_CROP,
        out_width: int = 640,
    ) -> None:
        self._client = obs.ReqClient(
            host=os.environ.get("OBS_WS_HOST", "localhost"),
            port=int(os.environ.get("OBS_WS_PORT", "4455")),
            password=os.environ.get("OBS_WS_PASSWORD", ""),
        )
        self._source = source
        self._capture = capture
        self._crop = crop
        self._out_width = out_width

    def grab(self) -> Frame:
        w, h = self._capture
        resp = self._client.get_source_screenshot(self._source, "jpg", w, h, 80)
        raw = base64.b64decode(resp.image_data.split(",", 1)[1])
        return prepare(raw, self._crop, self._out_width)
