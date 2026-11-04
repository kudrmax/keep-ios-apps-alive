#!/usr/bin/env python3
"""Creates a one-click "Install <Name>.app" for a project: it opens Terminal and installs the latest build on the iPhone.
Usage: make_app.py <project clone> [--name N] [--scheme S] [--team T] [--iphone NAME] [--xcode APP] [--branch B] [--output DIR]"""
import argparse
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from installer.config import InstallConfig
from installer.errors import InstallError
from installer.xcode import Container

TOOL_ROOT = Path(__file__).resolve().parent
ICON_SIZES = [16, 32, 128, 256, 512]

LAUNCHER = """#!/bin/bash
open -a Terminal "$(dirname "$0")/../Resources/install.command"
"""

COMMAND = """#!/bin/bash
cd "$(dirname "$0")" && exec /usr/bin/python3 -B install_on_iphone.py config.json
"""


class AppBundle:
    def __init__(self, config: InstallConfig, output: Path):
        self._config = config
        self.path = output / f"Install {config.name}.app"
        self._contents = self.path / "Contents"
        self._resources = self._contents / "Resources"

    def create(self) -> None:
        if self.path.exists():
            subprocess.run(["trash", str(self.path)], check=True)
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

    @staticmethod
    def _write_executable(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)


class AppIcon:
    """The project's own app icon, so every installer looks like the app it installs."""

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

    def _largest_icon(self):
        listing = subprocess.run(["git", "-C", str(self._clone), "ls-files", "-z", "*AppIcon.appiconset/*.png"],
                                 capture_output=True, text=True).stdout
        icons = [self._clone / name for name in listing.split("\0") if name]
        return max(icons, key=lambda icon: icon.stat().st_size) if icons else None

    @staticmethod
    def _resize(source: Path, size: int, target: Path) -> None:
        subprocess.run(["sips", "-z", str(size), str(size), str(source), "--out", str(target)],
                       capture_output=True, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clone", type=Path, help="папка git-клона проекта")
    parser.add_argument("--name", help="имя приложения в иконке (по умолчанию — имя Xcode-проекта)")
    parser.add_argument("--scheme", help="схема, если их несколько")
    parser.add_argument("--team", help="команда подписи, если в Xcode их несколько")
    parser.add_argument("--iphone", help="имя айфона, если сопряжено несколько")
    parser.add_argument("--xcode", help="путь к Xcode.app, если автовыбор не подходит")
    parser.add_argument("--branch", default="main", help="ветка на GitHub (по умолчанию main)")
    parser.add_argument("--output", type=Path, default=Path.home() / "Applications", help="куда положить иконку")
    args = parser.parse_args()

    clone = args.clone.expanduser().resolve()
    try:
        name = args.name or Container.find(clone).name
    except InstallError as error:
        print(f"✖ {error}", file=sys.stderr)
        return 1
    config = InstallConfig(name=name, clone=str(clone), branch=args.branch, scheme=args.scheme, team=args.team,
                           iphone=args.iphone, xcode=args.xcode)
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = AppBundle(config, args.output)
    bundle.create()
    print(f"✔ {bundle.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
