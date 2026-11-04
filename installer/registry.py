from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import List

from .config import InstallConfig
from .errors import InstallError

DEFAULT_REGISTRY = Path.home() / ".config/install-on-iphone/apps.json"


class AppRegistry:
    """The user's own list of apps, kept outside the repository: the repository stays free of project names."""

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def default(cls) -> "AppRegistry":
        return cls(Path(os.environ.get("INSTALL_ON_IPHONE_APPS", str(DEFAULT_REGISTRY))))

    def apps(self) -> List[InstallConfig]:
        if not self.path.exists():
            return []
        return [InstallConfig(**entry) for entry in json.loads(self.path.read_text())["apps"]]

    def get(self, name: str) -> InstallConfig:
        for app in self.apps():
            if app.name.lower() == name.lower():
                return app
        known = ", ".join(app.name for app in self.apps()) or "список пуст"
        raise InstallError(f"приложения {name} нет в списке ({known})")

    def put(self, app: InstallConfig) -> None:
        apps = [existing for existing in self.apps() if existing.name.lower() != app.name.lower()]
        self._save(sorted(apps + [app], key=lambda entry: entry.name.lower()))

    def remove(self, name: str) -> InstallConfig:
        app = self.get(name)
        self._save([existing for existing in self.apps() if existing.name != app.name])
        return app

    def _save(self, apps: List[InstallConfig]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entries = [self._compact(app) for app in apps]
        self.path.write_text(json.dumps({"apps": entries}, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _compact(app: InstallConfig) -> dict:
        """Only what differs from the defaults, so the file stays readable and editable by hand."""
        defaults = asdict(InstallConfig(name=app.name, clone=app.clone))
        return {key: value for key, value in asdict(app).items()
                if key in ("name", "clone") or value != defaults[key]}


class ProjectName:
    """The name an app gets when none is given: the Xcode project's, then XcodeGen's, then the folder's."""

    @staticmethod
    def guess(clone: Path) -> str:
        for pattern in ("*.xcworkspace", "*.xcodeproj"):
            found = sorted(clone.glob(pattern))
            if found:
                return found[0].stem
        spec = clone / "project.yml"
        if spec.is_file():
            match = re.search(r"^name:\s*['\"]?([^'\"\n]+)", spec.read_text(), re.MULTILINE)
            if match:
                return match.group(1).strip()
        return clone.name

