from __future__ import annotations

import plistlib
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

from .shell import Shell

PROFILE_FOLDERS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]


class ProfileMatcher:
    """Apple requires an extension's bundle id to start with its app's id and a dot, so those profiles are the app's."""

    @staticmethod
    def matches(application_identifier: str, team: str, bundle_ids: Iterable[str]) -> bool:
        prefix, _, bundle_id = application_identifier.partition(".")
        return prefix == team and any(bundle_id == own or bundle_id.startswith(f"{own}.") for own in bundle_ids)


class ProfileRefresh:
    """A free Apple account signs an app for 7 days, and Xcode reuses a cached profile until it expires.
    Setting this app's cached profiles aside makes the build fetch fresh ones, so the 7 days count from now.
    They are put back if the build fails and moved to the Trash once it succeeds."""

    def __init__(self, shell: Shell, team: str, bundle_ids: List[str], folders: Optional[List[Path]] = None):
        self._shell = shell
        self._team = team
        self._bundle_ids = bundle_ids
        self._folders = folders if folders is not None else PROFILE_FOLDERS
        self._stash = Path(tempfile.mkdtemp(prefix="install-on-iphone-profiles-"))
        self._moved: List[Path] = []

    def set_aside(self) -> List[str]:
        names = []
        for profile in self._cached_profiles():
            application_identifier = self._application_identifier(profile)
            if application_identifier and ProfileMatcher.matches(application_identifier, self._team, self._bundle_ids):
                shutil.move(str(profile), str(self._stash / profile.name))
                self._moved.append(profile)
                names.append(application_identifier.partition(".")[2])
        return names

    def restore(self) -> None:
        for original in self._moved:
            shutil.move(str(self._stash / original.name), str(original))
        self._moved = []
        self._discard_stash()

    def commit(self) -> None:
        self._moved = []
        self._discard_stash()

    def _discard_stash(self) -> None:
        self._shell.run(["trash", str(self._stash)])

    def _cached_profiles(self) -> List[Path]:
        return [profile for folder in self._folders if folder.is_dir()
                for profile in sorted(folder.glob("*.mobileprovision"))]

    def _application_identifier(self, profile: Path) -> str:
        decoded = self._shell.run(["security", "cms", "-D", "-i", str(profile)])
        if decoded.returncode != 0:
            return ""
        return plistlib.loads(decoded.stdout.encode()).get("Entitlements", {}).get("application-identifier", "")
