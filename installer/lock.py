from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import IO, List, Optional, Tuple

from .errors import InstallError

SHELLS = {"bash", "zsh", "sh", "dash", "fish", "login", "env", "sudo", "python3", "Python"}
MAX_ANCESTORS = 30


class Launch(Enum):
    ICON = "icon"
    COMMAND = "command"


class Processes:
    def parent(self, pid: int) -> Optional[Tuple[int, str]]:
        """The parent's pid and the process's own executable name."""
        line = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout
        ppid, _, command = line.strip().partition(" ")
        return (int(ppid), Path(command.strip()).name) if ppid.isdigit() else None


@dataclass
class LockOwner:
    """Who holds the install lock: the process that is installing the app right now."""
    pid: int
    started: float
    launch: Launch
    caller: Optional[str]
    terminal: Optional[str]

    @classmethod
    def current(cls, launch: Launch) -> "LockOwner":
        return cls.of_process(launch, Processes(), os.getpid(), cls._own_terminal())

    @classmethod
    def of_process(cls, launch: Launch, processes: Processes, pid: int, terminal: Optional[str]) -> "LockOwner":
        return cls(pid=pid, started=time.time(), launch=launch, caller=cls._caller(processes, pid),
                   terminal=terminal)

    @classmethod
    def load(cls, text: str) -> Optional["LockOwner"]:
        try:
            fields = json.loads(text)
            return cls(**{**fields, "launch": Launch(fields["launch"])})
        except (ValueError, TypeError, KeyError):
            return None

    def dump(self) -> str:
        return json.dumps({**asdict(self), "launch": self.launch.value})

    def describe(self, name: str, now: float) -> List[str]:
        launch = f"иконка Install {name}.app" if self.launch is Launch.ICON else "команда install-on-iphone run"
        lines = [f"способ: {launch}"]
        if self.caller:
            lines.append(f"откуда: {self.caller}")
        if self.terminal:
            lines.append(f"терминал: {self.terminal}")
        lines.append(f"начало: {time.strftime('%H:%M', time.localtime(self.started))}, {self._ago(now)}")
        lines.append(f"процесс: {self.pid}")
        return lines

    def _ago(self, now: float) -> str:
        minutes = int(now - self.started) // 60
        return f"{minutes} мин назад" if minutes else "только что"

    @staticmethod
    def _caller(processes: Processes, pid: int) -> Optional[str]:
        for _ in range(MAX_ANCESTORS):
            entry = processes.parent(pid)
            if entry is None:
                return None
            ppid, command = entry
            if command not in SHELLS:
                return command
            if ppid <= 1:
                return None
            pid = ppid
        return None

    @staticmethod
    def _own_terminal() -> Optional[str]:
        stream = sys.stdin
        return Path(os.ttyname(stream.fileno())).name if stream and stream.isatty() else None


class InstallLock:
    """Only one install of a project at a time. The holder writes itself into the lock file,
    so a second install can say who is already installing instead of "somewhere, someone"."""

    def __init__(self, path: Path, name: str, owner: LockOwner):
        self._path = path
        self._name = name
        self._owner = owner
        self._file: Optional[IO[str]] = None

    def __enter__(self) -> "InstallLock":
        self._file = self._path.open("a+")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            message = self._busy_message()
            self._file.close()
            raise InstallError(message)
        self._file.truncate(0)
        self._file.write(self._owner.dump())
        self._file.flush()
        return self

    def __exit__(self, *_) -> None:
        self._file.truncate(0)
        self._file.close()

    def _busy_message(self) -> str:
        self._file.seek(0)
        holder = LockOwner.load(self._file.read())
        headline = f"{self._name} уже ставится"
        if holder is None:
            return headline
        return "\n".join([headline] + [f"  {line}" for line in holder.describe(self._name, time.time())])
