"""Configuration loading.

All tunables (universe, fees, risk profiles, strategy params, data-source
priority) live in ``config/settings.yaml``. This module loads that file into a
small dotted-access wrapper and resolves relative paths against the project root.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Project root = the directory that contains this package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class Config:
    """Thin wrapper over the parsed YAML config.

    Access values either by dotted path (``cfg.get("data.cache_db")``) or by
    indexing into :pyattr:`raw`. Path-like settings can be resolved to absolute
    paths under the project root with :meth:`path`.
    """

    def __init__(self, raw: dict[str, Any], path: Path | None = None):
        self.raw = raw
        self.source_path = path

    # -- access ------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def path(self, dotted: str, default: str | None = None) -> Path:
        """Resolve a config value that is a path, relative to the project root."""
        value = self.get(dotted, default)
        if value is None:
            raise KeyError(f"No path configured at '{dotted}'")
        p = Path(value)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    # -- convenience -------------------------------------------------------
    @property
    def currency(self) -> str:
        return self.get("currency", "MAD")

    @property
    def demo_tickers(self) -> list[str]:
        return list(self.get("universe.demo_tickers", []))

    @property
    def benchmark(self) -> str:
        return self.get("universe.benchmark", "CSE-COMPOSITE")

    def risk_profile(self, name: str) -> dict[str, Any]:
        profiles = self.get("risk_profiles", {})
        if name not in profiles:
            raise KeyError(f"Unknown risk profile '{name}'. Known: {list(profiles)}")
        return dict(profiles[name])

    @property
    def risk_profile_names(self) -> list[str]:
        return list(self.get("risk_profiles", {}).keys())


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from *path* (defaults to ``config/settings.yaml``)."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Config(raw, path=p)
