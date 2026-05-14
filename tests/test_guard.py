import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks" / "guard.py"


def run_guard(
    state_path: Path,
    payload: dict,
    env: dict | None = None,
    config_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(GUARD), "--state", str(state_path)]
    if config_path is not None:
        args.extend(["--config", str(config_path)])
    return subprocess.run(
        args,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_session_start_records_model(tmp_path):
    state = tmp_path / "state.json"
    result = run_guard(
        state,
        {
            "hook_event_name": "SessionStart",
            "session_id": "s1",
            "model": "deepseek-v4-flash",
        },
    )

    assert result.returncode == 0
    assert json.loads(state.read_text(encoding="utf-8"))["s1"]["model"] == "deepseek-v4-flash"


def test_pre_tool_use_blocks_non_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "Allowed model keywords" in output["permissionDecisionReason"]
    assert "deepseek" in output["permissionDecisionReason"]


def test_pre_tool_use_blocks_claude_fetch_url_by_default(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc-web__fetch_url",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "WebFetch" in output["permissionDecisionReason"]


def test_pre_tool_use_allows_claude_fetch_url_when_configured(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    config.write_text(
        json.dumps(
            {
                "allowed_model_patterns": ["deepseek"],
                "allow_fetch_url_for_claude": True,
            }
        ),
        encoding="utf-8",
    )

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc-web__fetch_url",
        },
        config_path=config,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_allows_short_claude_model_name_fetch_url_when_configured(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "sonnet"}}), encoding="utf-8")
    config.write_text(json.dumps({"allow_fetch_url_for_claude": True}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__fetch_url",
        },
        config_path=config,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_still_blocks_claude_research_brief_when_fetch_override_is_enabled(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    config.write_text(json.dumps({"allow_fetch_url_for_claude": True}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc-web__research_brief",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_allows_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "deepseek-v4-pro[1m]"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__fetch_url",
        },
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_blocks_native_web_search_for_allowed_model_by_default(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "deepseek-v4-flash"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebSearch",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "cc-web" in output["permissionDecisionReason"]
    assert "research_brief" in output["permissionDecisionReason"]
    assert "additionalContext" in output
    assert "mcp__cc-web__research_brief" in output["additionalContext"]
    assert "Do not retry WebSearch" in output["additionalContext"]


def test_pre_tool_use_blocks_native_web_fetch_for_allowed_model_by_default(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "qwen3-coder"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek", "qwen"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebFetch",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "fetch_url" in output["permissionDecisionReason"]
    assert "mcp__cc-web__fetch_url" in output["additionalContext"]
    assert "Do not retry WebFetch" in output["additionalContext"]


def test_pre_tool_use_allows_native_web_for_allowed_model_when_disabled(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "deepseek-v4-flash"}}), encoding="utf-8")
    config.write_text(
        json.dumps(
            {
                "allowed_model_patterns": ["deepseek"],
                "block_native_web_for_allowed_models": False,
            }
        ),
        encoding="utf-8",
    )

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebSearch",
        },
        config_path=config,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_allows_native_web_for_claude_model(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebSearch",
        },
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_blocks_native_web_for_allowed_environment_when_model_is_missing(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({}), encoding="utf-8")
    env = {**os.environ, "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]"}

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebSearch",
        },
        env=env,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_uses_recorded_model_before_environment_for_native_web(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    env = {**os.environ, "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]"}

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "WebSearch",
        },
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_blocks_hyphenated_cc_web_tool_name(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc-web__web_search",
        },
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_uses_recorded_model_before_deepseek_environment_alias(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "sonnet"}}), encoding="utf-8")
    env = {**os.environ, "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]"}

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
        env=env,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_allows_deepseek_environment_alias_when_recorded_model_is_missing(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({}), encoding="utf-8")
    env = {**os.environ, "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]"}

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_allows_configured_non_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "qwen3-coder"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek", "qwen"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
        config_path=config,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_block_message_mentions_configured_model_patterns(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek", "qwen"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__fetch_url",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "deepseek, qwen" in output["permissionDecisionReason"]
