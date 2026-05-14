from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path


START_MARKER = "<!-- cc-web-mcp:start -->"
END_MARKER = "<!-- cc-web-mcp:end -->"
INSTRUCTION_BLOCK = f"""{START_MARKER}
## cc-web MCP routing for third-party models

When the current Claude Code model is DeepSeek, Qwen, Kimi, or another third-party model that lacks working native web tools:

- Do not call WebSearch. Some third-party Anthropic-compatible APIs reject WebSearch before Claude Code local hooks can run.
- For web research or current information, call `mcp__cc-web__research_brief` first.
- If raw search results are needed, call `mcp__cc-web__web_search`.
- If a specific URL must be read, call `mcp__cc-web__fetch_url`.
- Official Claude models should continue to prefer native `WebSearch` / `WebFetch`.
{END_MARKER}"""


def default_memory_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.cc-web-backup.{timestamp}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def replace_block(text: str) -> tuple[str, bool]:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start != -1 and end != -1 and end >= start:
        end += len(END_MARKER)
        new_text = text[:start].rstrip() + "\n\n" + INSTRUCTION_BLOCK + "\n\n" + text[end:].lstrip()
        return new_text.rstrip() + "\n", new_text != text

    if text.strip():
        return text.rstrip() + "\n\n" + INSTRUCTION_BLOCK + "\n", True
    return INSTRUCTION_BLOCK + "\n", True


def install_instructions(memory_path: Path) -> tuple[bool, Path | None]:
    old_text = memory_path.read_text(encoding="utf-8-sig") if memory_path.exists() else ""
    new_text, changed = replace_block(old_text)
    backup_path = None
    if changed:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = backup_file(memory_path)
        memory_path.write_text(new_text, encoding="utf-8")
    return changed, backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install cc-web instructions into Claude Code memory.")
    parser.add_argument("--memory", default=str(default_memory_path()))
    args = parser.parse_args()

    memory_path = Path(os.path.expanduser(args.memory))
    changed, backup_path = install_instructions(memory_path)
    if changed:
        print(f"已更新: {memory_path}")
        if backup_path is not None:
            print(f"备份: {backup_path}")
    else:
        print(f"无需更新: {memory_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

