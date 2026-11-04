from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CACHE_ROOT = Path.home() / "Library/Caches/install-on-iphone"


@dataclass(frozen=True)
class InstallConfig:
    name: str
    clone: str
    remote: str = "origin"
    branch: str = "main"
    configuration: str = "Release"
    scheme: Optional[str] = None
    team: Optional[str] = None
    iphone: Optional[str] = None

    @classmethod
    def load(cls, path: Path) -> "InstallConfig":
        return cls(**json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n")

    @property
    def clone_path(self) -> Path:
        return Path(self.clone).expanduser()

    @property
    def cache(self) -> Path:
        digest = hashlib.sha1(str(self.clone_path).encode()).hexdigest()[:8]
        return CACHE_ROOT / f"{self.clone_path.name}-{digest}"
