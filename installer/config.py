from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InstallConfig:
    name: str
    clone: str
    remote: str = "origin"
    branch: Optional[str] = None
    configuration: str = "Release"
    scheme: Optional[str] = None
    team: Optional[str] = None
    iphone: Optional[str] = None
    xcode: Optional[str] = None
    # The folder of the Xcode project (or its project.yml) inside the clone, when it is not the root.
    project: str = "."

    @classmethod
    def load(cls, path: Path) -> "InstallConfig":
        return cls(**json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n")

    @property
    def clone_path(self) -> Path:
        return Path(self.clone).expanduser()

    @property
    def lock(self) -> Path:
        digest = hashlib.sha1(str(self.clone_path).encode()).hexdigest()[:8]
        return Path(tempfile.gettempdir()) / f"install-on-iphone-{digest}.lock"

    @property
    def failure_log(self) -> Path:
        return Path.home() / "Library/Logs/install-on-iphone" / f"{self.name}.log"
