from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .util import PROJECT_ROOT, PipelineError, resolve_path


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "rom.toml"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, data: dict[str, Any], source: Path):
        self.data = data
        self.source = source

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        if not isinstance(value, dict):
            raise PipelineError(f"configuration section [{name}] must be a table")
        return value

    def path(self, dotted: str, default: str | None = None) -> Path:
        value = self.get(dotted, default)
        if value is None:
            raise PipelineError(f"missing path configuration: {dotted}")
        return resolve_path(value)

    def project_path(self, dotted: str, default: str | None = None) -> Path:
        value = self.get(dotted, default)
        if value is None:
            raise PipelineError(f"missing path configuration: {dotted}")
        p = Path(value)
        if p.is_absolute():
            return p.resolve()
        return (PROJECT_ROOT / p).resolve()


def load_config(path: Path | None = None, local: Path | None = None) -> Config:
    source = path or DEFAULT_CONFIG
    if not source.is_file():
        raise PipelineError(f"configuration not found: {source}")
    with source.open("rb") as f:
        data = tomllib.load(f)
    local_path = local or (PROJECT_ROOT / "config" / "local.toml")
    if local_path.is_file():
        with local_path.open("rb") as f:
            data = _merge(data, tomllib.load(f))
    return Config(data, source)
