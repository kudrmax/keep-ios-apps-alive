from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .errors import InstallError
from .shell import Shell


@dataclass(frozen=True)
class Device:
    identifier: str
    udid: str
    name: str
    wired: bool
    connected: bool


class DevicePicker:
    @staticmethod
    def pick(devices: List[Device], preferred_name: Optional[str]) -> Device:
        if preferred_name:
            devices = [device for device in devices if device.name == preferred_name]
            if not devices:
                raise InstallError(f"айфон «{preferred_name}» не сопряжён с этим Mac")
        if not devices:
            raise InstallError("нет сопряжённого айфона — подключить проводом один раз и нажать «Доверять»")
        return sorted(devices, key=lambda device: (not device.connected, not device.wired))[0]


class Devices:
    def __init__(self, shell: Shell):
        self._shell = shell

    def paired_iphones(self) -> List[Device]:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "devices.json"
            result = self._shell.run(["xcrun", "devicectl", "list", "devices", "--json-output", str(output)])
            if result.returncode != 0:
                raise InstallError(f"devicectl не отвечает: {result.stderr.strip()[-300:]}")
            listing = json.loads(output.read_text())
        return [self._device(entry) for entry in listing["result"]["devices"] if self._is_paired_iphone(entry)]

    def reachable(self, device: Device) -> bool:
        """Xcode can build for the iPhone and install on it: its tunnel to it is up. `devicectl device info` answers
        from what it remembers even while the tunnel is down, so it says nothing about that."""
        return any(found.identifier == device.identifier and found.connected for found in self.paired_iphones())

    def install(self, device: Device, app: Path) -> None:
        result = self._shell.run(["xcrun", "devicectl", "device", "install", "app", "--device", device.identifier,
                                  str(app)])
        if result.returncode != 0:
            raise InstallError(f"айфон не принял приложение: {result.stderr.strip()[-500:]}")

    @staticmethod
    def _is_paired_iphone(entry: dict) -> bool:
        return (entry.get("hardwareProperties", {}).get("deviceType") == "iPhone"
                and entry.get("connectionProperties", {}).get("pairingState") == "paired")

    @staticmethod
    def _device(entry: dict) -> Device:
        connection = entry["connectionProperties"]
        return Device(
            identifier=entry["identifier"],
            udid=entry["hardwareProperties"]["udid"],
            name=entry["deviceProperties"].get("name", "iPhone"),
            wired=connection.get("transportType") == "wired",
            connected=connection.get("tunnelState") == "connected",
        )


class XcodeWaker:
    """Xcode keeps a Wi-Fi iPhone's connection alive; it is opened only when needed and closed if it was not running."""

    TRIES = 12
    PAUSE_SECONDS = 5

    def __init__(self, shell: Shell, devices: Devices):
        self._shell = shell
        self._devices = devices
        self._opened = False

    def wake(self, device: Device, xcode_app: Path, on_wait) -> bool:
        """Whether the iPhone came on the line while Xcode was open."""
        if not self._shell.succeeds(["pgrep", "-x", "Xcode"]):
            self._opened = True
        self._shell.run(["open", "-g", "-a", str(xcode_app)])
        for attempt in range(1, self.TRIES + 1):
            time.sleep(self.PAUSE_SECONDS)
            if self._devices.reachable(device):
                return True
            on_wait(attempt * self.PAUSE_SECONDS)
        return False

    def close(self) -> None:
        if self._opened:
            self._shell.run(["osascript", "-e", 'quit app id "com.apple.dt.Xcode"'])
            self._opened = False
