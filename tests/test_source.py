import subprocess
import tempfile
import unittest
from pathlib import Path

from installer.errors import InstallError
from installer.shell import Shell
from installer.source import GitSource, Workspace


class GitRepos:
    """A "GitHub" repository and the project's clone of it, both in a temporary folder."""

    def __init__(self, branch: str):
        self.root = Path(tempfile.mkdtemp())
        self.remote = self.root / "remote"
        self.clone = self.root / "clone"
        self.remote.mkdir()
        self.git(self.remote, "init", "-q", "-b", branch)
        self.commit(self.remote, "first")
        self.git(self.root, "clone", "-q", str(self.remote), str(self.clone))
        self.git(self.remote, "config", "receive.denyCurrentBranch", "ignore")

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def commit(self, cwd: Path, message: str) -> None:
        (cwd / "file.txt").write_text(message)
        self.git(cwd, "add", "file.txt")
        self.git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)

    def go_offline(self) -> None:
        self.git(self.clone, "remote", "set-url", "origin", str(self.root / "missing"))

    def remove(self) -> None:
        subprocess.run(["trash", str(self.root)])


class GitSourceTest(unittest.TestCase):
    def tearDown(self):
        self.repos.remove()

    def test_main_branch(self):
        self.repos = GitRepos("main")
        self.assertEqual(GitSource(Shell(), self.repos.clone, "origin", None).upstream, "origin/main")

    def test_master_branch(self):
        self.repos = GitRepos("master")
        self.assertEqual(GitSource(Shell(), self.repos.clone, "origin", None).upstream, "origin/master")

    def test_master_without_remote_head(self):
        self.repos = GitRepos("master")
        self.repos.git(self.repos.clone, "remote", "set-head", "origin", "--delete")
        self.assertEqual(GitSource(Shell(), self.repos.clone, "origin", None).upstream, "origin/master")

    def test_fetch_brings_new_commits_without_touching_the_branch(self):
        self.repos = GitRepos("main")
        self.repos.commit(self.repos.remote, "second")
        source = GitSource(Shell(), self.repos.clone, "origin", None)
        self.assertTrue(source.fetch())
        self.assertIn("second", source.describe(source.upstream))
        self.assertIn("first", source.describe("main"))

    def test_offline_keeps_the_last_fetched_state(self):
        self.repos = GitRepos("main")
        self.repos.go_offline()
        source = GitSource(Shell(), self.repos.clone, "origin", None)
        source.FETCH_PAUSE_SECONDS = 0
        self.assertFalse(source.fetch())
        self.assertIn("first", source.describe(source.upstream))

    def test_unpushed_commits(self):
        self.repos = GitRepos("main")
        self.repos.commit(self.repos.clone, "local")
        self.assertEqual(GitSource(Shell(), self.repos.clone, "origin", None).unpushed_commits(), 1)


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.repos = GitRepos("main")
        self.source = GitSource(Shell(), self.repos.clone, "origin", None)

    def tearDown(self):
        self.repos.remove()

    def test_upstream_sources_only_during_the_install(self):
        self.repos.commit(self.repos.clone, "local")
        (self.repos.clone / "file.txt").write_text("uncommitted")
        with Workspace(Shell(), self.source) as workspace:
            self.assertEqual((workspace.tree / "file.txt").read_text(), "first")
            self.assertIn(str(workspace.tree), self.repos.git(self.repos.clone, "worktree", "list"))
        self.assertFalse(workspace.tree.exists())
        self.assertNotIn(str(workspace.tree), self.repos.git(self.repos.clone, "worktree", "list"))
        self.assertEqual((self.repos.clone / "file.txt").read_text(), "uncommitted")

    def test_cleans_up_after_a_failure(self):
        with self.assertRaises(RuntimeError):
            with Workspace(Shell(), self.source) as workspace:
                raise RuntimeError
        self.assertFalse(workspace.tree.exists())
        self.assertEqual(len(self.repos.git(self.repos.clone, "worktree", "list").splitlines()), 1)

    def test_submodule_comes_from_the_clone_without_network(self):
        library = self.repos.root / "library"
        library.mkdir()
        self.repos.git(library, "init", "-q", "-b", "main")
        self.repos.commit(library, "library")
        self.repos.git(self.repos.clone, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "lib")
        self.repos.git(self.repos.clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "lib")
        self.repos.git(self.repos.clone, "push", "-q", "origin", "main")
        self.repos.git(self.repos.clone, "fetch", "-q", "origin")
        library.rename(self.repos.root / "library-unreachable")
        with Workspace(Shell(), self.source) as workspace:
            self.assertEqual((workspace.tree / "lib" / "file.txt").read_text(), "library")
        self.assertEqual(len(self.repos.git(self.repos.clone, "worktree", "list").splitlines()), 1)

    def test_no_branch_on_remote(self):
        source = GitSource(Shell(), self.repos.clone, "origin", "missing")
        source.FETCH_PAUSE_SECONDS = 0
        with self.assertRaises(InstallError):
            source.fetch()


if __name__ == "__main__":
    unittest.main()
