import json
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts" / "doctor.py"


def load_doctor_module():
    spec = importlib.util.spec_from_file_location("cc_web_doctor_under_test", DOCTOR)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_doctor(config_path: Path, claude_path: Path, settings_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(DOCTOR),
            "--config",
            str(config_path),
            "--claude-memory",
            str(claude_path),
            "--settings",
            str(settings_path),
            "--json",
            "--skip-network",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_doctor_text(config_path: Path, claude_path: Path, settings_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(DOCTOR),
            "--config",
            str(config_path),
            "--claude-memory",
            str(claude_path),
            "--settings",
            str(settings_path),
            "--skip-network",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_doctor_reports_missing_claude_instructions_and_hook(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["checks"]["config"]["ok"] is True
    assert report["checks"]["claude_instructions"]["ok"] is False
    assert report["checks"]["hook_guard"]["ok"] is False
    assert any("install_instructions.py" in item for item in report["recommendations"])
    assert any("install_hook.py" in item for item in report["recommendations"])


def test_doctor_text_output_keeps_english_prompts(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    result = run_doctor_text(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    assert "cc-web doctor: Needs attention" in result.stdout
    assert "Recommendations:" in result.stdout
    assert "Run scripts/install_instructions.py" in result.stdout
    assert "Run scripts/install_hook.py" in result.stdout


def test_doctor_passes_when_local_files_are_configured(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 ./hooks/guard.py"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": hook_command,
                                }
                            ],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": hook_command,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["checks"]["claude_instructions"]["ok"] is True
    assert report["checks"]["hook_guard"]["ok"] is True


def test_doctor_fails_when_guard_is_only_registered_for_session_start(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "py -3.11 ./hooks/guard.py",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["checks"]["hook_guard"]["ok"] is False
    assert report["checks"]["hook_guard"]["session_start"] is True
    assert report["checks"]["hook_guard"]["pre_tool_use"] is False


def test_doctor_fails_when_pre_tool_matcher_does_not_cover_webfetch(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 ./hooks/guard.py"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^mcp__cc[-_]web__.*$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["checks"]["hook_guard"]["ok"] is False
    assert report["checks"]["hook_guard"]["session_start"] is True
    assert report["checks"]["hook_guard"]["pre_tool_use"] is False
    assert "WebFetch" in report["checks"]["hook_guard"]["pre_tool_use_reason"]


def test_build_report_runs_network_check_when_not_skipped(tmp_path, monkeypatch):
    doctor = load_doctor_module()
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 ./hooks/guard.py"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_network_check():
        calls.append(True)
        return {
            "ok": True,
            "first_available_search_backend": "bing_cn",
            "search_backend_status": {"bing_cn": {"ok": True}},
        }, []

    monkeypatch.setattr(doctor, "_check_network", fake_network_check, raising=False)

    report = doctor.build_report(config, claude_memory, settings, skip_network=False)

    assert calls == [True]
    assert report["ok"] is True
    assert report["checks"]["network"]["first_available_search_backend"] == "bing_cn"
