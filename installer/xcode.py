from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .errors import InstallError
from .shell import Shell


@dataclass(frozen=True)
class Container:
    flag: str
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @classmethod
    def find(cls, root: Path) -> "Container":
        workspaces = sorted(root.glob("*.xcworkspace"))
        if workspaces:
            return cls("-workspace", workspaces[0])
        projects = sorted(root.glob("*.xcodeproj"))
        if projects:
            return cls("-project", projects[0])
        raise InstallError(f"в {root} нет ни .xcworkspace, ни .xcodeproj, ни project.yml для XcodeGen")


class ProjectGenerator:
    """Projects that keep their .xcodeproj out of git and generate it from project.yml with XcodeGen."""

    SPEC = "project.yml"
    SEARCH_PATH = ["/opt/homebrew/bin", "/usr/local/bin"]

    def __init__(self, shell: Shell):
        self._shell = shell

    def needed(self, root: Path) -> bool:
        has_container = any(root.glob("*.xcworkspace")) or any(root.glob("*.xcodeproj"))
        return not has_container and (root / self.SPEC).is_file()

    def generate(self, root: Path) -> None:
        xcodegen = shutil.which("xcodegen", path=os.pathsep.join([os.environ.get("PATH", "")] + self.SEARCH_PATH))
        if not xcodegen:
            raise InstallError("проект генерируется XcodeGen, а он не установлен — brew install xcodegen")
        result = self._shell.run([xcodegen, "generate", "--quiet"], cwd=root)
        if result.returncode != 0:
            raise InstallError(f"XcodeGen не сгенерировал проект: {(result.stderr or result.stdout).strip()[-500:]}")


@dataclass(frozen=True)
class XcodeInstall:
    app: Path
    version: str

    @property
    def developer_dir(self) -> Path:
        return self.app / "Contents/Developer"

    @property
    def version_key(self) -> Tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", self.version))


class XcodeInstalls:
    """Every Xcode on this Mac, newest first: one of them may lack the iOS platform of the connected iPhone."""

    @staticmethod
    def find(shell: Shell) -> List[XcodeInstall]:
        found = shell.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.apple.dt.Xcode'"]).stdout.splitlines()
        apps = {Path(path) for path in found if path.endswith(".app")}
        apps |= set(Path("/Applications").glob("Xcode*.app"))
        installs = []
        for app in apps:
            info = app / "Contents/Info.plist"
            if (app / "Contents/Developer").is_dir() and info.is_file():
                with info.open("rb") as stream:
                    installs.append(XcodeInstall(app, plistlib.load(stream).get("CFBundleShortVersionString", "0")))
        return sorted(installs, key=lambda install: install.version_key, reverse=True)


class DestinationCheck:
    @staticmethod
    def supports(destinations: str, device_udid: str) -> bool:
        return any(f"id:{device_udid}" in line and "error:" not in line for line in destinations.splitlines())

    @staticmethod
    def listed(destinations: str, device_udid: str) -> bool:
        """Xcode sees the iPhone at all, fit to build for or not: one it does not list is not on the line with it."""
        return any(f"id:{device_udid}" in line for line in destinations.splitlines())


@dataclass(frozen=True)
class App:
    product_name: str
    path: Path
    bundle_ids: List[str]
    team: str


class SchemePicker:
    @staticmethod
    def pick(schemes: List[str], container_name: str, preferred: Optional[str]) -> str:
        if preferred:
            if preferred not in schemes:
                raise InstallError(f"схемы {preferred} нет в проекте, есть: {', '.join(schemes)}")
            return preferred
        if len(schemes) == 1:
            return schemes[0]
        if container_name in schemes:
            return container_name
        raise InstallError(f"несколько схем ({', '.join(schemes)}) — укажи нужную при создании иконки (--scheme)")


class TeamPicker:
    """Signing team for projects that keep it out of git: the one Xcode is signed in with."""

    @staticmethod
    def pick(teams: Dict[str, str], preferred: Optional[str]) -> str:
        if preferred:
            return preferred
        if len(teams) == 1:
            return next(iter(teams))
        if not teams:
            raise InstallError("в Xcode нет ни одного аккаунта Apple — войти в Xcode → Settings → Accounts")
        listed = ", ".join(f"{team} ({name})" for team, name in teams.items())
        raise InstallError(f"в Xcode несколько команд ({listed}) — укажи нужную при создании иконки (--team)")

    @staticmethod
    def signed_in_teams(shell: Shell) -> Dict[str, str]:
        result = shell.run(["defaults", "export", "com.apple.dt.Xcode", "-"])
        if result.returncode != 0:
            return {}
        accounts = plistlib.loads(result.stdout.encode()).get("IDEProvisioningTeamByIdentifier", {})
        return {team["teamID"]: team.get("teamName", "") for teams in accounts.values() for team in teams}


