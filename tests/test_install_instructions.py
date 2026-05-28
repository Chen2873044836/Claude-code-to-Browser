import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_INSTRUCTIONS = ROOT / "scripts" / "install_instructions.py"
START_MARKER = "<!-- cc-web-mcp:start -->"
END_MARKER = "<!-- cc-web-mcp:end -->"


def run_install(memory_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALL_INSTRUCTIONS), "--memory", str(memory_path)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_install_instructions_creates_user_memory_block(tmp_path):
    memory = tmp_path / "CLAUDE.md"

    result = run_install(memory)

    assert result.returncode == 0, result.stderr
    text = memory.read_text(encoding="utf-8")
    assert START_MARKER in text
    assert END_MARKER in text
    assert "cc-web MCP" in text
    assert "mcp__cc-web__research_brief" in text
    assert "mcp__cc-web__fetch_url" in text
    assert "mcp__cc-web__web_search" in text


def test_install_instructions_preserves_existing_content_and_is_idempotent(tmp_path):
    memory = tmp_path / "CLAUDE.md"
    memory.write_text("# Existing\n\nKeep this.\n", encoding="utf-8")

    first = run_install(memory)
    second = run_install(memory)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    text = memory.read_text(encoding="utf-8")
    assert text.startswith("# Existing\n\nKeep this.")
    assert text.count(START_MARKER) == 1
    assert text.count(END_MARKER) == 1


def test_install_instructions_replaces_old_block(tmp_path):
    memory = tmp_path / "CLAUDE.md"
    memory.write_text(
        f"before\n\n{START_MARKER}\nold text\n{END_MARKER}\n\nafter\n",
        encoding="utf-8",
    )

    result = run_install(memory)

    assert result.returncode == 0, result.stderr
    text = memory.read_text(encoding="utf-8")
    assert "before" in text
    assert "after" in text
    assert "old text" not in text
    assert text.count(START_MARKER) == 1

