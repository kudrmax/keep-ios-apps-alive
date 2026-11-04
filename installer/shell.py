from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Sequence


class Shell:
    def run(self, args: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)

    def output(self, args: Sequence[str], cwd: Optional[Path] = None) -> str:
        result = self.run(args, cwd)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, list(args), result.stdout, result.stderr)
        return result.stdout

    def succeeds(self, args: Sequence[str], cwd: Optional[Path] = None) -> bool:
        return self.run(args, cwd).returncode == 0

    def run_logged(self, args: Sequence[str], log: Path, cwd: Optional[Path] = None) -> bool:
        with log.open("w") as stream:
            return subprocess.run(list(args), cwd=cwd, stdout=stream, stderr=subprocess.STDOUT).returncode == 0
