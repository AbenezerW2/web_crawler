from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import webview

from app_model import AppValidationError, ExtractionOptions, build_crawler_command


APP_DIR = Path(__file__).resolve().parent
CRAWLER_PATH = APP_DIR / "crawler.py"
FRONTEND_INDEX = APP_DIR / "frontend" / "dist" / "index.html"


class DesktopBridge:
    def __init__(self) -> None:
        self.window: webview.Window | None = None
        self.process: subprocess.Popen[str] | None = None
        self.events: list[dict[str, Any]] = []
        self.exit_code: int | None = None
        self.lock = threading.Lock()

    def attach_window(self, window: webview.Window) -> None:
        self.window = window

    def _append_event(self, event_type: str, **values: Any) -> None:
        with self.lock:
            self.events.append({"type": event_type, **values})

    def choose_output_dir(self, initial: str) -> str | None:
        if not self.window:
            return None
        directory = self._resolve_output_dir(initial)
        selection = self.window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=str(directory),
            allow_multiple=False,
        )
        if not selection:
            return None
        return str(selection[0] if isinstance(selection, (tuple, list)) else selection)

    def start_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.process and self.process.poll() is None:
            return {"ok": False, "error": "An extraction is already running."}

        try:
            options = self._options_from_payload(payload)
            command = build_crawler_command(options, sys.executable, CRAWLER_PATH)
        except (AppValidationError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(
                command,
                cwd=APP_DIR,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return {"ok": False, "error": f"Could not start the crawler: {exc}"}

        with self.lock:
            self.events = []
            self.exit_code = None
            self.process = process
        threading.Thread(target=self._read_process, args=(process,), daemon=True).start()
        return {"ok": True}

    def _read_process(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for line in iter(process.stdout.readline, ""):
                self._append_event("output", text=line)
                lowered = line.lower()
                if lowered.startswith("saved:"):
                    self._append_event("saved", path=line.split(":", 1)[1].strip())
                if "complete any verification" in lowered:
                    self._append_event("verification")
        finally:
            exit_code = process.wait()
            with self.lock:
                self.exit_code = exit_code
                if self.process is process:
                    self.process = None
            self._append_event("finished", exitCode=exit_code)

    def get_status(self, cursor: int = 0) -> dict[str, Any]:
        with self.lock:
            safe_cursor = max(0, min(int(cursor), len(self.events)))
            events = self.events[safe_cursor:]
            next_cursor = len(self.events)
            running = self.process is not None and self.process.poll() is None
            exit_code = self.exit_code
        return {
            "events": events,
            "cursor": next_cursor,
            "running": running,
            "exitCode": exit_code,
        }

    def send_verification(self) -> dict[str, Any]:
        with self.lock:
            process = self.process
        if not process or process.poll() is not None or process.stdin is None:
            return {"ok": False}
        try:
            process.stdin.write("\n")
            process.stdin.flush()
            return {"ok": True}
        except OSError:
            return {"ok": False}

    def stop_extraction(self) -> dict[str, Any]:
        with self.lock:
            process = self.process
        if not process or process.poll() is not None:
            return {"ok": False}
        process.terminate()
        threading.Thread(target=self._kill_after_timeout, args=(process,), daemon=True).start()
        return {"ok": True}

    @staticmethod
    def _kill_after_timeout(process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def open_output_folder(self, output_dir: str) -> dict[str, Any]:
        try:
            path = self._resolve_output_dir(output_dir)
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _resolve_output_dir(value: str) -> Path:
        path = Path(value or "outputs").expanduser()
        return (path if path.is_absolute() else APP_DIR / path).resolve()

    @staticmethod
    def _options_from_payload(payload: dict[str, Any]) -> ExtractionOptions:
        whole_book = payload.get("mode") == "book"
        return ExtractionOptions(
            url=str(payload.get("url", "")),
            name=str(payload.get("name", "")),
            output_dir=str(payload.get("output_dir", "")),
            output_format=str(payload.get("output_format", "markdown")),
            whole_book=whole_book,
            start_chapter=int(payload.get("start_chapter", 1)),
            end_chapter=int(payload.get("end_chapter", 1)),
            playwright=True if whole_book else bool(payload.get("playwright", False)),
            headed=bool(payload.get("headed", False)),
            wait_for_user=bool(payload.get("wait_for_user", False)),
            delay=float(payload.get("delay", 0)),
            overwrite=bool(payload.get("overwrite", False)),
        ).validated()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Web Extractor desktop app.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Load the Vite development server at http://localhost:5173",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dev:
        frontend_url = "http://localhost:5173"
    else:
        if not FRONTEND_INDEX.exists():
            print(
                "The React frontend has not been built. Run `npm install` and `npm run build` "
                "inside the frontend folder, then launch the app again.",
                file=sys.stderr,
            )
            return 1
        frontend_url = str(FRONTEND_INDEX)

    bridge = DesktopBridge()
    window = webview.create_window(
        "Web Extractor",
        frontend_url,
        js_api=bridge,
        width=1120,
        height=860,
        min_size=(760, 640),
        background_color="#070b12",
        text_select=True,
    )
    bridge.attach_window(window)
    try:
        webview.start(debug=args.dev, private_mode=False)
    finally:
        bridge.stop_extraction()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