class XcodeProject:
    APP_PRODUCT = "com.apple.product-type.application"
    BUNDLED_WRAPPERS = ("app", "appex")

    def __init__(self, shell: Shell, root: Path, derived_data: Path, configuration: str):
        self._shell = shell
        self._container = Container.find(root)
        self._root = root
        self._derived_data = derived_data
        self._configuration = configuration

    @property
    def name(self) -> str:
        return self._container.name

    def using(self, xcode: XcodeInstall) -> "XcodeProject":
        return XcodeProject(self._shell.with_developer_dir(xcode.developer_dir), self._root, self._derived_data,
                            self._configuration)

    def destinations(self, scheme: str) -> str:
        return self._shell.run(["xcodebuild", *self._container_args(), "-scheme", scheme, "-showdestinations"],
                               cwd=self._root).stdout

    def supports(self, scheme: str, device_udid: str) -> bool:
        return DestinationCheck.supports(self.destinations(scheme), device_udid)

    def schemes(self) -> List[str]:
        listing = json.loads(self._xcodebuild(self._container_args() + ["-list", "-json"]))
        return listing.get("workspace", listing.get("project", {})).get("schemes", [])

    def app(self, scheme: str, team: Optional[str]) -> App:
        settings = json.loads(self._xcodebuild(
            self._build_args(scheme, team) + ["-destination", "generic/platform=iOS", "-showBuildSettings", "-json"]))
        targets = [entry["buildSettings"] for entry in settings]
        apps = [target for target in targets if target.get("PRODUCT_TYPE") == self.APP_PRODUCT]
        if not apps:
            raise InstallError(f"схема {scheme} не собирает приложение")
        app = apps[0]
        bundle_ids = [target["PRODUCT_BUNDLE_IDENTIFIER"] for target in targets
                      if target.get("WRAPPER_EXTENSION") in self.BUNDLED_WRAPPERS
                      and target.get("PRODUCT_BUNDLE_IDENTIFIER")]
        return App(
            product_name=app.get("PRODUCT_NAME", scheme),
            path=Path(app["TARGET_BUILD_DIR"]) / app["FULL_PRODUCT_NAME"],
            bundle_ids=bundle_ids,
            team=app.get("DEVELOPMENT_TEAM", ""),
        )

    def build(self, scheme: str, team: Optional[str], device_udid: str, log: Path,
              on_line: Callable[[str], None]) -> bool:
        args = self._build_args(scheme, team) + [
            "-destination", f"id={device_udid}", "-allowProvisioningUpdates", "build"]
        return self._shell.run_streamed(["xcodebuild", *args], log, on_line, cwd=self._root)

    def _container_args(self) -> List[str]:
        return [self._container.flag, str(self._container.path)]

    def _build_args(self, scheme: str, team: Optional[str]) -> List[str]:
        args = self._container_args() + [
            "-scheme", scheme,
            "-configuration", self._configuration,
            "-derivedDataPath", str(self._derived_data),
        ]
        return args + ([f"DEVELOPMENT_TEAM={team}"] if team else [])

    def _xcodebuild(self, args: List[str]) -> str:
        result = self._shell.run(["xcodebuild", *args], cwd=self._root)
        if result.returncode != 0:
            raise PlatformCheck.error(result.stderr) or InstallError(
                f"xcodebuild не прочитал проект: {result.stderr.strip()[-500:]}")
        return result.stdout


class PlatformCheck:
    MISSING = re.compile(r"(iOS [\d.]+) is not installed")

    @classmethod
    def error(cls, output: str) -> Optional[InstallError]:
        missing = cls.MISSING.search(output)
        if not missing:
            return None
        return InstallError(f"в Xcode не скачана платформа {missing.group(1)} — Xcode → Settings → Components "
                            "или в терминале: xcodebuild -downloadPlatform iOS")
