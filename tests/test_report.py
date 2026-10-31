import json

from PIL import Image

from s1play import ledger
from s1play.report import (
    MODEL_COLORS,
    Stall,
    contact_sheet,
    current_rows,
    markdown,
    progress_chart,
    read_games,
    stalls,
)


def ledger_row(**over):
    base = dict.fromkeys(ledger.COLUMNS, "")
    base |= {
        "id": "r",
        "model": "jev",
        "harness": "jev/v0",
        "role": "baseline",
        "hypothesis": "h",
        "attempts": "5",
        "attempt_px": "100.0,200.0,300.0,400.0,500.0",
        "mean_best_px": "300.0",
        "ci_lo": "200.0",
        "ci_hi": "400.0",
        "clears": "0",
        "decision": "champion",
    }
    return base | over


def log_row(step, attempt, life, progress):
    return {
        "step": step,
        "attempt": attempt,
        "life": life,
        "progress": progress,
        "frame": f"frames/{step:06d}.jpg",
    }


def test_a_later_row_for_the_same_model_harness_and_role_supersedes_an_earlier_one():
    rows = [
        ledger_row(id="a"),
        ledger_row(id="b"),
        ledger_row(id="c", harness="jev/v1", role="candidate"),
        ledger_row(id="d", model="clef-omni", harness="jev/v1", role="transfer"),
    ]
    assert [r["id"] for r in current_rows(rows)] == ["b", "c", "d"]


def test_stall_frames_end_where_progress_first_reaches_its_peak():
    progress = [[0, 10, 20, 30, 30, 30], [0, 5, 5], [0, 0]]
    log, step = [], 0
    for life, values in enumerate(progress):
        for px in values:
            log.append(log_row(step, 1, life, px))
            step += 1

    assert stalls(log) == [
        Stall(1, 0, ("frames/000001.jpg", "frames/000002.jpg", "frames/000003.jpg"), 30),
        Stall(1, 1, ("frames/000006.jpg", "frames/000007.jpg"), 5),
    ]


def write_run(run_dir, lives_per_attempt):
    """Frames are flat colors, so a sheet pixel says which frame it came from."""
    (run_dir / "frames").mkdir(parents=True)
    log, step = [], 0
    for attempt, lives in enumerate(lives_per_attempt, start=1):
        for life in range(lives):
            for px in (0, 40, 80):
                Image.new("RGB", (640, 495), (10, 200, 30)).save(run_dir / f"frames/{step:06d}.jpg")
                log.append(log_row(step, attempt, life, px))
                step += 1
    (run_dir / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in log))


def test_contact_sheet_has_a_block_per_life_with_the_frames_cropped_to_the_ground(tmp_path):
    write_run(tmp_path / "run", [2, 1])
    games = read_games(ledger_row(run_dirs=str(tmp_path / "run")))

    assert [g[0] for g in games] == ["game 1", "game 2"]
    sheet = contact_sheet("title", games)

    assert sheet.size == (3 * (3 * 200 + 12) + 90, 34 + 2 * (18 + 93 + 8))
    r, g, b = sheet.getpixel((90 + 5, 34 + 18 + 5))
    assert (abs(r - 10), abs(g - 200), abs(b - 30)) < (8, 8, 8)
    assert sheet.getpixel((90 + 2 * (3 * 200 + 12) + 5, 34 + 18 + 5)) == (255, 255, 255)


def test_games_from_an_extension_run_continue_the_numbering(tmp_path):
    write_run(tmp_path / "a", [1, 1])
    write_run(tmp_path / "a-ext", [1, 1])
    games = read_games(ledger_row(run_dirs=f"{tmp_path / 'a'},{tmp_path / 'a-ext'}"))
    assert [g[0] for g in games] == ["game 1", "game 2", "game 3", "game 4"]


def test_chart_draws_each_model_in_its_own_color():
    rows = [ledger_row(), ledger_row(id="s", model="clef-omni", harness="clef-omni/v0")]
    chart = progress_chart(rows)
    pixels = {color for _, color in chart.getcolors(maxcolors=chart.width * chart.height)}
    assert MODEL_COLORS["jev"] in pixels and MODEL_COLORS["clef-omni"] in pixels


def test_report_lists_champions_lineage_and_a_model_by_harness_table():
    rows = [
        ledger_row(id="a", mean_best_px="565.4", ci_lo="359.0", ci_hi="749.1"),
        ledger_row(
            id="b",
            harness="jev/v1",
            role="candidate",
            mean_best_px="1041.9",
            ci_lo="732.8",
            ci_hi="1351.0",
            delta_ci_lo="97.6",
            hypothesis="threshold 0.7",
            attempt_px="1408.0,1293.0",
        ),
        ledger_row(id="c", model="clef-omni", harness="jev/v1", role="transfer", decision="transfer",
                   mean_best_px="700.0", ci_lo="600.0", ci_hi="800.0"),
    ]  # fmt: skip

    text = markdown(rows, {"jev": "v1", "clef-omni": "v0"}, ["old"], {"b": "b/deaths.jpg"})

    assert "| jev | jev/v1 | 1041.9 [732.8, 1351.0] | 5 | 0 | threshold 0.7 |" in text
    assert "| clef-omni | v0 | no ledger row | | | |" in text
    assert (
        "| jev/v1 | candidate | 1041.9 [732.8, 1351.0] | 97.6 | champion | 1408.0, 1293.0 |" in text
    )
    assert "| jev/v0 | 565.4 [359.0, 749.1] n=5 |  |" in text
    assert "| jev/v1 | 1041.9 [732.8, 1351.0] n=5 | 700.0 [600.0, 800.0] n=5 |" in text
    assert "- b: ![deaths](b/deaths.jpg)" in text
    assert "old" in text.split("## Superseded rows")[1]
