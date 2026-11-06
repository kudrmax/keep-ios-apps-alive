#!/usr/bin/env python3
"""Builds the latest upstream branch of a project and installs it on the iPhone.
Usage: install_on_iphone.py <config.json>"""
import sys
from pathlib import Path

from installer.config import InstallConfig
from installer.console import Console
from installer.errors import InstallError
from installer.installer import Installer
from installer.lock import Launch
from installer.shell import Shell


def main() -> int:
    config = InstallConfig.load(Path(sys.argv[1]))
    console = Console(config.name)
    try:
        Installer(config, Shell(), console, Launch.ICON).run()
    except InstallError as error:
        console.failure(str(error))
        return 1
    except KeyboardInterrupt:
        console.failure("остановлено")
        return 130
    except Exception as error:
        console.failure(f"непредвиденная ошибка: {error}")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
