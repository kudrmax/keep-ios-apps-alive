from __future__ import annotations

import fcntl
import plistlib
from dataclasses import replace
from pathlib import Path

from .config import InstallConfig
from .console import Console
from .devices import DevicePicker, Devices, XcodeWaker
from .errors import InstallError
from .profiles import ProfileRefresh
from .shell import Shell
from .source import BuildTree, GitSource
from .xcode import PlatformCheck, SchemePicker, TeamPicker, XcodeProject

LOG_TAIL_LINES = 40


class Installer:
    def __init__(self, config: InstallConfig, shell: Shell, console: Console):
        self._config = config
        self._shell = shell
        self._console = console
        cache = config.cache
        self._log = cache / "build.log"
        self._source = GitSource(shell, config.clone_path, config.remote, config.branch)
        self._tree = BuildTree(shell, self._source, cache / "tree")
        self._derived_data = cache / "DerivedData"
        self._packages = cache / "SourcePackages"
        self._devices = Devices(shell)
        self._waker = XcodeWaker(shell, self._devices)

    def run(self) -> None:
        self._config.cache.mkdir(parents=True, exist_ok=True)
        with (self._config.cache / "lock").open("w") as lock:
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

        console.step(f"Скачиваю свежий {upstream}")
        self._source.fetch()
        unpushed = self._source.unpushed_commits()
        if unpushed:
            console.warn(f"в локальном {self._config.branch} {unpushed} незапушенных коммитов — в сборку они не попадут")
        self._tree.checkout()
        revision = self._source.describe(upstream)
        console.info(revision)

        console.step("Читаю проект")
        project = XcodeProject(self._shell, self._tree.path, self._derived_data, self._packages,
                               self._config.configuration)
        scheme = SchemePicker.pick(project.schemes(), project.name, self._config.scheme)
        app = project.app(scheme, self._config.team)
        team = self._config.team or app.team
        if not team:
            team = TeamPicker.pick(TeamPicker.signed_in_teams(self._shell), None)
            app = replace(project.app(scheme, team), team=team)
        console.info(f"Схема {scheme}, приложение {app.path.name}, команда {team}")

        console.step("Ищу айфон")
        device = DevicePicker.pick(self._devices.paired_iphones(), self._config.iphone)
        console.info(f"{device.name} ({'провод' if device.wired else 'Wi-Fi'})")
        if not self._devices.reachable(device):
            console.info("Айфон не отвечает — открываю Xcode, чтобы он поднял соединение")
            console.info("(айфон должен быть разблокирован и в той же Wi-Fi-сети, что и Mac)")
            self._waker.wake(device, lambda seconds: console.info(f"…жду ({seconds} с)"))
        console.info("Соединение есть")

        console.step("Обновляю подпись (7 дней с этой установки)")
        refresh = ProfileRefresh(self._shell, team, app.bundle_ids)
        for bundle_id in refresh.set_aside():
            console.info(f"старый профиль {bundle_id} убран")

        console.step(f"Собираю {self._config.configuration} для {device.name}")
        console.info(f"полный лог: {self._log}")
        if not project.build(scheme, team, device.udid, self._log):
            refresh.restore()
            log = self._log.read_text(errors="replace")
            console.info("\n".join(log.splitlines()[-LOG_TAIL_LINES:]))
            raise PlatformCheck.error(log) or InstallError("сборка не прошла, старые профили возвращены")
        refresh.commit()
        console.info(f"Собрано, подпись до {self._expiry(app.path)}")

        console.step("Ставлю на айфон")
        self._devices.install(device, app.path)
        console.success(f"{app.product_name} установлен на {device.name} ({revision})")

    def _expiry(self, app: Path) -> str:
        decoded = self._shell.run(["security", "cms", "-D", "-i", str(app / "embedded.mobileprovision")])
        if decoded.returncode != 0:
            return "неизвестно"
        return plistlib.loads(decoded.stdout.encode()).get("ExpirationDate", "неизвестно").strftime("%d.%m %H:%M")
