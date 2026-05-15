from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any


ENV_CONFIG = "CC_WEB_MCP_CONFIG"


def default_user_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "cc-web-mcp" / "config.json"


def default_config_text() -> str:
    return resources.files("cc_web_mcp.data").joinpath("default_config.json").read_text(encoding="utf-8")


def default_config_dict() -> dict[str, Any]:
    data = json.loads(default_config_text())
    if not isinstance(data, dict):
        raise ValueError("default_config.json must contain a JSON object")
    return data


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_value = os.environ.get(ENV_CONFIG)
    if env_value:
        return Path(env_value).expanduser()
    return default_user_config_path()


def ensure_user_config(path: str | Path | None = None) -> tuple[Path, bool]:
    config_path = resolve_config_path(path)
    if config_path.exists():
        return config_path, False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(default_config_text(), encoding="utf-8")
    return config_path, True
