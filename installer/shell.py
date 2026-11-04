from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence


class Shell:
    def __init__(self, extra_env: Optional[Dict[str, str]] = None):
        self._extra_env = dict(extra_env or {})

    def with_developer_dir(self, developer_dir: Path) -> "Shell":
        """Commands run by the returned shell use this Xcode instead of the one xcode-select points to."""
        return Shell({**self._extra_env, "DEVELOPER_DIR": str(developer_dir)})

    def run(self, args: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=self._env())

    def succeeds(self, args: Sequence[str], cwd: Optional[Path] = None) -> bool:
        return self.run(args, cwd).returncode == 0

    def run_streamed(self, args: Sequence[str], log: Path, on_line: Callable[[str], None],
                     cwd: Optional[Path] = None) -> bool:
        with log.open("w") as stream:
            process = subprocess.Popen(list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors="replace", env=self._env())
            for line in process.stdout:
                stream.write(line)
                on_line(line)
            return process.wait() == 0

    def _env(self) -> Dict[str, str]:
        return {**os.environ, **self._extra_env}
