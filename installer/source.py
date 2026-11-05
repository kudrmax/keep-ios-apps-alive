from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from .errors import InstallError
from .shell import Shell


class GitSource:
    """The project's own clone. Only its remote-tracking ref is fetched: branches, HEAD and files stay untouched."""

    FETCH_ATTEMPTS = 3
    FETCH_PAUSE_SECONDS = 2
    MAIN_BRANCHES = ("main", "master")

    def __init__(self, shell: Shell, clone: Path, remote: str, branch: Optional[str]):
        self._shell = shell
        self.clone = clone
        self._remote = remote
        self.branch = branch or self._main_branch()

    @property
    def upstream(self) -> str:
        return f"{self._remote}/{self.branch}"

    def fetch(self) -> bool:
        """False when GitHub is out of reach: the last fetched state of the branch is built then."""
        # Another agent fetching at the same moment holds the ref lock, so a failed fetch is worth a retry.
        for attempt in range(1, self.FETCH_ATTEMPTS + 1):
            if self._git("fetch", "--quiet", self._remote, self.branch).returncode == 0:
                return True
            if attempt < self.FETCH_ATTEMPTS:
                time.sleep(self.FETCH_PAUSE_SECONDS)
        if not self._ref_exists(f"refs/remotes/{self.upstream}"):
            raise InstallError(f"нет ни сети, ни {self.upstream} — хотя бы раз сделать push или pull")
        return False

    def unpushed_commits(self) -> int:
        if not self._ref_exists(f"refs/heads/{self.branch}"):
            return 0
        return int(self._git("rev-list", "--count", f"{self.upstream}..{self.branch}").stdout.strip())

    def describe(self, revision: str) -> str:
        return self._git("log", "--oneline", "-1", revision).stdout.strip()

    def local_configs(self) -> List[Path]:
        """Git-ignored *.xcconfig files, such as a personal signing team, that a fresh checkout lacks.
        Another repository inside the clone (a worktree kept in it) is listed as its folder, ending in a slash: skipped."""
        listing = self._git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", "*.xcconfig").stdout
        return [Path(name) for name in listing.split("\0") if name and not name.endswith("/")]

    def add_worktree(self, path: Path) -> bool:
        return self._git("worktree", "add", "--quiet", "--detach", str(path), self.upstream).returncode == 0

    def prune_worktrees(self) -> None:
        self._git("worktree", "prune")

    def _main_branch(self) -> str:
        remote_head = self._git("symbolic-ref", "--short", f"refs/remotes/{self._remote}/HEAD")
        if remote_head.returncode == 0:
            return remote_head.stdout.strip().partition("/")[2]
        for name in self.MAIN_BRANCHES:
            if self._ref_exists(f"refs/remotes/{self._remote}/{name}"):
                return name
        raise InstallError(f"в {self.clone} нет {self._remote}/main и {self._remote}/master — "
                           "хотя бы раз сделать push или pull")

    def _ref_exists(self, ref: str) -> bool:
        return self._git("rev-parse", "--verify", "--quiet", ref).returncode == 0

    def _git(self, *args: str):
        return self._shell.run(["git", "-C", str(self.clone), *args])


class Workspace:
    """Everything one install needs on disk, for the duration of the install only: a detached worktree of the
    upstream branch (sources only, the history stays in the clone) and Xcode's build folder.
    Afterwards it goes to the Trash and git forgets the worktree."""

    def __init__(self, shell: Shell, source: GitSource):
        self._shell = shell
        self._source = source
        self._root = Path(tempfile.mkdtemp(prefix="install-on-iphone-"))
        self.tree = self._root / "tree"
        self.derived_data = self._root / "DerivedData"
        self.log = self._root / "build.log"

    def __enter__(self) -> "Workspace":
        try:
            if not self._source.add_worktree(self.tree):
                raise InstallError(f"не получилось выложить {self._source.upstream} во временную папку")
            if (self.tree / ".gitmodules").exists():
                self._check_out_submodules()
            self._copy_local_configs()
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_) -> None:
        self._shell.run(["trash", str(self._root)])
        self._source.prune_worktrees()

    def _check_out_submodules(self) -> None:
        """Submodules come from the clone's own checkouts: no network, and git hard-links their objects.
        Only a commit the clone does not have yet is downloaded from the submodule's remote."""
        self._tree_git("submodule", "init")
        listing = self._tree_git("config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$").stdout
        for key, path in (line.split(" ", 1) for line in listing.splitlines()):
            name = key[len("submodule."):-len(".path")]
            local = self._source.clone / path
            if (local / ".git").exists():
                self._tree_git("config", f"submodule.{name}.url", str(local))
        update = ["-c", "protocol.file.allow=always", "submodule", "update", "--quiet", "--recursive"]
        if self._tree_git(*update).returncode == 0:
            return
        self._tree_git("submodule", "sync", "--quiet", "--recursive")
        result = self._tree_git(*update)
        if result.returncode != 0:
            raise InstallError(f"не получилось подтянуть подмодули: {result.stderr.strip()[-300:]}")

    def _tree_git(self, *args: str):
        return self._shell.run(["git", "-C", str(self.tree), *args])

    def _copy_local_configs(self) -> None:
        for relative in self._source.local_configs():
            target = self.tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._source.clone / relative, target)
