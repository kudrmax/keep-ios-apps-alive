from __future__ import annotations

import re
import shutil
import sys
import threading
import time
from typing import Optional


class BuildActivity:
    """Turns an xcodebuild output line into what the build is doing right now, in words."""

    PATTERNS = [
        (re.compile(r"^(SwiftCompile|CompileSwift|CompileC) .*?([^/\s]+\.(swift|m|mm|c|cpp))\b"), "компилирую {file}"),
        (re.compile(r"^(Resolve Package Graph|Fetching from|Cloning|Checking out)"), "подтягиваю Swift-пакеты"),
        (re.compile(r"^CompileAssetCatalog"), "собираю картинки и иконки"),
        (re.compile(r"^(CompileStoryboard|CompileXIB|LinkStoryboards)"), "собираю экраны"),
        (re.compile(r"^Ld "), "собираю бинарник"),
        (re.compile(r"^CodeSign "), "подписываю"),
        (re.compile(r"^ProcessProvisioningProfile|^Signing Identity"), "получаю профиль подписи"),
    ]

    @classmethod
    def describe(cls, line: str) -> Optional[str]:
        for pattern, template in cls.PATTERNS:
            match = pattern.search(line)
            if match:
                file = match.group(2) if match.re.groups >= 2 and match.group(2) else ""
                return template.format(file=file)
        return None


class StatusLine:
    """One terminal line that is rewritten in place every second: a spinner, the elapsed time and the activity."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, activity: str):
        self._activity = activity
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick, daemon=True)

    def __enter__(self) -> "StatusLine":
        self._thread.start()
        return self

    def __exit__(self, error_type, *_) -> None:
        self._stop.set()
        self._thread.join()
        sys.stdout.write(f"\r\033[K{self._elapsed()}  {'не получилось' if error_type else 'готово'}\n")
        sys.stdout.flush()

    def update(self, activity: str) -> None:
        self._activity = activity

    def _tick(self) -> None:
        frame = 0
        while not self._stop.wait(0.25 if frame else 0):
            line = f"{self.FRAMES[frame % len(self.FRAMES)]} {self._elapsed()}  {self._activity}"
            sys.stdout.write(f"\r\033[K{line[:shutil.get_terminal_size().columns - 1]}")
            sys.stdout.flush()
            frame += 1

    def _elapsed(self) -> str:
        seconds = int(time.monotonic() - self._started)
        return f"{seconds // 60}:{seconds % 60:02d}"
