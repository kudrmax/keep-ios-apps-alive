import tempfile
import unittest
from pathlib import Path

from installer.progress import BuildActivity
from installer.shell import Shell
from installer.xcode import ProjectGenerator


class BuildActivityTest(unittest.TestCase):
    def test_swift_file(self):
        line = "SwiftCompile normal arm64 Compiling\\ CalendarView.swift /tmp/App/CalendarView.swift (in target 'App')"
        self.assertEqual(BuildActivity.describe(line), "компилирую CalendarView.swift")

    def test_signing(self):
        self.assertEqual(BuildActivity.describe("CodeSign /tmp/Build/App.app (in target 'App')"), "подписываю")

    def test_packages(self):
        self.assertEqual(BuildActivity.describe("Resolve Package Graph"), "подтягиваю Swift-пакеты")

    def test_noise(self):
        self.assertIsNone(BuildActivity.describe("    cd /tmp/project"))


class ProjectGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_needed_for_spec_without_project(self):
        (self.root / "project.yml").write_text("name: App\n")
        self.assertTrue(ProjectGenerator(Shell()).needed(self.root))

    def test_not_needed_when_project_is_in_git(self):
        (self.root / "project.yml").write_text("name: App\n")
        (self.root / "App.xcodeproj").mkdir()
        self.assertFalse(ProjectGenerator(Shell()).needed(self.root))

    def test_not_needed_without_spec(self):
        self.assertFalse(ProjectGenerator(Shell()).needed(self.root))


if __name__ == "__main__":
    unittest.main()
