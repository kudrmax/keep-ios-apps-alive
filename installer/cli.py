from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .config import InstallConfig
from .console import Console
from .errors import InstallError
from .installer import Installer
from .launcher import LauncherApp
from .lock import Launch
from .registry import AppRegistry, ProjectName
from .shell import Shell

DEFAULT_APPLICATIONS = Path.home() / "Applications"


class Commands:
    def __init__(self, registry: AppRegistry, applications: Path):
        self._registry = registry
        self._applications = applications

    def add(self, clone: Path, name: Optional[str], **options: Optional[str]) -> None:
        clone = clone.expanduser().resolve()
        self._check_clone(clone)
        app = InstallConfig(name=name or ProjectName.guess(clone), clone=str(clone), **options)
        self._registry.put(app)
        launcher = self._launcher(app)
        launcher.create()
        print(f"✔ {app.name} добавлен")
        print(f"  иконка: {launcher.path}")
        print(f"  список: {self._registry.path}")

    def remove(self, name: str) -> None:
        app = self._registry.remove(name)
        self._launcher(app).remove()
        print(f"✔ {app.name} убран из списка, иконка в корзине")

    def list(self) -> None:
        apps = self._registry.apps()
        if not apps:
            print("Список пуст. Добавить: install-on-iphone add <папка проекта>")
            return
        for app in apps:
            launcher = self._launcher(app)
            print(app.name)
            print(f"  проект: {app.clone}")
            print(f"  иконка: {launcher.path if launcher.path.exists() else 'нет — install-on-iphone sync'}")
            for key, value in self._options(app):
                print(f"  {key}: {value}")

    def sync(self) -> None:
        apps = self._registry.apps()
        for app in apps:
            self._launcher(app).create()
            print(f"✔ {app.name}")
        if not apps:
            print("Список пуст. Добавить: install-on-iphone add <папка проекта>")

    def run(self, name: str) -> int:
        app = self._registry.get(name)
        console = Console(app.name)
        try:
            Installer(app, Shell(), console, Launch.COMMAND).run()
        except InstallError as error:
            console.failure(str(error))
            return 1
        return 0

    def _launcher(self, app: InstallConfig) -> LauncherApp:
        return LauncherApp(app, self._applications, register=self._applications == DEFAULT_APPLICATIONS)

    @staticmethod
    def _options(app: InstallConfig) -> List[tuple]:
        labels = {"branch": "ветка", "scheme": "схема", "team": "команда", "iphone": "айфон", "xcode": "Xcode",
                  "configuration": "конфигурация", "remote": "remote"}
        defaults = InstallConfig(name=app.name, clone=app.clone)
        return [(label, getattr(app, key)) for key, label in labels.items()
                if getattr(app, key) != getattr(defaults, key)]

    @staticmethod
    def _check_clone(clone: Path) -> None:
        if subprocess.run(["git", "-C", str(clone), "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
            raise InstallError(f"{clone} — не git-репозиторий")
        if subprocess.run(["git", "-C", str(clone), "remote", "get-url", "origin"], capture_output=True).returncode != 0:
            raise InstallError(f"у {clone} нет remote origin — сначала подключить GitHub")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="install-on-iphone",
        description="Иконки «Install <Имя>.app»: нажал — на айфон встаёт свежая основная ветка проекта с GitHub.")
    commands = root.add_subparsers(dest="command", required=True, metavar="команда")

    add = commands.add_parser("add", help="добавить приложение и создать его иконку (повторный add — обновить)")
    add.add_argument("clone", type=Path, help="папка git-клона проекта")
    add.add_argument("--name", help="имя в иконке (по умолчанию — имя Xcode-проекта)")
    add.add_argument("--branch", help="ветка (по умолчанию основная: main или master)")
    add.add_argument("--scheme", help="схема, если их несколько")
    add.add_argument("--team", help="команда подписи, если в Xcode их несколько")
    add.add_argument("--iphone", help="имя айфона, если сопряжено несколько")
    add.add_argument("--xcode", help="путь к Xcode.app, если автовыбор не подходит")

    remove = commands.add_parser("remove", help="убрать приложение из списка, иконку — в корзину")
    remove.add_argument("name")

    commands.add_parser("list", help="показать настроенные приложения")
    commands.add_parser("sync", help="пересоздать все иконки по списку (после обновления этого репозитория)")

    run = commands.add_parser("run", help="поставить приложение прямо в этом терминале, без иконки")
    run.add_argument("name")
    return root


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    applications = Path(os.environ.get("INSTALL_ON_IPHONE_APPLICATIONS", str(DEFAULT_APPLICATIONS)))
    commands = Commands(AppRegistry.default(), applications)
    try:
        if args.command == "add":
            commands.add(args.clone, args.name, branch=args.branch, scheme=args.scheme, team=args.team,
                         iphone=args.iphone, xcode=args.xcode)
        elif args.command == "remove":
            commands.remove(args.name)
        elif args.command == "list":
            commands.list()
        elif args.command == "sync":
            commands.sync()
        elif args.command == "run":
            return commands.run(args.name)
    except InstallError as error:
        print(f"✖ {error}", file=sys.stderr)
        return 1
    return 0
