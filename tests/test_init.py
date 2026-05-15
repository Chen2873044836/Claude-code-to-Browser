from __future__ import annotations

import json
import sys
from pathlib import Path

from cc_web_mcp import install


def test_init_registers_mcp_with_server_command_not_guard(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(install.subprocess, "run", fake_run)

    summary = install.run_init(
        config_path=tmp_path / "config.json",
        memory_path=tmp_path / "CLAUDE.md",
        settings_path=tmp_path / "settings.json",
        python_command="py -3.11",
    )

    assert len(calls) == 1
    assert calls[0][1:] == [
        "mcp",
        "add",
        "--scope",
        "user",
        "--transport",
        "stdio",
        "cc-web",
        "--",
        sys.executable,
        "-m",
        "cc_web_mcp",
    ]
    assert "cc_web_mcp.hooks.guard" not in " ".join(calls[0])
    assert summary["mcp_registered"] is True


def test_init_uvx_runner_registers_persistent_uvx_command(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(install.subprocess, "run", fake_run)
    monkeypatch.setattr(install.shutil, "which", lambda name: "uvx" if name == "uvx" else None)

    summary = install.run_init(
        config_path=tmp_path / "config.json",
        memory_path=tmp_path / "CLAUDE.md",
        settings_path=tmp_path / "settings.json",
        runner="uvx",
    )

    assert calls[0][1:] == [
        "mcp",
        "add",
        "--scope",
        "user",
        "--transport",
        "stdio",
        "cc-web",
        "--",
        "uvx",
        "cc-web-mcp",
    ]
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    hook_command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert hook_command == "uvx cc-web-mcp hook-guard"
    assert summary["runner"] == "uvx"


def test_init_uvx_runner_supports_custom_package_spec(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(install.subprocess, "run", fake_run)
    monkeypatch.setattr(install.shutil, "which", lambda name: "uvx.exe" if name == "uvx" else None)

    summary = install.run_init(
        config_path=tmp_path / "config.json",
        memory_path=tmp_path / "CLAUDE.md",
        settings_path=tmp_path / "settings.json",
        runner="uvx",
        uvx_package="cc-web-mcp==0.1.0",
    )

    assert calls[0][-2:] == ["uvx.exe", "cc-web-mcp==0.1.0"]
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    hook_command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert hook_command == "uvx.exe cc-web-mcp==0.1.0 hook-guard"
    assert summary["uvx_package"] == "cc-web-mcp==0.1.0"


def test_uvx_hook_command_normalizes_windows_launcher_path(monkeypatch):
    monkeypatch.setattr(install.os, "name", "nt")
    monkeypatch.setattr(install.shutil, "which", lambda name: r"C:\Program Files\uv\uvx.exe" if name == "uvx.exe" else None)

    command = install.build_uvx_guard_command("cc-web-mcp")

    assert command == "'C:/Program Files/uv/uvx.exe' cc-web-mcp hook-guard"


def test_init_uvx_runner_dry_run_shows_uvx_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: "uvx" if name == "uvx" else None)

    summary = install.run_init(
        config_path=tmp_path / "config.json",
        memory_path=tmp_path / "CLAUDE.md",
        settings_path=tmp_path / "settings.json",
        runner="uvx",
        dry_run=True,
    )

    assert summary["mcp_registration_command"].endswith("cc-web -- uvx cc-web-mcp")
    assert not (tmp_path / "settings.json").exists()


def test_register_claude_mcp_resolves_windows_cmd_launcher(monkeypatch):
    calls: list[list[str]] = []

    def fake_which(name):
        if name == "claude":
            return r"E:\Program Files\nodejs\node_cache\claude.CMD"
        return None

    def fake_run(command, **kwargs):
        calls.append(list(command))

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(install.shutil, "which", fake_which)
    monkeypatch.setattr(install.subprocess, "run", fake_run)

    registered, command, stdout, stderr = install.register_claude_mcp()

    assert registered is True
    assert command[0] == r"E:\Program Files\nodejs\node_cache\claude.CMD"
    assert calls == [command]
    assert stdout == "ok"
    assert stderr == ""


def test_resolve_claude_command_prefers_windows_cmd_launcher(monkeypatch):
    def fake_which(name):
        paths = {
            "claude": r"E:\Program Files\nodejs\node_cache\claude",
            "claude.cmd": r"E:\Program Files\nodejs\node_cache\claude.CMD",
        }
        return paths.get(name)

    monkeypatch.setattr(install.os, "name", "nt")
    monkeypatch.setattr(install.shutil, "which", fake_which)

    assert install.resolve_claude_command() == r"E:\Program Files\nodejs\node_cache\claude.CMD"


def test_init_skip_mcp_does_not_call_claude(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(install.subprocess, "run", lambda command, **kwargs: calls.append(list(command)))

    summary = install.run_init(
        config_path=tmp_path / "config.json",
        memory_path=tmp_path / "CLAUDE.md",
        settings_path=tmp_path / "settings.json",
        skip_mcp=True,
    )

    assert calls == []
    assert summary["mcp_registered"] is None


def test_init_dry_run_does_not_write_or_call_claude(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(install.subprocess, "run", lambda command, **kwargs: calls.append(list(command)))
    config = tmp_path / "config.json"
    memory = tmp_path / "CLAUDE.md"
    settings = tmp_path / "settings.json"

    summary = install.run_init(
        config_path=config,
        memory_path=memory,
        settings_path=settings,
        dry_run=True,
    )

    assert calls == []
    assert not config.exists()
    assert not memory.exists()
    assert not settings.exists()
    assert summary["dry_run"] is True
    assert summary["mcp_registered"] is None


def test_install_hooks_use_module_command(tmp_path):
    settings = tmp_path / "settings.json"

    changed, _ = install.install_hooks(settings, "py -3.11")

    data = json.loads(settings.read_text(encoding="utf-8"))
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert changed is True
    assert "-m cc_web_mcp.hooks.guard" in command
    assert "hooks/guard.py" not in command.replace("\\", "/")
