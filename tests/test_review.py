import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from s1play.label import audit_sample
from s1play.review import apply_edit, derive_action, load_rows, make_handler, save_rows

QUESTIONS = [
    "jump_now",
    "enemy_ahead",
    "airborne",
    "transition",
    "game_over",
    "title_screen",
    "level_clear",
]


def labels(**yes):
    return {q: q in yes for q in QUESTIONS}


def row(frame="frames/run-a_000003.jpg", **yes):
    return {
        "frame": frame,
        "source_run": "run-a",
        "labels": labels(**yes),
        "action": "RUN",
        "dead": False,
        "note": "",
        "reviewed": False,
    }


@pytest.mark.parametrize(
    ("yes", "dead", "expected"),
    [
        ({}, False, "RUN"),
        ({"airborne": True}, False, "RUN"),
        ({"jump_now": True}, False, "RUN_JUMP"),
        ({"jump_now": True, "transition": True}, False, "WAIT"),
        ({"level_clear": True}, False, "WAIT"),
        ({"jump_now": True}, True, "WAIT"),
    ],
)
def test_action_follows_the_labeling_rule(yes, dead, expected):
    assert derive_action(labels(**yes), dead) == expected


def test_edit_changes_one_row_and_rederives_its_action():
    rows = [row("frames/run-a_000003.jpg"), row("frames/run-a_000004.jpg")]

    out = apply_edit(rows, "frames/run-a_000004.jpg", {"labels": {"jump_now": True}})

    assert out[0] == rows[0]
    assert out[1]["labels"]["jump_now"] is True
    assert out[1]["action"] == "RUN_JUMP"
    assert rows[1]["labels"]["jump_now"] is False


def test_dead_and_reviewed_and_note_are_editable_and_dead_wins_over_jump():
    rows = [row(jump_now=True)]
    out = apply_edit(rows, rows[0]["frame"], {"dead": True, "reviewed": True, "note": "x"})
    assert (out[0]["action"], out[0]["reviewed"], out[0]["note"]) == ("WAIT", True, "x")


@pytest.mark.parametrize(
    "edit", [{"action": "RUN"}, {"labels": {"made_up": True}}], ids=["action", "question"]
)
def test_edit_rejects_fields_it_does_not_own(edit):
    with pytest.raises(ValueError):
        apply_edit([row()], row()["frame"], edit)


def test_edit_of_a_missing_frame_is_an_error():
    with pytest.raises(KeyError):
        apply_edit([row()], "frames/nope_000001.jpg", {"dead": True})


def test_rows_round_trip_and_default_to_unreviewed(tmp_path):
    path = tmp_path / "labels.jsonl"
    old = {k: v for k, v in row().items() if k != "reviewed"}
    path.write_text(json.dumps(old) + "\n")

    rows = load_rows(path)
    assert rows[0]["reviewed"] is False

    save_rows(path, apply_edit(rows, rows[0]["frame"], {"reviewed": True}))
    assert load_rows(path)[0]["reviewed"] is True
    assert not path.with_suffix(".tmp").exists()


def test_audit_sample_is_a_fixed_tenth_of_the_frames():
    frames = [f"frames/r_{i:06d}.jpg" for i in range(200)]
    first = audit_sample(frames)
    assert len(first) == 20
    assert first == audit_sample(frames)


def post(url, body):
    req = Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urlopen(req))


def test_server_serves_state_and_saves_an_edit_to_disk(tmp_path):
    labels_path = tmp_path / "labels.jsonl"
    save_rows(labels_path, [row()])
    questions = {q: f"text of {q}" for q in QUESTIONS}
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(labels_path, tmp_path / "runs", questions)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        state = json.load(urlopen(base + "/api/state"))
        assert state["rows"][0]["step"] == 3
        assert state["rows"][0]["run"] == "run-a"
        assert state["questions"]["jump_now"] == "text of jump_now"

        saved = post(
            base + "/api/edit", {"frame": row()["frame"], "edit": {"labels": {"jump_now": True}}}
        )
        assert saved["action"] == "RUN_JUMP"
        assert json.loads(labels_path.read_text())["labels"]["jump_now"] is True

        assert b"Label review" in urlopen(base + "/").read()
    finally:
        server.shutdown()
