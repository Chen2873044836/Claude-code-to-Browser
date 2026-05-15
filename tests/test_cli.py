from __future__ import annotations

import cc_web_mcp.cli as cli


def test_cli_dispatches_init_command(monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_main(argv=None):
        captured["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("cc_web_mcp.install.main", fake_main)

    result = cli.main(["init", "--dry-run", "--config", "tmp-config.json"])

    assert result == 0
    assert captured["argv"] == ["--dry-run", "--config", "tmp-config.json"]


def test_cli_uses_process_argv_when_argv_is_none(monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_main(argv=None):
        captured["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("cc_web_mcp.install.main", fake_main)
    monkeypatch.setattr("sys.argv", ["cc-web-mcp", "init", "--dry-run"])

    result = cli.main()

    assert result == 0
    assert captured["argv"] == ["--dry-run"]


def test_cli_dispatches_doctor_command(monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_main(argv=None):
        captured["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("cc_web_mcp.doctor.main", fake_main)

    result = cli.main(["doctor", "--json", "--skip-network"])

    assert result == 0
    assert captured["argv"] == ["--json", "--skip-network"]


def test_cli_defaults_to_serve(monkeypatch):
    called = []

    def fake_run_stdio():
        called.append(True)

    monkeypatch.setattr("cc_web_mcp.server.run_stdio", fake_run_stdio)

    result = cli.main([])

    assert result == 0
    assert called == [True]


def test_cli_dispatches_config_path(monkeypatch, capsys):
    monkeypatch.setenv("CC_WEB_MCP_CONFIG", "tmp-config.json")

    result = cli.main(["config", "path"])

    assert result == 0
    assert "tmp-config.json" in capsys.readouterr().out


def test_cli_dispatches_config_init(tmp_path, monkeypatch):
    config = tmp_path / "config.json"

    result = cli.main(["config", "init", "--config", str(config)])

    assert result == 0
    assert config.exists()


def test_cli_dispatches_hook_guard(monkeypatch):
    captured: list[bool] = []

    def fake_main(argv=None):
        captured.extend(list(argv or []))
        return 0

    monkeypatch.setattr("cc_web_mcp.hooks.guard.main", fake_main)

    result = cli.main(["hook-guard"])

    assert result == 0
    assert captured == []


def test_cli_passes_hook_guard_arguments(monkeypatch):
    captured: list[str] = []

    def fake_main(argv=None):
        captured.extend(list(argv or []))
        return 0

    monkeypatch.setattr("cc_web_mcp.hooks.guard.main", fake_main)

    result = cli.main(["hook-guard", "--config", "config.json", "--state", "state.json"])

    assert result == 0
    assert captured == ["--config", "config.json", "--state", "state.json"]
