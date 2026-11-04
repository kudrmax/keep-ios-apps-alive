from __future__ import annotations

import json
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

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
        raise InstallError(f"в {root} нет ни .xcworkspace, ни .xcodeproj")


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

    def __init__(self, shell: Shell, root: Path, derived_data: Path, packages: Path, configuration: str):
        self._shell = shell
        self._container = Container.find(root)
        self._root = root
        self._derived_data = derived_data
        self._packages = packages
        self._configuration = configuration

    @property
    def name(self) -> str:
        return self._container.name

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

    def build(self, scheme: str, team: Optional[str], device_udid: str, log: Path) -> bool:
        args = self._build_args(scheme, team) + [
            "-destination", f"id={device_udid}", "-allowProvisioningUpdates", "build"]
        return self._shell.run_logged(["xcodebuild", *args], log, cwd=self._root)

    def _container_args(self) -> List[str]:
        return [self._container.flag, str(self._container.path)]

    def _build_args(self, scheme: str, team: Optional[str]) -> List[str]:
        args = self._container_args() + [
            "-scheme", scheme,
            "-configuration", self._configuration,
            "-derivedDataPath", str(self._derived_data),
            "-clonedSourcePackagesDirPath", str(self._packages),
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
