import io
import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from installer.cli import main
from installer.config import InstallConfig
from installer.errors import InstallError
from installer.registry import AppRegistry, ProjectName


class AppRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = AppRegistry(Path(tempfile.mkdtemp()) / "apps.json")

    def test_empty_without_file(self):
        self.assertEqual(self.registry.apps(), [])

    def test_put_replaces_by_name(self):
        self.registry.put(InstallConfig(name="Calendar", clone="/a"))
        self.registry.put(InstallConfig(name="calendar", clone="/b", scheme="App"))
        self.assertEqual(self.registry.apps(), [InstallConfig(name="calendar", clone="/b", scheme="App")])

    def test_file_keeps_only_what_differs_from_defaults(self):
        self.registry.put(InstallConfig(name="Calendar", clone="/a", iphone="Max"))
        self.assertEqual(json.loads(self.registry.path.read_text()),
                         {"apps": [{"name": "Calendar", "clone": "/a", "iphone": "Max"}]})

    def test_remove(self):
        self.registry.put(InstallConfig(name="A", clone="/a"))
        self.registry.put(InstallConfig(name="B", clone="/b"))
        self.registry.remove("a")
        self.assertEqual([app.name for app in self.registry.apps()], ["B"])

    def test_unknown_name(self):
        with self.assertRaises(InstallError):
            self.registry.get("missing")


class ProjectNameTest(unittest.TestCase):
    def setUp(self):
        self.clone = Path(tempfile.mkdtemp()) / "my-app"
        self.clone.mkdir()

    def test_xcode_project(self):
        (self.clone / "Calendar.xcodeproj").mkdir()
        self.assertEqual(ProjectName.guess(self.clone), "Calendar")

    def test_xcodegen_spec(self):
        (self.clone / "project.yml").write_text("name: TaskCalendar\noptions:\n  bundleIdPrefix: com.x\n")
        self.assertEqual(ProjectName.guess(self.clone), "TaskCalendar")

    def test_folder(self):
        self.assertEqual(ProjectName.guess(self.clone), "my-app")


class CommandsTest(unittest.TestCase):
    """The whole command line against a temporary list, applications folder and project."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.applications = self.root / "Applications"
        self.clone = self.root / "calendar"
        self.clone.mkdir()
        self._git("init", "-q", "-b", "main")
        self._git("remote", "add", "origin", "https://example.com/calendar.git")
        (self.clone / "project.yml").write_text("name: Calendar\n")
        env = {"INSTALL_ON_IPHONE_APPS": str(self.root / "apps.json"),
               "INSTALL_ON_IPHONE_APPLICATIONS": str(self.applications)}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        subprocess.run(["trash", str(self.root)])

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.clone), *args], check=True, capture_output=True)

    @staticmethod
    def _main(argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(argv)

    def _launcher(self, name="Calendar"):
        return self.applications / f"Install {name}.app"

    def test_add_creates_a_launcher_with_its_config(self):
        self.assertEqual(self._main(["add", str(self.clone), "--iphone", "Max"]), 0)
        resources = self._launcher() / "Contents/Resources"
        config = InstallConfig.load(resources / "config.json")
        self.assertEqual((config.name, config.clone, config.iphone), ("Calendar", str(self.clone.resolve()), "Max"))
        self.assertTrue((resources / "installer/installer.py").is_file())
        self.assertTrue(os.access(self._launcher() / "Contents/MacOS/launch", os.X_OK))
        with (self._launcher() / "Contents/Info.plist").open("rb") as stream:
            self.assertEqual(plistlib.load(stream)["CFBundleExecutable"], "launch")

    def test_add_refuses_a_clone_without_remote(self):
        self._git("remote", "remove", "origin")
        self.assertEqual(self._main(["add", str(self.clone)]), 1)
        self.assertFalse(self._launcher().exists())

    def test_remove_drops_the_launcher(self):
        self._main(["add", str(self.clone)])
        self.assertEqual(self._main(["remove", "calendar"]), 0)
        self.assertFalse(self._launcher().exists())
        self.assertEqual(AppRegistry.default().apps(), [])

    def test_sync_recreates_missing_launchers(self):
        self._main(["add", str(self.clone)])
        subprocess.run(["trash", str(self._launcher())], check=True)
        self.assertEqual(self._main(["sync"]), 0)
        self.assertTrue(self._launcher().exists())


if __name__ == "__main__":
    unittest.main()
