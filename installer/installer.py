from __future__ import annotations

import fcntl
import plistlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import List

from .config import InstallConfig
from .console import Console
from .devices import Device, DevicePicker, Devices, XcodeWaker
from .errors import InstallError
from .profiles import ProfileRefresh
from .shell import Shell
from .source import GitSource, Workspace
from .xcode import PlatformCheck, SchemePicker, TeamPicker, XcodeInstall, XcodeInstalls, XcodeProject

LOG_TAIL_LINES = 40


class Installer:
    def __init__(self, config: InstallConfig, shell: Shell, console: Console):
        self._config = config
        self._shell = shell
        self._console = console
        self._source = GitSource(shell, config.clone_path, config.remote, config.branch)
        self._devices = Devices(shell)
        self._waker = XcodeWaker(shell, self._devices)

    def run(self) -> None:
        with self._config.lock.open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstallError(f"{self._config.name} уже ставится в другом окне")
            try:
                self._install()
            finally:
                self._waker.close()

    def _install(self) -> None:
        console = self._console
        upstream = self._source.upstream

        console.step(f"Сверяю {upstream} с GitHub")
        online = self._source.fetch()
        if not online:
            console.warn(f"GitHub недоступен — ставлю {upstream}, каким он был при последней синхронизации")
        unpushed = self._source.unpushed_commits()
        if unpushed:
            console.warn(f"в локальном {self._source.branch} {unpushed} незапушенных коммитов — в сборку они не попадут")
        revision = self._source.describe(upstream)
        console.info(revision)

        console.step("Ищу айфон")
        xcodes = self._xcodes()
        device = DevicePicker.pick(self._devices.paired_iphones(), self._config.iphone)
        console.info(f"{device.name} ({'провод' if device.wired else 'Wi-Fi'})")
        if not self._devices.reachable(device):
            console.info("Айфон не отвечает — открываю Xcode, чтобы он поднял соединение")
            console.info("(айфон должен быть разблокирован и в той же Wi-Fi-сети, что и Mac)")
            self._waker.wake(device, xcodes[0].app, lambda seconds: console.info(f"…жду ({seconds} с)"))
        console.info("Соединение есть")

        with Workspace(self._shell, self._source) as workspace:
            self._build_and_install(workspace, xcodes, device, online, revision)

    def _build_and_install(self, workspace: Workspace, xcodes: List[XcodeInstall], device: Device, online: bool,
                           revision: str) -> None:
        console = self._console
        console.step("Читаю проект")
        project = XcodeProject(self._shell, workspace.tree, workspace.derived_data, self._config.configuration)
        scheme = SchemePicker.pick(project.schemes(), project.name, self._config.scheme)
        xcode = self._xcode_for(project, xcodes, scheme, device)
        project = project.using(xcode)
        app = project.app(scheme, self._config.team)
        team = self._config.team or app.team
        if not team:
            team = TeamPicker.pick(TeamPicker.signed_in_teams(self._shell), None)
            app = replace(project.app(scheme, team), team=team)
        console.info(f"Xcode {xcode.version}, схема {scheme}, приложение {app.path.name}, команда {team}")

        refresh = ProfileRefresh(self._shell, team, app.bundle_ids)
        if online:
            console.step("Обновляю подпись (7 дней с этой установки)")
            for bundle_id in refresh.set_aside():
                console.info(f"старый профиль {bundle_id} убран")
        else:
            console.warn("без сети подпись не продлить — остаётся прежний срок")

        console.step(f"Собираю {self._config.configuration} для {device.name}")
        if not project.build(scheme, team, device.udid, workspace.log):
            refresh.restore()
            log = workspace.log.read_text(errors="replace")
            console.info("\n".join(log.splitlines()[-LOG_TAIL_LINES:]))
            saved = self._save_failure_log(workspace.log)
            raise PlatformCheck.error(log) or InstallError(f"сборка не прошла, полный лог: {saved}")
        refresh.commit()
        console.info(f"Собрано, подпись до {self._expiry(app.path)}")

        console.step("Ставлю на айфон")
        self._devices.install(device, app.path)
        console.success(f"{app.product_name} установлен на {device.name} ({revision})")

    def _save_failure_log(self, log: Path) -> Path:
        target = self._config.failure_log
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(log, target)
        return target

    def _xcodes(self) -> List[XcodeInstall]:
        if self._config.xcode:
            forced = [xcode for xcode in XcodeInstalls.find(self._shell) if xcode.app == Path(self._config.xcode)]
            if not forced:
                raise InstallError(f"Xcode {self._config.xcode} не найден")
            return forced
        xcodes = XcodeInstalls.find(self._shell)
        if not xcodes:
            raise InstallError("на этом Mac нет Xcode")
        return xcodes

    @staticmethod
    def _xcode_for(project: XcodeProject, xcodes: List[XcodeInstall], scheme: str, device: Device) -> XcodeInstall:
        for xcode in xcodes:
            if project.using(xcode).supports(scheme, device.udid):
                return xcode
        versions = ", ".join(xcode.version for xcode in xcodes)
        raise InstallError(f"ни один Xcode ({versions}) не собирает {scheme} под {device.name} — "
                           "открыть проект в Xcode и посмотреть, что он пишет про айфон")

    def _expiry(self, app: Path) -> str:
        decoded = self._shell.run(["security", "cms", "-D", "-i", str(app / "embedded.mobileprovision")])
        if decoded.returncode != 0:
            return "неизвестно"
        return plistlib.loads(decoded.stdout.encode()).get("ExpirationDate", "неизвестно").strftime("%d.%m %H:%M")
