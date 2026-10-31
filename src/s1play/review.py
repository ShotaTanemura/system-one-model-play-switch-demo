import argparse
import json
import os
import re
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from s1play.harness import load
from s1play.label import BENCH, audit_sample

HARNESS = Path("harnesses/jev/v0.toml")
PAGE = Path(__file__).with_name("review.html")
SCREENS = ("transition", "game_over", "title_screen", "level_clear")
FRAME = re.compile(r"frames/(?P<run>[\w-]+)_(?P<step>\d{6})\.jpg")
RUN_FRAME = re.compile(r"/run/(?P<run>[\w-]+)/(?P<step>\d{6})\.jpg")
EDITABLE = {"dead", "note", "reviewed"}


def derive_action(labels: Mapping[str, bool], dead: bool) -> str:
    if dead or any(labels[q] for q in SCREENS):
        return "WAIT"
    return "RUN_JUMP" if labels["jump_now"] else "RUN"


def apply_edit(rows: list[dict], frame: str, edit: Mapping[str, object]) -> list[dict]:
    """Returns a copy of `rows` with one row edited and its action re-derived."""
    unknown = set(edit) - EDITABLE - {"labels"}
    if unknown:
        raise ValueError(f"cannot edit {sorted(unknown)}")
    if not any(r["frame"] == frame for r in rows):
        raise KeyError(frame)
    out = []
    for row in rows:
        if row["frame"] != frame:
            out.append(row)
            continue
        labels = {**row["labels"]}
        for qid, value in edit.get("labels", {}).items():
            if qid not in labels:
                raise ValueError(f"unknown question {qid!r}")
            labels[qid] = bool(value)
        new = {**row, **{k: edit[k] for k in EDITABLE & set(edit)}, "labels": labels}
        out.append({**new, "action": derive_action(labels, new["dead"])})
    return out


def load_rows(path: Path) -> list[dict]:
    return [{"reviewed": False, **json.loads(line)} for line in path.read_text().splitlines()]


def save_rows(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    os.replace(tmp, path)


def state(rows: list[dict], questions: Mapping[str, str]) -> dict:
    sample = audit_sample([r["frame"] for r in rows])
    return {
        "rows": [{**r, **_where(r["frame"])} for r in rows],
        "questions": questions,
        "audit": sorted(sample),
    }


def _where(frame: str) -> dict:
    m = FRAME.fullmatch(frame)
    return {"run": m["run"], "step": int(m["step"])}


def make_handler(labels_path: Path, runs_dir: Path, questions: Mapping[str, str]):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, kind: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object, status: int = 200) -> None:
            self._send(json.dumps(payload).encode(), "application/json", status)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/":
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                with lock:
                    return self._json(state(load_rows(labels_path), questions))
            if m := re.fullmatch(r"/bench/(frames/[\w-]+\.jpg)", path):
                return self._image(BENCH / m[1])
            if m := RUN_FRAME.fullmatch(path):
                return self._image(runs_dir / m["run"] / "frames" / f"{m['step']}.jpg")
            self._send(b"not found", "text/plain", 404)

        def _image(self, file: Path) -> None:
            if not file.is_file():
                return self._send(b"", "image/jpeg", 404)
            self._send(file.read_bytes(), "image/jpeg")

        def do_POST(self) -> None:
            if self.path != "/api/edit":
                return self._send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                rows = load_rows(labels_path)
                try:
                    rows = apply_edit(rows, body["frame"], body["edit"])
                except (KeyError, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
                save_rows(labels_path, rows)
            self._json(next(r for r in rows if r["frame"] == body["frame"]))

        def log_message(self, *args) -> None:
            pass

    return Handler


def main() -> None:
    p = argparse.ArgumentParser(prog="s1play.review")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--runs", type=Path, default=Path("runs"))
    args = p.parse_args()
    handler = make_handler(BENCH / "labels.jsonl", args.runs, load(HARNESS).questions)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"review screen on http://127.0.0.1:{args.port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
