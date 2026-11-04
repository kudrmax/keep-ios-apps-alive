from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import List

from .errors import InstallError
from .shell import Shell


class GitSource:
    """The project's own clone. Only its remote-tracking ref is updated: branches, HEAD and files stay untouched."""

    FETCH_ATTEMPTS = 3
    FETCH_PAUSE_SECONDS = 2

    def __init__(self, shell: Shell, clone: Path, remote: str, branch: str):
        self._shell = shell
        self.clone = clone
        self._remote = remote
        self._branch = branch

    @property
    def upstream(self) -> str:
        return f"{self._remote}/{self._branch}"

    def fetch(self) -> None:
        # Another agent fetching at the same moment holds the ref lock, so a failed fetch is worth a retry.
        for attempt in range(1, self.FETCH_ATTEMPTS + 1):
            result = self._git("fetch", "--quiet", self._remote, self._branch)
            if result.returncode == 0:
                return
            if attempt < self.FETCH_ATTEMPTS:
                time.sleep(self.FETCH_PAUSE_SECONDS)
        raise InstallError(f"не получилось скачать {self.upstream} с GitHub: {result.stderr.strip()}")

    def unpushed_commits(self) -> int:
        if self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{self._branch}").returncode != 0:
            return 0
        return int(self._git("rev-list", "--count", f"{self.upstream}..{self._branch}").stdout.strip())

    def describe(self, revision: str) -> str:
        return self._git("log", "--oneline", "-1", revision).stdout.strip()

    def local_configs(self) -> List[Path]:
        """Git-ignored *.xcconfig files, such as a personal signing team, that a fresh checkout lacks."""
        listing = self._git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", "*.xcconfig").stdout
        return [Path(name) for name in listing.split("\0") if name]

    def _git(self, *args: str):
        return self._shell.run(["git", "-C", str(self.clone), *args])


class BuildTree:
    """A detached worktree of the upstream branch kept at a fixed path, so incremental builds survive between runs."""

    def __init__(self, shell: Shell, source: GitSource, path: Path):
        self._shell = shell
        self._source = source
        self.path = path

    def checkout(self) -> None:
        if (self.path / ".git").exists():
            self._run_git(["-C", str(self.path), "checkout", "--quiet", "--force", "--detach", self._source.upstream])
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._run_git(["-C", str(self._source.clone), "worktree", "add", "--quiet", "--force", "--detach",
                           str(self.path), self._source.upstream])
        if (self.path / ".gitmodules").exists():
            self._run_git(["-C", str(self.path), "submodule", "update", "--quiet", "--init", "--recursive"])
        self._copy_local_configs()

    def _copy_local_configs(self) -> None:
        for relative in self._source.local_configs():
            target = self.path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._source.clone / relative, target)

    def _run_git(self, args: List[str]) -> None:
        result = self._shell.run(["git", *args])
        if result.returncode != 0:
            raise InstallError(f"не получилось подготовить папку сборки: {result.stderr.strip()}")
