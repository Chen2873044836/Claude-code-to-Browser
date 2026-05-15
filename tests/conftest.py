from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_user_environment(monkeypatch, tmp_path):
    """Keep tests independent from local Claude and user config state."""
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    localappdata = tmp_path / "localappdata"
    xdg_config = tmp_path / "xdg-config"
    for path in (home, appdata, localappdata, xdg_config):
        path.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.delenv("CC_WEB_MCP_CONFIG", raising=False)

    model_env_names = (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "CLAUDE_CODE_MODEL",
    )
    for name in model_env_names:
        monkeypatch.delenv(name, raising=False)

    os.environ["PYTHONUTF8"] = "1"
