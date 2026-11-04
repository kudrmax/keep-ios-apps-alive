from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .config import InstallConfig

TOOL_ROOT = Path(__file__).resolve().parent.parent
ICON_SIZES = [16, 32, 128, 256, 512]

LAUNCHER = """#!/bin/bash
open -a Terminal "$(dirname "$0")/../Resources/install.command"
"""

COMMAND = """#!/bin/bash
cd "$(dirname "$0")" && exec /usr/bin/python3 -B install_on_iphone.py config.json
"""


class LauncherApp:
    """"Install <Name>.app": a plain bundle whose executable is a shell script that opens Terminal with the installer.
    It carries its own copy of the installer and its config, so it keeps working whatever happens to this repository."""

    def __init__(self, config: InstallConfig, folder: Path, register: bool = True):
        self._config = config
        self._register_with_system = register
        self.path = folder / f"Install {config.name}.app"
        self._contents = self.path / "Contents"
        self._resources = self._contents / "Resources"

    def create(self) -> None:
        self.remove()
        (self._contents / "MacOS").mkdir(parents=True)
        self._resources.mkdir()
        self._write_executable(self._contents / "MacOS/launch", LAUNCHER)
        self._write_executable(self._resources / "install.command", COMMAND)
        shutil.copy2(TOOL_ROOT / "install_on_iphone.py", self._resources)
        shutil.copytree(TOOL_ROOT / "installer", self._resources / "installer",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self._config.save(self._resources / "config.json")
        has_icon = AppIcon(self._config.clone_path).write(self._resources / "AppIcon.icns")
        self._write_info_plist(has_icon)
        if self._register_with_system:
            self._register()

    def remove(self) -> None:
        if self.path.exists():
            subprocess.run(["trash", str(self.path)], check=True)

    def _write_info_plist(self, has_icon: bool) -> None:
        slug = re.sub(r"[^A-Za-z0-9-]", "-", self._config.name)
        info = {
            "CFBundleExecutable": "launch",
            "CFBundleIdentifier": f"local.install-on-iphone.{slug}",
            "CFBundleName": f"Install {self._config.name}",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "LSUIElement": True,
        }
        if has_icon:
            info["CFBundleIconFile"] = "AppIcon"
        with (self._contents / "Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)

    def _register(self) -> None:
        """Makes Spotlight and Launchpad notice the new or rebuilt app right away."""
        lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
                      "/Support/lsregister")
        subprocess.run([lsregister, "-f", str(self.path)], capture_output=True)

    @staticmethod
    def _write_executable(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)


class AppIcon:
    """The project's own app icon, so every launcher looks like the app it installs."""

    def __init__(self, clone: Path):
        self._clone = clone

    def write(self, target: Path) -> bool:
        source = self._largest_icon()
        if source is None:
            return False
        with tempfile.TemporaryDirectory() as folder:
            iconset = Path(folder) / "AppIcon.iconset"
            iconset.mkdir()
            for size in ICON_SIZES:
                self._resize(source, size, iconset / f"icon_{size}x{size}.png")
                self._resize(source, size * 2, iconset / f"icon_{size}x{size}@2x.png")
            return subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)],
                                  capture_output=True).returncode == 0

    def _largest_icon(self) -> Optional[Path]:
        listing = subprocess.run(["git", "-C", str(self._clone), "ls-files", "-z", "*AppIcon.appiconset/*.png"],
                                 capture_output=True, text=True).stdout
        icons = [self._clone / name for name in listing.split("\0") if name]
        return max(icons, key=lambda icon: icon.stat().st_size) if icons else None

    @staticmethod
    def _resize(source: Path, size: int, target: Path) -> None:
        subprocess.run(["sips", "-z", str(size), str(size), str(source), "--out", str(target)],
                       capture_output=True, check=True)
