from __future__ import annotations

import subprocess


class Console:
    def __init__(self, title: str):
        self._title = title

    def step(self, text: str) -> None:
        print(f"\n▶ {text}", flush=True)

    def info(self, text: str) -> None:
        print(text, flush=True)

    def warn(self, text: str) -> None:
        print(f"⚠ {text}", flush=True)

    def success(self, text: str) -> None:
        print(f"\n✔ {text}", flush=True)
        self._notify(text)

    def failure(self, text: str) -> None:
        print(f"\n✖ {text}", flush=True)
        self._notify(f"Не установлено: {text}")

    def _notify(self, text: str) -> None:
        script = ["on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run"]
        args = ["/usr/bin/osascript"]
        for line in script:
            args += ["-e", line]
        subprocess.run(args + [text, self._title], capture_output=True)
