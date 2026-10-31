import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from s1play import ledger

EXPERIMENTS = Path("experiments")
HARNESSES = Path("harnesses")
MODEL_COLORS = {"jev": (0, 114, 178), "clef-omni": (230, 159, 0)}
INK = (30, 30, 30)
GRID = (222, 222, 222)
BACKGROUND = (255, 255, 255)
THUMB_W = 200
CROP_TOP = 0.4
LIVES_PER_GAME = 3
FRAMES_PER_LIFE = 3
PEAK_SLACK = 0.5


@dataclass(frozen=True)
class Stall:
    """Where one life stopped making progress, with the frames that lead into it."""

    attempt: int
    life: int
    frames: tuple[str, ...]
    peak: float


def current_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Drops a row when a later row measured the same model, harness and role again."""
    latest = {(r["model"], r["harness"], r["role"]): r["id"] for r in rows}
    return [r for r in rows if latest[(r["model"], r["harness"], r["role"])] == r["id"]]


def stalls(log: Sequence[dict]) -> list[Stall]:
    """The last frames before the screen stopped scrolling in each life.

    The frames right before a black screen show the death animation with Mario already gone,
    so the peak of `progress`, where the contact happens, is the better place to look.
    """
    lives: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in log:
        lives[(row["attempt"], row["life"])].append(row)
    out = []
    for (attempt, life), rows in sorted(lives.items()):
        peak = max(r["progress"] for r in rows)
        if peak <= 0:
            continue
        at = next(i for i, r in enumerate(rows) if r["progress"] >= peak - PEAK_SLACK)
        frames = tuple(r["frame"] for r in rows[max(0, at - FRAMES_PER_LIFE + 1) : at + 1])
        out.append(Stall(attempt, life, frames, peak))
    return out


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def contact_sheet(title: str, games: Sequence[tuple[str, Path, list[Stall]]]) -> Image.Image:
    """One row per game and one block per life. `games` is (label, run_dir, stalls)."""
    thumb_h = round(495 * (1 - CROP_TOP) * THUMB_W / 640)
    block_w = FRAMES_PER_LIFE * THUMB_W + 12
    label_h, gap = 18, 8
    width = LIVES_PER_GAME * block_w + 90
    height = 34 + len(games) * (label_h + thumb_h + gap)
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 6), title, fill=INK, font=_font(16))
    for g, (label, run_dir, game_stalls) in enumerate(games):
        top = 34 + g * (label_h + thumb_h + gap)
        draw.text((8, top + label_h + thumb_h // 2 - 8), label, fill=INK, font=_font(14))
        for stall in game_stalls[:LIVES_PER_GAME]:
            left = 90 + stall.life * block_w
            draw.text(
                (left, top), f"life {stall.life + 1}: {stall.peak:.0f} px", fill=INK, font=_font(13)
            )
            for i, name in enumerate(stall.frames):
                with Image.open(run_dir / name) as im:
                    im = im.convert("RGB")
                    im = im.crop((0, round(im.height * CROP_TOP), im.width, im.height))
                    sheet.paste(im.resize((THUMB_W, thumb_h)), (left + i * THUMB_W, top + label_h))
    return sheet


def progress_chart(rows: Sequence[dict[str, str]]) -> Image.Image:
    """Every game as a dot, with the mean and its 95% CI, one column per ledger row."""
    col_w, left, top, plot_h, foot = 120, 70, 40, 360, 70
    width, height = left + col_w * len(rows) + 20, top + plot_h + foot
    top_px = max(float(r["ci_hi"]) for r in rows)
    top_px = max(top_px, *(max(ledger.attempt_px(r)) for r in rows))
    step = 250 if top_px <= 2000 else 500
    ceiling = (int(top_px // step) + 1) * step

    def y(px: float) -> int:
        return round(top + plot_h * (1 - px / ceiling))

    chart = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(chart)
    draw.text(
        (8, 8),
        "Best progress per game (NES px). Bar: mean. Whisker: 95% CI.",
        fill=INK,
        font=_font(14),
    )
    for tick in range(0, ceiling + 1, step):
        draw.line([(left, y(tick)), (width - 10, y(tick))], fill=GRID)
        draw.text((8, y(tick) - 7), str(tick), fill=INK, font=_font(12))
    for i, row in enumerate(rows):
        cx = left + col_w * i + col_w // 2
        color = MODEL_COLORS.get(row["model"], INK)
        lo, hi = float(row["ci_lo"]), float(row["ci_hi"])
        draw.line([(cx, y(lo)), (cx, y(hi))], fill=color, width=2)
        for cap in (lo, hi):
            draw.line([(cx - 8, y(cap)), (cx + 8, y(cap))], fill=color, width=2)
        mean = float(row["mean_best_px"])
        draw.line([(cx - 26, y(mean)), (cx + 26, y(mean))], fill=color, width=4)
        for k, px in enumerate(ledger.attempt_px(row)):
            dx = (k - 2) * 9
            draw.ellipse([cx + dx - 4, y(px) - 4, cx + dx + 4, y(px) + 4], outline=INK, fill=color)
        base = top + plot_h + 8
        draw.text((cx - 50, base), row["harness"], fill=INK, font=_font(13))
        draw.text(
            (cx - 50, base + 16), f"{row['role']}, {row['decision']}", fill=INK, font=_font(11)
        )
        draw.text((cx - 50, base + 31), f"on {row['model']}", fill=INK, font=_font(11))
    return chart


def _cell(row: dict[str, str] | None) -> str:
    if row is None:
        return ""
    return f"{row['mean_best_px']} [{row['ci_lo']}, {row['ci_hi']}] n={row['attempts']}"


def markdown(
    rows: Sequence[dict[str, str]],
    champions: dict[str, str],
    superseded: Sequence[str],
    sheets: dict[str, str],
) -> str:
    """`champions` maps a model to its CHAMPION version. `sheets` maps a row id to a sheet path."""
    out = [
        "# Harness report",
        "",
        (
            "Generated by `python -m s1play.report` from `ledger.tsv`. Progress is the best scroll "
            "distance of any life in a game, in NES pixels. Each row is a small sample, so read "
            "the CIs before the means."
        ),
        "",
        "## Champions",
        "",
        "| Model | Harness | Mean best px [95% CI] | Games | Clears | Hypothesis |",
        "|---|---|---|---|---|---|",
    ]
    for model, version in champions.items():
        row = ledger.champion_row(list(rows), model, f"{model}/{version}")
        if row is None:
            out.append(f"| {model} | {version} | no ledger row | | | |")
            continue
        out.append(
            f"| {model} | {row['harness']} | {row['mean_best_px']} [{row['ci_lo']}, {row['ci_hi']}] "
            f"| {row['attempts']} | {row['clears']} | {row['hypothesis']} |"
        )
    out += ["", "## Lineage", ""]
    for model in champions:
        out += [
            f"### {model}",
            "",
            "| Harness | Role | Mean [95% CI] | Lower bound of delta CI | Decision | Games |",
            "|---|---|---|---|---|---|",
        ]
        for r in (r for r in rows if r["model"] == model):
            delta = r["delta_ci_lo"] or "-"
            out.append(
                f"| {r['harness']} | {r['role']} | {r['mean_best_px']} [{r['ci_lo']}, {r['ci_hi']}] "
                f"| {delta} | {r['decision']} | {r['attempt_px'].replace(',', ', ')} |"
            )
        out.append("")
    models = list(champions)
    harnesses = list(dict.fromkeys(r["harness"] for r in rows))
    cells = {(r["harness"], r["model"]): r for r in rows}
    out += [
        "## Model against model",
        "",
        (
            "Each row is a harness. Each column is the model that played it. A cell off the "
            "diagonal is a transfer run."
        ),
        "",
        "| Harness | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]
    for harness in harnesses:
        out.append(
            f"| {harness} | " + " | ".join(_cell(cells.get((harness, m))) for m in models) + " |"
        )
    out += ["", "![progress](progress.png)", ""]
    if sheets:
        out += [
            "## What ended each life",
            "",
            "Three frames up to the moment progress stopped, per life.",
            "",
        ]
        out += [f"- {row_id}: ![deaths]({path})" for row_id, path in sheets.items()]
        out.append("")
    if superseded:
        out += [
            "## Superseded rows",
            "",
            "Kept in the ledger but left out above, because a later row measured the same model, "
            "harness and role again: " + ", ".join(superseded) + ".",
            "",
        ]
    return "\n".join(out)


def read_games(row: dict[str, str]) -> list[tuple[str, Path, list[Stall]]]:
    games = []
    offset = 0
    for run_dir in (Path(d) for d in row["run_dirs"].split(",")):
        log = [json.loads(line) for line in (run_dir / "log.jsonl").read_text().splitlines()]
        by_attempt: dict[int, list[Stall]] = defaultdict(list)
        for stall in stalls(log):
            by_attempt[stall.attempt].append(stall)
        for attempt in sorted(by_attempt):
            games.append((f"game {offset + attempt}", run_dir, by_attempt[attempt]))
        offset += max((r["attempt"] for r in log), default=0)
    return games


def main() -> None:
    rows = ledger.read()
    if not rows:
        raise SystemExit(f"{ledger.LEDGER} has no rows yet. Run s1play.eval first.")
    shown = current_rows(rows)
    superseded = [r["id"] for r in rows if r not in shown]
    sheets: dict[str, str] = {}
    for row in shown:
        try:
            sheet = contact_sheet(
                f"{row['id']}  {row['harness']} on {row['model']}", read_games(row)
            )
        except FileNotFoundError:
            continue
        path = EXPERIMENTS / row["id"] / "deaths.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path, quality=88)
        sheets[row["id"]] = f"{row['id']}/deaths.jpg"
    progress_chart(shown).save(EXPERIMENTS / "progress.png")
    champions = {
        d.name: (d / "CHAMPION").read_text().strip()
        for d in sorted(HARNESSES.iterdir())
        if (d / "CHAMPION").exists()
    }
    (EXPERIMENTS / "REPORT.md").write_text(markdown(shown, champions, superseded, sheets))
    print(f"wrote {EXPERIMENTS / 'REPORT.md'}, progress.png and {len(sheets)} deaths.jpg sheets")
    if len(sheets) < len(shown):
        print(f"{len(shown) - len(sheets)} rows had no run logs on this machine, so no sheet.")


if __name__ == "__main__":
    main()
