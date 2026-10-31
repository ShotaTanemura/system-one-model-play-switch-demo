import io
import random

from PIL import Image, ImageDraw

from s1play.progress import (
    ScrollTracker,
    hud_changed,
    hud_mask,
    is_transition,
    time_visible,
)

W, H = 640, 495


def jpeg(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def draw_timer(draw: ImageDraw.ImageDraw) -> None:
    x0, y0 = int(0.80 * W), int(0.07 * H)
    draw.rectangle([x0, y0, x0 + 40, y0 + 12], fill=(255, 255, 255))


def level_frame(offset_px: int, timer: bool = True) -> bytes:
    """Sky with fixed random landmarks; the camera has moved right by offset_px."""
    im = Image.new("RGB", (W, H), (136, 136, 255))
    draw = ImageDraw.Draw(im)
    if timer:
        draw_timer(draw)
    rng = random.Random(7)
    for _ in range(40):
        x, y = rng.randrange(0, 1400), rng.randrange(100, 360)
        draw.rectangle([x - offset_px, y, x - offset_px + 28, y + 24], fill=(60, 140, 40))
    return jpeg(im)


def test_scroll_of_two_tiles_is_measured_in_nes_pixels():
    tracker = ScrollTracker()
    tracker.update(level_frame(0))
    moved = tracker.update(level_frame(80))  # 80 px of 640 = 32 NES px
    assert abs(moved - 32) <= 2
    assert abs(tracker.total - 32) <= 2


def test_standing_still_scrolls_nothing():
    tracker = ScrollTracker()
    tracker.update(level_frame(40))
    assert tracker.update(level_frame(40)) == 0.0


def test_black_transition_frames_are_ignored_on_both_sides():
    black = jpeg(Image.new("RGB", (W, H), (0, 0, 0)))
    tracker = ScrollTracker()
    tracker.update(level_frame(0))
    assert [tracker.update(black), tracker.update(level_frame(200))] == [0.0, 0.0]
    assert is_transition(black) and not is_transition(level_frame(0))


def hud_frame(last_digit_columns: int, background=(136, 136, 255)) -> bytes:
    im = Image.new("RGB", (W, H), background)
    draw = ImageDraw.Draw(im)
    x0, y0 = int(0.60 * W), int(0.07 * H)
    draw.rectangle([x0, y0, x0 + 20, y0 + 12], fill=(255, 255, 255))
    draw.rectangle([x0 + 30, y0, x0 + 30 + last_digit_columns, y0 + 12], fill=(255, 255, 255))
    draw_timer(draw)
    return jpeg(im)


def test_hud_change_ignores_background_and_detects_a_new_digit():
    template = hud_mask(hud_frame(10))
    assert not hud_changed(template, hud_frame(10, background=(0, 0, 0)))
    assert hud_changed(template, hud_frame(26))


def time_frame(digits: bool = True) -> bytes:
    im = Image.new("RGB", (W, H), (136, 136, 255))
    if digits:
        draw_timer(ImageDraw.Draw(im))
    return jpeg(im)


def test_time_counter_tells_a_real_game_from_the_title_and_demo():
    assert time_visible(time_frame(True))
    assert not time_visible(time_frame(False))


def test_a_blank_screen_is_not_a_changed_world_number():
    template = hud_mask(hud_frame(10))
    blank = jpeg(Image.new("RGB", (W, H), (0, 0, 0)))
    assert not hud_changed(template, blank)
