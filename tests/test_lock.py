import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from installer.errors import InstallError
from installer.lock import InstallLock, Launch, LockOwner


class FakeProcesses:
    def __init__(self, table):
        self._table = table

    def parent(self, pid):
        return self._table.get(pid)


class LockOwnerTest(unittest.TestCase):
    def test_caller_is_the_first_ancestor_that_is_not_a_shell(self):
        processes = FakeProcesses({10: (9, "Python"), 9: (8, "zsh"), 8: (7, "login"), 7: (1, "Terminal")})
        owner = LockOwner.of_process(Launch.ICON, processes, pid=10, terminal="ttys004")
        self.assertEqual((owner.pid, owner.caller, owner.terminal), (10, "Terminal", "ttys004"))

    def test_no_caller_when_only_shells_lead_to_launchd(self):
        processes = FakeProcesses({10: (9, "Python"), 9: (1, "zsh")})
        self.assertIsNone(LockOwner.of_process(Launch.COMMAND, processes, pid=10, terminal=None).caller)

    def test_describes_every_fact_on_its_own_line(self):
        started = datetime(2026, 11, 6, 12, 30).timestamp()
        owner = LockOwner(pid=48211, started=started, launch=Launch.ICON, caller="Terminal", terminal="ttys004")
        self.assertEqual(owner.describe("TaskCalendar", now=started + 6 * 60), [
            "способ: иконка Install TaskCalendar.app",
            "откуда: Terminal",
            "терминал: ttys004",
            "начало: 12:30, 6 мин назад",
            "процесс: 48211",
        ])

    def test_command_without_terminal_or_caller(self):
        started = datetime(2026, 11, 6, 9, 5).timestamp()
        owner = LockOwner(pid=7, started=started, launch=Launch.COMMAND, caller=None, terminal=None)
        self.assertEqual(owner.describe("TaskCalendar", now=started + 20), [
            "способ: команда install-on-iphone run",
            "начало: 09:05, только что",
            "процесс: 7",
        ])


class InstallLockTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "app.lock"
        self.owner = LockOwner(pid=48211, started=time.time(), launch=Launch.ICON, caller="Terminal",
                               terminal="ttys004")
        self.other = LockOwner(pid=1, started=time.time(), launch=Launch.COMMAND, caller=None, terminal=None)

    def test_second_install_names_the_first_one(self):
        with InstallLock(self.path, "TaskCalendar", self.owner):
            with self.assertRaises(InstallError) as raised:
                with InstallLock(self.path, "TaskCalendar", self.other):
                    pass
        lines = str(raised.exception).splitlines()
        self.assertEqual(lines[0], "TaskCalendar уже ставится")
        self.assertIn("  откуда: Terminal", lines)
        self.assertIn("  процесс: 48211", lines)

    def test_owner_that_has_not_written_itself_yet(self):
        with InstallLock(self.path, "TaskCalendar", self.owner):
            self.path.write_text("")
            with self.assertRaises(InstallError) as raised:
                with InstallLock(self.path, "TaskCalendar", self.other):
                    pass
        self.assertEqual(str(raised.exception), "TaskCalendar уже ставится")

    def test_free_again_after_release(self):
        with InstallLock(self.path, "TaskCalendar", self.owner):
            pass
        with InstallLock(self.path, "TaskCalendar", self.other):
            pass


if __name__ == "__main__":
    unittest.main()
